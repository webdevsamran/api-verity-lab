"""Universal contract loader.

Detects the protocol of a spec file/URL and dispatches to the matching
spec plugin (built-in or registered via the ``apiverity.specs`` entry
point group).
"""

from __future__ import annotations

from typing import Optional

from apiverity.core.model import Finding, Service
from apiverity.plugins.registry import PluginRegistry
from apiverity.specs import SpecPlugin, read_source


def _builtin_plugins() -> list[SpecPlugin]:
    from apiverity.specs.graphql import GraphQlSpecPlugin
    from apiverity.specs.grpc import GrpcSpecPlugin
    from apiverity.specs.openapi import OpenApiSpecPlugin

    return [OpenApiSpecPlugin(), GraphQlSpecPlugin(), GrpcSpecPlugin()]


def detect_and_load(
    source: str, registry: Optional[PluginRegistry] = None
) -> tuple[Service, list[Finding], SpecPlugin]:
    """Load a contract from any supported format."""
    _, raw = read_source(source)
    plugins = list(_builtin_plugins())
    if registry is not None:
        plugins.extend(registry.spec_plugins())

    for plugin in plugins:
        try:
            if plugin.detect(source, raw):
                service, findings = plugin.load(source)
                return service, findings, plugin
        except NotImplementedError:
            continue
    raise ValueError(f"no spec plugin could handle '{source}'")