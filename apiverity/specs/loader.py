"""Universal contract loader.

Detects the protocol of a spec file/URL and dispatches to the matching
spec plugin (built-in or registered via the ``apiverity.specs`` entry
point group).
"""

from __future__ import annotations

from apiverity.core.model import Finding, Service
from apiverity.plugins.registry import PluginRegistry
from apiverity.specs import SpecPlugin, UnrecognizedSpecError, read_source


def _builtin_plugins(*, allow_remote_refs: bool = False) -> list[SpecPlugin]:
    from apiverity.specs.asyncapi import AsyncApiSpecPlugin
    from apiverity.specs.graphql import GraphQlSpecPlugin
    from apiverity.specs.grpc import GrpcSpecPlugin
    from apiverity.specs.mcp import McpSpecPlugin
    from apiverity.specs.openapi import OpenApiSpecPlugin
    from apiverity.specs.swagger2 import Swagger2SpecPlugin

    # Order matters. MCP sits ahead of GraphQL and gRPC because those two sniff
    # for substrings ("type Query", a `service` declaration) that can occur
    # inside a JSON tool description, and behind OpenAPI/Swagger, whose own
    # markers are unambiguous.
    return [
        OpenApiSpecPlugin(allow_remote_refs=allow_remote_refs),
        Swagger2SpecPlugin(),
        McpSpecPlugin(),
        GraphQlSpecPlugin(),
        GrpcSpecPlugin(),
        AsyncApiSpecPlugin(),
    ]


def detect_and_load(
    source: str,
    registry: PluginRegistry | None = None,
    *,
    allow_remote_refs: bool = False,
) -> tuple[Service, list[Finding], SpecPlugin]:
    """Load a contract from any supported format.

    `allow_remote_refs` permits the OpenAPI bundler to fetch a `$ref` that
    names a URL. Off by default: a URL inside a document makes this process
    request an address the caller never chose.
    """
    _, raw = read_source(source)
    plugins = list(_builtin_plugins(allow_remote_refs=allow_remote_refs))
    if registry is not None:
        plugins.extend(p for p in registry.instances() if isinstance(p, SpecPlugin))

    for plugin in plugins:
        try:
            if plugin.detect(source, raw):
                service, findings = plugin.load(source)
                return service, findings, plugin
        except NotImplementedError:
            continue
    tried: list[str] = []
    for plugin in plugins:
        name = plugin.protocol().value
        if name not in tried:  # OpenAPI and Swagger 2.0 share a protocol value
            tried.append(name)
    raise UnrecognizedSpecError(source, tried=tried)
