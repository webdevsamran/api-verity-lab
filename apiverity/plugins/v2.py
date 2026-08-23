"""Plugin API v2: manifests, capability negotiation and failure isolation.

A v2 plugin ships a :class:`PluginManifest` declaring its identity, the
``api_version`` it targets, its capabilities and a host compatibility range.
The :class:`PluginManager` loads plugins with per-plugin failure isolation so
one broken plugin can never take down a CLI run, and records diagnostics for
every load attempt. Remote code is never auto-installed; plugins are only
discovered from explicitly installed entry points or explicit local paths.
"""

from __future__ import annotations

import importlib
import traceback
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

#: The plugin API version this host implements. Bumped on breaking changes.
HOST_PLUGIN_API_VERSION = "2.0"

KNOWN_CAPABILITIES = frozenset(
    {
        "spec_adapter",
        "rules",
        "generators",
        "transports",
        "auth_providers",
        "checks",
        "reporters",
        "exporters",
    }
)


class PluginManifest(BaseModel):
    """Declarative metadata every v2 plugin must provide."""

    name: str
    version: str
    api_version: str = HOST_PLUGIN_API_VERSION
    description: str = ""
    author: str | None = None
    license: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    host_compatibility: str = f">={HOST_PLUGIN_API_VERSION}"
    entry_point: str  # "package.module:attribute"
    config_schema: dict[str, Any] = Field(default_factory=dict)

    def validate_capabilities(self) -> list[str]:
        """Return unknown capability names (empty means valid)."""
        return [c for c in self.capabilities if c not in KNOWN_CAPABILITIES]

    def supports_host(self, host_api: str = HOST_PLUGIN_API_VERSION) -> bool:
        """Simple major-version compatibility negotiation."""
        try:
            want_major = int(self.api_version.split(".")[0])
            host_major = int(host_api.split(".")[0])
        except (ValueError, IndexError):
            return False
        return want_major == host_major


@dataclass
class LoadDiagnostic:
    """Outcome of one plugin load attempt."""

    name: str
    ok: bool
    error: str | None = None
    traceback: str | None = None


@dataclass
class LoadedPlugin:
    manifest: PluginManifest
    instance: Any
    diagnostic: LoadDiagnostic = field(init=False)

    def __post_init__(self) -> None:
        self.diagnostic = LoadDiagnostic(name=self.manifest.name, ok=True)


class PluginManager:
    """Loads v2 plugins with isolation and collects diagnostics."""

    def __init__(self, *, host_api: str = HOST_PLUGIN_API_VERSION) -> None:
        self.host_api = host_api
        self.diagnostics: list[LoadDiagnostic] = []
        self.loaded: list[LoadedPlugin] = []

    def load_from_manifest(self, manifest: PluginManifest) -> LoadedPlugin | None:
        problems = manifest.validate_capabilities()
        if problems:
            diag = LoadDiagnostic(
                name=manifest.name,
                ok=False,
                error=f"unknown capabilities: {', '.join(problems)}",
            )
            self.diagnostics.append(diag)
            return None
        if not manifest.supports_host(self.host_api):
            diag = LoadDiagnostic(
                name=manifest.name,
                ok=False,
                error=(
                    f"plugin targets plugin-api {manifest.api_version}, "
                    f"host provides {self.host_api}"
                ),
            )
            self.diagnostics.append(diag)
            return None
        try:
            module_name, _, attr = manifest.entry_point.partition(":")
            module = importlib.import_module(module_name)
            instance = getattr(module, attr) if attr else module
            loaded = LoadedPlugin(manifest=manifest, instance=instance)
            self.loaded.append(loaded)
            self.diagnostics.append(LoadDiagnostic(name=manifest.name, ok=True))
            return loaded
        except Exception as exc:
            diag = LoadDiagnostic(
                name=manifest.name,
                ok=False,
                error=str(exc),
                traceback=traceback.format_exc(),
            )
            self.diagnostics.append(diag)
            return None

    def call_isolated(self, loaded: LoadedPlugin, method: str, *args: Any) -> tuple[Any, str | None]:
        """Invoke ``method`` on a plugin, capturing any exception.

        Returns ``(result, error)``; exactly one of the two is None.
        """
        try:
            fn = getattr(loaded.instance, method)
            return fn(*args), None
        except Exception as exc:
            return None, f"{loaded.manifest.name}.{method} failed: {exc}"

    def by_capability(self, capability: str) -> list[LoadedPlugin]:
        return [p for p in self.loaded if capability in p.manifest.capabilities]
