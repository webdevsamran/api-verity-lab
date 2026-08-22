"""Plugin discovery and registry.

Built-in plugins are always available; external plugins are discovered
through the six entry-point groups declared in their own packages.
"""

from __future__ import annotations

import sys
from typing import Any

if sys.version_info >= (3, 10):
    from importlib.metadata import entry_points
else:  # pragma: no cover
    from importlib_metadata import entry_points

from apiverity import PLUGIN_API_VERSION
from apiverity.plugins.api import CheckPlugin, ExporterPlugin, GeneratorPlugin, RulePlugin
from apiverity.specs import SpecPlugin

_ENTRY_POINT_GROUPS = {
    "specs": "apiverity.specs",
    "rules": "apiverity.rules",
    "checks": "apiverity.checks",
    "generators": "apiverity.generators",
    "exporters": "apiverity.exporters",
    "transports": "apiverity.transports",
}


class PluginRegistry:
    """Loads and caches plugins from all entry-point groups."""

    def __init__(self) -> None:
        self._cache: dict[str, list[Any]] = {}
        self.warnings: list[str] = []

    def _load_group(self, group_key: str) -> list[Any]:
        if group_key in self._cache:
            return self._cache[group_key]
        loaded: list[Any] = []
        try:
            eps = entry_points(group=_ENTRY_POINT_GROUPS[group_key])
        except TypeError:  # pragma: no cover - older Python fallback
            eps = entry_points().get(_ENTRY_POINT_GROUPS[group_key], [])
        for ep in eps:
            try:
                obj = ep.load()
                instance = obj() if isinstance(obj, type) else obj
                version = getattr(instance, "PLUGIN_API_VERSION", None)
                if version is not None and version != PLUGIN_API_VERSION:
                    self.warnings.append(
                        f"plugin '{ep.name}' declares plugin API {version}, "
                        f"expected {PLUGIN_API_VERSION}; skipped"
                    )
                    continue
                loaded.append(instance)
            except Exception as exc:  # noqa: BLE001 - plugin isolation
                self.warnings.append(f"failed to load plugin '{ep.name}': {exc}")
        self._cache[group_key] = loaded
        return loaded

    def spec_plugins(self) -> list[SpecPlugin]:
        return list(self._load_group("specs"))

    def rule_plugins(self) -> list[RulePlugin]:
        return list(self._load_group("rules"))

    def check_plugins(self) -> list[CheckPlugin]:
        return list(self._load_group("checks"))

    def generator_plugins(self) -> list[GeneratorPlugin]:
        return list(self._load_group("generators"))

    def exporter_plugins(self) -> list[ExporterPlugin]:
        return list(self._load_group("exporters"))

    def transport_plugins(self) -> list[Any]:
        return list(self._load_group("transports"))

    def summary(self) -> dict[str, list[str]]:
        return {
            key: [type(p).__module__ + ":" + type(p).__name__ for p in self._load_group(key)]
            for key in _ENTRY_POINT_GROUPS
        }