"""Conformance kit for plugin authors.

Run :func:`run_conformance` against any object to verify it satisfies the
v2 plugin contract: valid manifest, declared capabilities it actually
implements, deterministic behavior and safe failure modes. Returns a list of
human-readable failures; an empty list means the plugin conforms.
"""

from __future__ import annotations

from typing import Any

from apiverity.plugins.v2 import KNOWN_CAPABILITIES, PluginManifest


def run_conformance(instance: Any) -> list[str]:
    """Check ``instance`` against the v2 plugin contract."""
    failures: list[str] = []

    manifest = getattr(instance, "manifest", None)
    if not isinstance(manifest, PluginManifest):
        return ["missing or invalid 'manifest' attribute (expected PluginManifest)"]

    if manifest.validate_capabilities():
        failures.append(f"unknown capabilities: {manifest.validate_capabilities()}")

    if not manifest.supports_host():
        failures.append(f"manifest api_version {manifest.api_version} != host major version")

    # Every declared capability must map to a callable method.
    capability_methods = {
        "spec_adapter": "load_spec",
        "rules": "check",
        "generators": "generate",
        "transports": "make_client",
        "auth_providers": "apply_auth",
        "checks": "run_check",
        "reporters": "render",
        "exporters": "export",
    }
    for cap in manifest.capabilities:
        method = capability_methods.get(cap)
        if method is None:
            continue
        if not callable(getattr(instance, method, None)):
            failures.append(f"capability '{cap}' requires a callable '{method}()'")

    # Determinism probe: call the primary method twice with identical input.
    for cap in ("rules", "checks"):
        method = capability_methods.get(cap)
        fn = getattr(instance, method, None) if method else None
        if callable(fn):
            try:
                first = fn(None)
                second = fn(None)
                if repr(first) != repr(second):
                    failures.append(f"{method}() is not deterministic on empty input")
            except Exception as exc:
                failures.append(f"{method}(None) raised {type(exc).__name__}: {exc}")

    return failures


def conformance_report(instance: Any) -> dict[str, Any]:
    """Structured report suitable for CI output."""
    failures = run_conformance(instance)
    manifest = getattr(instance, "manifest", None)
    return {
        "plugin": getattr(manifest, "name", type(instance).__name__),
        "version": getattr(manifest, "version", "unknown"),
        "conforms": not failures,
        "failures": failures,
        "known_capabilities": sorted(KNOWN_CAPABILITIES),
    }
