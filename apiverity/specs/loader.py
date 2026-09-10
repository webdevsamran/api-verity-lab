"""Universal contract loader.

Detects the protocol of a spec file/URL and dispatches to the matching
spec plugin (built-in or registered via the ``apiverity.specs`` entry
point group).
"""

from __future__ import annotations

from apiverity.core.model import Finding, Service, Severity, SourceLocation
from apiverity.plugins.registry import PluginRegistry
from apiverity.specs import SpecPlugin, UnrecognizedSpecError, read_source


class UnknownSpecFormatError(ValueError):
    """`--spec-format` named something no plugin provides."""

    def __init__(self, requested: str, *, known: list[str]) -> None:
        self.requested = requested
        self.known = known
        super().__init__(f"unknown spec format {requested!r}; known formats: {', '.join(known)}")


def _detects(plugin: SpecPlugin, source: str, raw: bytes) -> bool:
    """Would this plugin have claimed the document on its own?

    A plugin whose `detect` raises has not said no -- it has failed to answer,
    and treating that as a disagreement would attach a warning to a document
    the caller named correctly.
    """
    try:
        return bool(plugin.detect(source, raw))
    except Exception:
        return True


def _by_format(plugins: list[SpecPlugin], name: str) -> SpecPlugin | None:
    """Find the plugin for a format name.

    Matched on the class name rather than on `protocol()`, because two builtin
    plugins share `Protocol.OPENAPI` and a third-party plugin may share a
    protocol with a builtin one. A plugin can name itself by defining
    `spec_format`; the fallback derives a name from the class so every existing
    plugin is addressable without changing the interface.
    """
    wanted = name.strip().lower()
    for plugin in plugins:
        declared = getattr(plugin, "spec_format", None)
        if isinstance(declared, str) and declared.lower() == wanted:
            return plugin
        derived = type(plugin).__name__.removesuffix("SpecPlugin").lower()
        if derived == wanted:
            return plugin
    return None


#: `--spec-format` names, mapped to the plugin class that handles them. Keyed
#: by the *format*, not by the protocol: OpenAPI and Swagger 2.0 share
#: `Protocol.OPENAPI`, and the whole point of an override is to name the one
#: the sniffer got wrong.
SPEC_FORMATS = (
    "openapi",
    "swagger2",
    "asyncapi",
    "graphql",
    "grpc",
    "mcp",
)


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
    spec_format: str | None = None,
) -> tuple[Service, list[Finding], SpecPlugin]:
    """Load a contract from any supported format.

    `allow_remote_refs` permits the OpenAPI bundler to fetch a `$ref` that
    names a URL. Off by default: a URL inside a document makes this process
    request an address the caller never chose.

    `spec_format` skips detection and names the plugin outright. Detection is
    content sniffing -- substrings like `openapi:` and `type Query` -- and it
    has no escape hatch otherwise, so a document that contains the wrong words
    (a GraphQL SDL discussing OpenAPI, a JSON tool manifest whose description
    mentions a `service`) is unloadable by any means. A misdetection also fails
    as a parse error about a format the caller never asked for, which is a bad
    error message on top of a wrong answer.
    """
    plugins = list(_builtin_plugins(allow_remote_refs=allow_remote_refs))
    if registry is not None:
        plugins.extend(p for p in registry.instances() if isinstance(p, SpecPlugin))

    chosen: SpecPlugin | None = None
    if spec_format:
        # Checked before the file is read: an unknown format name is a mistake
        # in the command, and reporting it as "file not found" would send the
        # caller to look at the path.
        chosen = _by_format(plugins, spec_format)
        if chosen is None:
            raise UnknownSpecFormatError(spec_format, known=sorted(SPEC_FORMATS))

    _, raw = read_source(source)

    if chosen is not None:
        # Detection is skipped, not reordered. An override that only moved a
        # plugin to the front would still fall through to another one when the
        # named plugin declined -- which is the misdetection being overridden,
        # reached a second time and now silently.
        findings: list[Finding] = []
        if not _detects(chosen, source, raw):
            # Honoured anyway. The caller may know something the sniffer does
            # not; they should still be told the two disagree, because the
            # other explanation is a typo in the flag.
            findings.append(
                Finding(
                    rule_id="SPEC-FORMAT-OVERRIDDEN",
                    severity=Severity.WARN,
                    message=(
                        f"loaded as '{spec_format}' because it was named explicitly; "
                        "content detection does not recognise this document as that "
                        "format. Findings below come from that parser"
                    ),
                    location=SourceLocation(file=source, pointer=""),
                )
            )
        service, loaded = chosen.load(source)
        return service, findings + loaded, chosen

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
