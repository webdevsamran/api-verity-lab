"""Normalize an MCP `tools/list` manifest into the shared contract model.

An MCP server's tool manifest is a contract in exactly the shape this engine
already governs: a set of callable operations, each with a declared input
schema and sometimes a declared output schema. Compiling it into the same
`Service` the OpenAPI, GraphQL, gRPC and AsyncAPI adapters produce is what
lets a manifest change land in the same diff, the same rule catalogue, the same
`result-v1` artifact and the same CI gate as an OpenAPI change.

What upstream does and does not give us
---------------------------------------
The spec (revision 2026-07-28) defines the object precisely: a Tool has a
required `name` and a required `inputSchema`, and optional `title`,
`description`, `icons`, `outputSchema`, `annotations` and `_meta`. Schemas
default to JSON Schema 2020-12.

It defines nothing at all about what a *change* to that object means. Tools
carry no version field, and SEP-1575 "Tool Semantic Versioning" is an open,
dormant, unsponsored proposal. So the breaking-change taxonomy in
`apiverity/rules/breaking.py` is this project's own, and says so wherever it
is published.

Three decisions worth reading
-----------------------------
**The response status is "result", not "200".** A JSON-RPC result has no status
code. Inventing `"200"` would assert an HTTP outcome the protocol never
produces, and `diff/compat.py::_status_codes` classifies on `startswith("2")`,
so the invented code would draw HTTP-flavoured severities out of the rule
engine. gRPC set the precedent with `"OK"`.

**Volatile fields are excluded by whitelist, not blacklist.** `ttlMs`,
`cacheScope` and `nextCursor` are cache and pagination state that differ run to
run; they are never copied into the model, so nothing downstream can diff them.
A blacklist of fields-to-drop starts leaking the moment the next revision adds
another cache hint.

**The four annotation hints stay in `bindings`.** Mapping `idempotentHint` onto
`Operation.idempotent` is tempting and wrong: the spec says clients MUST treat
annotations as untrusted unless the server is trusted, while every other
populator of that field is an authoritative declaration. Collapsing them would
let an HTTP-oriented rule speak with more confidence than the source supports.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ...core.model import (
    Finding,
    Operation,
    OperationKind,
    Protocol,
    RequestBody,
    Response,
    Service,
    Severity,
    SourceLocation,
)
from .. import SpecPlugin, parse_document, read_source
from ..openapi.parser import OpenApiParser

#: JSON-RPC frames JSON on both stdio and Streamable HTTP. This is a factual
#: statement about the wire format, not HTTP content negotiation -- and because
#: both sides of a diff always carry exactly this one key, the media add/remove
#: branches in `diff/compat.py` can never fire spuriously on an MCP contract.
MCP_MEDIA_TYPE = "application/json"

#: A JSON-RPC result has no status code; see the module docstring.
MCP_RESULT_STATUS = "result"

#: Cache and pagination state on a `tools/list` result. Read during parsing to
#: decide the protocol era, never carried into the model.
_VOLATILE_KEYS = ("ttlMs", "cacheScope", "nextCursor")

#: Fields new in the 2026-07-28 list-result envelope.
_MODERN_MARKERS = ("resultType", "ttlMs", "cacheScope")

#: The four ToolAnnotations hints, iterated in a fixed order so a report is
#: byte-identical across runs (AGENTS.md: determinism).
ANNOTATION_HINTS = ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint")

#: JSON Schema 2020-12 keywords `OpenApiParser.to_schema` still does not model.
#: A schema using one is parsed with that keyword silently dropped, which would
#: mean the diff cannot see changes to it -- so the loader says so rather than
#: asserting a simpler schema than the document declares.
#:
#: This list was thirteen keywords long. `prefixItems`, `if`/`then`/`else`,
#: `dependentRequired`, `dependentSchemas`, `contains`, `patternProperties` and
#: `propertyNames` are modelled now; what remains are the two `unevaluated*`
#: keywords, whose meaning depends on which other keywords have already
#: matched, and the two `$dynamic*` ones, which need runtime resolution scope.
#: Both are real work rather than oversights, and saying which is which is the
#: point of keeping the list.
_UNMODELLED_KEYWORDS = (
    "unevaluatedProperties",
    "unevaluatedItems",
    "$dynamicRef",
    "$dynamicAnchor",
)

#: The revision that made MCP stateless. Manifests recording this or later are
#: "modern"; 2025-11-25 and earlier are "legacy" and still in the wild.
_MODERN_FROM = "2026-07-28"

_PROTOCOL_VERSION_META = "io.modelcontextprotocol/protocolVersion"


class ManifestShapeError(ValueError):
    """The document is not an MCP tool manifest."""


def unwrap_manifest(doc: Any) -> tuple[list[Any], dict[str, Any]]:
    """Return ``(tools, envelope)`` for any shape a saved manifest arrives in.

    Four shapes are accepted, and the asymmetry between them is the point.

    ``A`` a saved ``ListToolsResult``: a mapping with ``tools`` *and* at least
    one envelope key. ``B`` a whole JSON-RPC response, which is what teeing a
    stdio session produces. ``C`` a bare ``{"tools": [...]}`` dump, the shape
    every dump tool writes. Where the envelope proves intent (A, B) the entries
    are accepted and their problems reported as findings; where there is no
    proof (C) every entry must look like a Tool, so that a Spectral ruleset, a
    ``package.json``, or an agent config listing ``"tools": ["a", "b"]`` cannot
    be mistaken for a contract.

    An ``.mcp.json`` *server config* (``{"mcpServers": {...}}``) has no ``tools``
    list at all and is refused: it declares how to launch a server, not what
    the server exposes.
    """
    if not isinstance(doc, dict):
        raise ManifestShapeError("an MCP manifest is a JSON object")

    envelope: dict[str, Any] = {}
    tools: Any = None

    if doc.get("jsonrpc") == "2.0" and isinstance(doc.get("result"), dict):
        envelope = doc["result"]
        tools = envelope.get("tools")
    elif "tools" in doc:
        envelope = doc
        tools = doc.get("tools")

    if not isinstance(tools, list):
        raise ManifestShapeError("no `tools` array")
    return tools, envelope


def looks_like_tools(tools: list[Any]) -> bool:
    """Strict sniff for a bare dump, where nothing else proves intent.

    Every entry must be a mapping with a non-empty string ``name`` and an
    ``inputSchema`` object whose ``type`` is ``"object"`` -- the two fields the
    specification makes mandatory.
    """
    if not tools:
        return False
    for entry in tools:
        if not isinstance(entry, dict):
            return False
        if not isinstance(entry.get("name"), str) or not entry["name"].strip():
            return False
        schema = entry.get("inputSchema")
        if not isinstance(schema, dict) or schema.get("type") != "object":
            return False
    return True


def _era(envelope: dict[str, Any], tools: list[Any]) -> tuple[str, str]:
    """Which protocol era this manifest came from, and why we think so.

    Three values, and ``"legacy"`` is reachable only from a recorded version
    string. A bare dump from a modern server is byte-identical to one from a
    legacy server, so the *absence* of an envelope proves nothing and must
    never be read as evidence of age.
    """
    declared = None
    meta = envelope.get("_meta")
    if isinstance(meta, dict):
        declared = meta.get(_PROTOCOL_VERSION_META)
    if not isinstance(declared, str):
        for entry in tools:
            if isinstance(entry, dict) and isinstance(entry.get("_meta"), dict):
                candidate = entry["_meta"].get(_PROTOCOL_VERSION_META)
                if isinstance(candidate, str):
                    declared = candidate
                    break

    if isinstance(declared, str) and declared:
        if declared >= _MODERN_FROM:
            return "modern", f"the document records protocol version {declared}"
        return "legacy", f"the document records protocol version {declared}"

    present = [key for key in _MODERN_MARKERS if key in envelope]
    if present:
        return "modern", f"the list-result envelope carries {', '.join(sorted(present))}"
    return "unknown", (
        "no protocol version was recorded and the document carries no list-result "
        "envelope; a bare tools dump looks the same from either era"
    )


def _annotations(entry: dict[str, Any]) -> dict[str, bool | None]:
    """The four hints as an explicit tri-state.

    ``None`` means *undeclared* and is never collapsed to the specification's
    documented default: "the server did not say" and "the server said false"
    are different claims, and only one of them is something the run observed.
    """
    raw = entry.get("annotations")
    source = raw if isinstance(raw, dict) else {}
    out: dict[str, bool | None] = {}
    for hint in ANNOTATION_HINTS:
        value = source.get(hint)
        out[hint] = value if isinstance(value, bool) else None
    return out


def _unmodelled(schema: Any, pointer: str, found: list[tuple[str, str]]) -> None:
    """Walk a raw schema for keywords the shared SchemaNode cannot represent."""
    if isinstance(schema, dict):
        for keyword in _UNMODELLED_KEYWORDS:
            if keyword in schema:
                found.append((keyword, pointer))
        for key, value in schema.items():
            _unmodelled(value, f"{pointer}/{key}", found)
    elif isinstance(schema, list):
        for index, value in enumerate(schema):
            _unmodelled(value, f"{pointer}/{index}", found)


def load_manifest(
    payload: Any, *, label: str = "mcp-manifest", source_file: str | None = None
) -> tuple[Service, list[Finding]]:
    """Normalize a parsed manifest payload into a :class:`Service`.

    Takes a payload rather than a path so the live drift runner can feed a
    `tools/list` response straight off the wire through the *same* normalizer
    the declared manifest went through. Two contracts compared by
    `diff_services` must have been built the same way, or the differences it
    reports include the ones the loader invented.
    """
    findings: list[Finding] = []
    tools, envelope = unwrap_manifest(payload)
    parser = OpenApiParser(source_file or label)
    location = SourceLocation(file=source_file or label, pointer="/tools")

    era, era_reason = _era(envelope, tools)
    truncated = bool(envelope.get("nextCursor"))

    if era == "unknown":
        findings.append(
            Finding(
                rule_id="MCP-PROTOCOL-ERA-UNOBSERVED",
                severity=Severity.INFO,
                message=f"protocol era not established: {era_reason}",
                location=location,
            )
        )
    if truncated:
        findings.append(
            Finding(
                rule_id="MCP-MANIFEST-TRUNCATED",
                severity=Severity.WARN,
                message=(
                    "this is one page of a paginated tools/list -- `nextCursor` is set, so "
                    "tools beyond this page are absent from the contract"
                ),
                location=location,
            )
        )
    if "resultType" in envelope and not all(k in envelope for k in ("ttlMs", "cacheScope")):
        findings.append(
            Finding(
                rule_id="MCP-LIST-RESULT-INCOMPLETE",
                severity=Severity.WARN,
                message=(
                    "the envelope carries `resultType` but not both `ttlMs` and `cacheScope`, "
                    "which are required on a modern list result -- this looks like a partial capture"
                ),
                location=location,
            )
        )

    operations: list[Operation] = []
    seen: set[str] = set()

    for index, entry in enumerate(tools):
        pointer = f"/tools/{index}"
        if not isinstance(entry, dict):
            findings.append(
                Finding(
                    rule_id="MCP-TOOL-INVALID",
                    severity=Severity.ERROR,
                    message=f"tool at {pointer} is not an object",
                    location=SourceLocation(file=source_file or label, pointer=pointer),
                )
            )
            continue

        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            findings.append(
                Finding(
                    rule_id="MCP-TOOL-NAME-MISSING",
                    severity=Severity.ERROR,
                    message=f"tool at {pointer} has no `name`; the specification requires one",
                    location=SourceLocation(file=source_file or label, pointer=pointer),
                )
            )
            continue
        if name in seen:
            findings.append(
                Finding(
                    rule_id="MCP-TOOL-DUPLICATE",
                    severity=Severity.ERROR,
                    message=(
                        f"tool {name!r} is declared more than once; `tools/call` dispatches on "
                        "name, so which one answers is undefined"
                    ),
                    location=SourceLocation(file=source_file or label, pointer=pointer),
                )
            )
            continue
        seen.add(name)

        input_schema = entry.get("inputSchema")
        request_body: RequestBody | None = None
        if not isinstance(input_schema, dict):
            findings.append(
                Finding(
                    rule_id="MCP-INPUT-SCHEMA-MISSING",
                    severity=Severity.ERROR,
                    message=(
                        f"tool {name!r} has no `inputSchema` object; the specification makes it "
                        "mandatory and a client cannot construct a call without it"
                    ),
                    location=SourceLocation(file=source_file or label, pointer=pointer),
                )
            )
        else:
            if input_schema.get("type") != "object":
                findings.append(
                    Finding(
                        rule_id="MCP-INPUT-SCHEMA-NOT-OBJECT",
                        severity=Severity.ERROR,
                        message=(
                            f"tool {name!r} declares inputSchema.type="
                            f"{input_schema.get('type')!r}; tool arguments are an object"
                        ),
                        location=SourceLocation(
                            file=source_file or label, pointer=f"{pointer}/inputSchema"
                        ),
                    )
                )
            # `root` is the tool's own inputSchema: it is a JSON Schema resource
            # in its own right, so `#/$defs/Unit` resolves inside it, not
            # against the manifest document.
            schema = parser.to_schema(input_schema, input_schema, f"{pointer}/inputSchema")
            if schema is not None:
                request_body = RequestBody(
                    required=True,  # derived: the spec makes inputSchema mandatory
                    content={MCP_MEDIA_TYPE: schema},
                )

        responses: list[Response] = []
        output_schema = entry.get("outputSchema")
        if isinstance(output_schema, dict):
            out_schema = parser.to_schema(output_schema, output_schema, f"{pointer}/outputSchema")
            if out_schema is not None:
                responses.append(
                    Response(
                        status=MCP_RESULT_STATUS,
                        content={MCP_MEDIA_TYPE: out_schema},
                        description="structuredContent declared by outputSchema",
                    )
                )
        # No outputSchema means the manifest declares nothing about the result
        # shape. An empty Response would be a contract we made up.

        unmodelled: list[tuple[str, str]] = []
        _unmodelled(input_schema, f"{pointer}/inputSchema", unmodelled)
        _unmodelled(output_schema, f"{pointer}/outputSchema", unmodelled)
        for keyword, where in unmodelled:
            findings.append(
                Finding(
                    rule_id="MCP-SCHEMA-KEYWORD-UNMODELED",
                    severity=Severity.WARN,
                    message=(
                        f"`{keyword}` at {where} is not represented in the normalized model, "
                        "so the diff will not see changes to it"
                    ),
                    location=SourceLocation(file=source_file or label, pointer=where),
                )
            )

        # `x-mcp-header` (new in 2026-07-28) marks an input property whose value
        # travels as an HTTP header. Recorded as a list of pointers for the live
        # runner to build a real call with; deliberately not turned into a
        # Parameter(location=HEADER), which would double-report every change
        # since the property also stays in the input schema.
        properties = input_schema.get("properties") if isinstance(input_schema, dict) else None
        header_properties = sorted(
            f"{pointer}/inputSchema/properties/{prop}"
            for prop, value in (properties or {}).items()
            if isinstance(value, dict) and "x-mcp-header" in value
        )

        operations.append(
            Operation(
                kind=OperationKind.MCP_TOOL,
                operation_id=name,
                rpc_name=name,
                service_name=label,
                summary=entry.get("title") if isinstance(entry.get("title"), str) else None,
                description=(
                    entry.get("description") if isinstance(entry.get("description"), str) else None
                ),
                request_body=request_body,
                responses=responses,
                bindings={
                    "mcp": {
                        "annotations": _annotations(entry),
                        "icons": entry.get("icons"),
                        "meta": entry.get("_meta"),
                        "header_properties": header_properties,
                        "declares_output_schema": isinstance(output_schema, dict),
                    }
                },
                source_location=SourceLocation(file=source_file or label, pointer=pointer),
            )
        )

    findings.extend(parser.findings)

    service = Service(
        title=label,
        # A manifest carries no version. "unknown" is the honest value, it
        # keeps DiffEngine's version-change branch from firing on every diff,
        # and SemverPolicy already degrades to SEMVER-UNPARSEABLE rather than
        # crashing on it.
        version="unknown",
        protocol=Protocol.MCP,
        operations=operations,
        source_file=source_file,
        source_location=location,
        bindings={
            "mcp": {
                "era": era,
                "era_reason": era_reason,
                "truncated": truncated,
                "tool_count": len(operations),
            }
        },
    )
    return service, findings


def load_mcp(source: str) -> tuple[Service, list[Finding]]:
    """Load a manifest from a path or URL."""
    resolved, raw = read_source(source)
    label = Path(resolved).stem or "mcp-manifest"
    if label.endswith(".mcp"):
        label = label[: -len(".mcp")]
    return load_manifest(parse_document(raw), label=label, source_file=resolved)


class McpSpecPlugin(SpecPlugin):
    """Spec plugin for saved MCP `tools/list` manifests."""

    PLUGIN_API_VERSION = "1"

    #: A filename that states intent, mirroring GrpcSpecPlugin's descriptor
    #: suffixes.
    MANIFEST_SUFFIXES = (".mcp.json",)

    def protocol(self) -> Protocol:
        return Protocol.MCP

    def detect(self, source: str, raw: bytes | None = None) -> bool:
        named = source.lower().endswith(self.MANIFEST_SUFFIXES)
        if raw is None:
            return named
        try:
            doc = parse_document(raw)
        except Exception:
            return False
        try:
            tools, envelope = unwrap_manifest(doc)
        except ManifestShapeError:
            return False
        # An envelope, a JSON-RPC frame or the filename all state intent, so
        # the entries are taken on trust and their problems become findings.
        # A bare `{"tools": [...]}` states nothing, so it has to look the part.
        if named or any(key in envelope for key in (*_VOLATILE_KEYS, "resultType")):
            return True
        if isinstance(doc.get("jsonrpc"), str):
            return True
        return looks_like_tools(tools)

    def load(self, source: str) -> tuple[Service, list[Finding]]:
        return load_mcp(source)


def dumps(service_payload: dict[str, Any]) -> str:
    """Stable JSON for a manifest, used by fixtures and tests."""
    return json.dumps(service_payload, indent=2, sort_keys=True)
