"""gRPC / protobuf spec plugin (foundation).

Loads ``.proto`` files with a lightweight built-in parser (no protoc
dependency) and normalizes services/RPCs into the core model. Message
shapes become request/response schemas so the shared diff engine can
detect RPC removal, field changes and enum changes.

Load-time checks:
- field-number reuse inside a message (wire corruption risk)
- duplicate RPC names on a service

Note: this is a structural foundation. Full protobuf wire-compatibility
analysis (wire-type mapping for every scalar) is tracked in ROADMAP.
"""

from __future__ import annotations

import re
from pathlib import Path

from apiverity.core.model import (
    Finding,
    Operation,
    OperationKind,
    Protocol,
    RequestBody,
    Response,
    SchemaNode,
    Service,
    Severity,
    SourceLocation,
)
from apiverity.specs import SpecPlugin

_PROTO_SCALARS = {
    "double": ("number", None),
    "float": ("number", None),
    "int32": ("integer", "int32"),
    "int64": ("integer", "int64"),
    "uint32": ("integer", None),
    "uint64": ("integer", None),
    "sint32": ("integer", None),
    "sint64": ("integer", None),
    "fixed32": ("integer", None),
    "fixed64": ("integer", None),
    "sfixed32": ("integer", None),
    "sfixed64": ("integer", None),
    "bool": ("boolean", None),
    "string": ("string", None),
    "bytes": ("string", None),
}

NL = chr(10)

_RE_MESSAGE = re.compile(r"^message\s+(\w+)\s*\{", re.MULTILINE)
_RE_ENUM = re.compile(r"^enum\s+(\w+)\s*\{", re.MULTILINE)
_RE_SERVICE = re.compile(r"^service\s+(\w+)\s*\{", re.MULTILINE)
_RE_RPC = re.compile(
    r"rpc\s+(\w+)\s*\(\s*(stream\s+)?([\w.]+)\s*\)\s*returns\s*\(\s*(stream\s+)?([\w.]+)\s*\)"
)
_RE_FIELD = re.compile(
    r"^(?:(repeated|optional|required|map\s*<[^>]+>)\s+)?([\w.]+)\s+(\w+)\s*=\s*(\d+)"
)
_RE_ENUM_VALUE = re.compile(r"(\w+)\s*=\s*(-?\d+)")
#: `reserved 2, 15, 9 to 11;` and `reserved "foo", "bar";`. Both forms exist
#: because protobuf retires a number and a name separately -- reusing either
#: one breaks a different thing.
_RE_RESERVED = re.compile(r"^\s*reserved\s+([^;]+);")
_RE_RESERVED_RANGE = re.compile(r"(\d+)\s+to\s+(\d+|max)")
_RE_ONEOF = re.compile(r"\boneof\s+(\w+)\s*\{")

#: protobuf's largest field number.
_MAX_FIELD_NUMBER = 536_870_911


def _extract_block(text: str, start_match: re.Match[str]) -> str:
    """Extract the balanced brace block starting at a match."""
    start = start_match.end() - 1  # position of '{'
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1 : i]
    return ""


def _parse_reserved(body: str) -> tuple[list[int], list[str]]:
    """Numbers and names a message has retired.

    Reserving is how protobuf stops a later author reusing a field number
    whose old meaning is still on the wire in stored data. A checker that does
    not read them cannot tell a legal new field from one that will be decoded
    as something else entirely.
    """
    numbers: set[int] = set()
    names: list[str] = []
    for raw_line in body.splitlines():
        match = _RE_RESERVED.match(raw_line)
        if not match:
            continue
        clause = match.group(1)
        for quoted in re.findall(r'"([^"]+)"|\x27([^\x27]+)\x27', clause):
            names.append(quoted[0] or quoted[1])
        remaining = re.sub(r'"[^"]*"|\x27[^\x27]*\x27', "", clause)
        for start, end in _RE_RESERVED_RANGE.findall(remaining):
            high = _MAX_FIELD_NUMBER if end == "max" else int(end)
            low = int(start)
            if high >= low:
                # Capped for the same reason the descriptor reader caps: a
                # `to max` range covers half a billion numbers, and only
                # membership is ever asked.
                numbers.update(range(low, min(high, low + 10_000) + 1))
        remaining = _RE_RESERVED_RANGE.sub("", remaining)
        for token in re.findall(r"\b\d+\b", remaining):
            numbers.add(int(token))
    return sorted(numbers), names


def _message_to_schema(
    name: str, body: str, line_of: dict[int, int], base_line: int
) -> tuple[SchemaNode, list[Finding]]:
    """Normalize a message body, and report what is wrong with it.

    Returns findings rather than building them and dropping them, which is
    what this did: PROTO-FIELD-NUMBER-REUSE was constructed on every duplicate
    and then discarded when the function returned only the schema, so the
    documented load-time check never reported anything.
    """
    properties: dict[str, SchemaNode] = {}
    seen_numbers: dict[int, str] = {}
    findings: list[Finding] = []
    field_numbers: dict[int, str] = {}
    explicit_presence: list[str] = []
    oneofs: dict[str, list[str]] = {}
    reserved_numbers, reserved_names = _parse_reserved(body)

    current_oneof: str | None = None
    oneof_depth = 0

    for offset, raw_line in enumerate(body.splitlines()):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("//"):
            continue

        oneof_match = _RE_ONEOF.search(stripped)
        if oneof_match:
            current_oneof = oneof_match.group(1)
            oneof_depth = 1
            oneofs.setdefault(current_oneof, [])
            continue
        if current_oneof is not None:
            oneof_depth += stripped.count("{") - stripped.count("}")
            if oneof_depth <= 0:
                current_oneof = None
                continue

        m = _RE_FIELD.match(stripped)
        if not m:
            continue
        label, ftype, fname, number = m.group(1), m.group(2), m.group(3), int(m.group(4))

        if number in reserved_numbers:
            findings.append(
                Finding(
                    rule_id="PROTO-RESERVED-NUMBER-USED",
                    severity=Severity.ERROR,
                    message=(
                        f"message '{name}' field '{fname}' uses reserved number {number}; "
                        "data written by older clients will decode into this field"
                    ),
                    location=SourceLocation(file="", line=base_line + offset),
                )
            )
        if fname in reserved_names:
            findings.append(
                Finding(
                    rule_id="PROTO-RESERVED-NAME-USED",
                    severity=Severity.ERROR,
                    message=(f"message '{name}' declares field '{fname}', which is reserved"),
                    location=SourceLocation(file="", line=base_line + offset),
                )
            )
        field_numbers[number] = fname
        if current_oneof is not None:
            oneofs[current_oneof].append(fname)
            explicit_presence.append(fname)
        elif label == "optional":
            explicit_presence.append(fname)
        if number in seen_numbers:
            findings.append(
                Finding(
                    rule_id="PROTO-FIELD-NUMBER-REUSE",
                    severity=Severity.ERROR,
                    message=f"message '{name}' reuses field number {number} "
                    f"(used by both '{seen_numbers[number]}' and '{fname}') — "
                    "this corrupts wire data",
                    location=SourceLocation(file="", line=base_line + offset),
                )
            )
        else:
            seen_numbers[number] = fname
        if ftype in _PROTO_SCALARS:
            t, fmt = _PROTO_SCALARS[ftype]
            node = SchemaNode(type=t, format=fmt)
        else:
            node = SchemaNode(type="object", title=ftype.split(".")[-1])
        if label == "map":
            node = SchemaNode(type="object")
        elif label == "repeated":
            node = SchemaNode(type="array", items=node)
        properties[fname] = node

    schema = SchemaNode(
        type="object",
        title=name,
        properties=properties,
        field_numbers=field_numbers,
        reserved_numbers=reserved_numbers,
        reserved_names=reserved_names,
        explicit_presence=sorted(set(explicit_presence)),
        oneofs={k: sorted(v) for k, v in oneofs.items()},
    )
    return schema, findings


class GrpcSpecPlugin(SpecPlugin):
    """Normalizes ``.proto`` files into the core model."""

    def protocol(self) -> Protocol:
        return Protocol.GRPC

    #: Extensions `protoc --descriptor_set_out` is conventionally given.
    DESCRIPTOR_SUFFIXES = (".desc", ".pb", ".protoset", ".descriptor")

    def detect(self, source: str, raw: bytes | None = None) -> bool:
        if source.endswith(".proto") or source.endswith(self.DESCRIPTOR_SUFFIXES):
            return True
        if raw is not None:
            text = raw.decode("utf-8-sig", errors="replace")
            return bool(_RE_SERVICE.search(text)) and "openapi" not in text
        return False

    @staticmethod
    def _load_descriptor_set(path: Path) -> tuple[Service, list[Finding]]:
        return _load_descriptor_set_impl(path)

    def load(self, source: str) -> tuple[Service, list[Finding]]:
        from pathlib import Path as _Path

        path = _Path(source)
        if source.endswith(self.DESCRIPTOR_SUFFIXES):
            return self._load_descriptor_set(path)

        findings: list[Finding] = []
        text = path.read_text(encoding="utf-8-sig")
        label = path.name

        # strip comments to simplify block extraction
        clean = NL.join(line.split("//")[0] for line in text.splitlines())

        service = Service(
            title=label.rsplit(".", 1)[0],
            version="0",
            protocol=Protocol.GRPC,
            source_file=label,
        )

        # messages → reusable schema registry
        schemas: dict[str, SchemaNode] = {}
        for mm in _RE_MESSAGE.finditer(clean):
            name = mm.group(1)
            body = _extract_block(clean, mm)
            line_no = text[: mm.start()].count(NL) + 1
            schemas[name], message_findings = _message_to_schema(name, body, {}, line_no)
            for finding in message_findings:
                if finding.location is not None:
                    finding.location = SourceLocation(file=label, line=finding.location.line)
                findings.append(finding)

        # services → operations
        for sm in _RE_SERVICE.finditer(clean):
            svc_name = sm.group(1)
            body = _extract_block(clean, sm)
            svc_base_line = text[: sm.start()].count(NL) + 1
            seen_rpcs: set[str] = set()
            for offset, raw_line in enumerate(body.splitlines()):
                rm = _RE_RPC.search(raw_line)
                if not rm:
                    continue
                rpc_name, req_type, resp_type = rm.group(1), rm.group(3), rm.group(5)
                # Groups 2 and 4 are the `stream` markers. They were captured
                # and thrown away, so a unary RPC becoming bidirectional --
                # which no generated client can call -- produced no change at
                # all in the diff.
                client_streaming = bool(rm.group(2))
                server_streaming = bool(rm.group(4))
                if rpc_name in seen_rpcs:
                    findings.append(
                        Finding(
                            rule_id="PROTO-RPC-DUPLICATE",
                            severity=Severity.ERROR,
                            message=f"service '{svc_name}' declares duplicate RPC '{rpc_name}'",
                            location=SourceLocation(file=label, line=svc_base_line + offset),
                        )
                    )
                seen_rpcs.add(rpc_name)
                key = f"{svc_name}.{rpc_name}"
                req_schema = schemas.get(req_type.split(".")[-1])
                resp_schema = schemas.get(resp_type.split(".")[-1])
                op = Operation(
                    kind=OperationKind.GRPC_RPC,
                    rpc_name=rpc_name,
                    service_name=svc_name,
                    summary=key,
                    client_streaming=client_streaming,
                    server_streaming=server_streaming,
                    source_location=SourceLocation(file=label, line=svc_base_line + offset),
                )
                if req_schema is not None:
                    op.request_body = RequestBody(
                        required=True,
                        content={"application/x-protobuf": req_schema},
                    )
                if resp_schema is not None:
                    op.responses.append(
                        Response(status="OK", content={"application/x-protobuf": resp_schema})
                    )
                service.operations.append(op)

        if not service.operations and not schemas:
            findings.append(
                Finding(
                    rule_id="PROTO-PARSE-EMPTY",
                    severity=Severity.ERROR,
                    message=f"no services or messages found in '{label}'",
                    location=SourceLocation(file=label),
                )
            )

        service.operations.sort(key=lambda o: o.key)
        return service, findings


def _load_descriptor_set_impl(path: Path) -> tuple[Service, list[Finding]]:
    """Load a compiled FileDescriptorSet.

    Preferred over re-parsing `.proto` text whenever it is available: protoc
    has already resolved imports, applied options, and decided which fields
    have explicit presence. For a proto with imports it is the only input that
    can be correct, because the text parser here reads one file.
    """
    from apiverity.specs.grpc.descriptor import (
        DescriptorError,
        service_from_descriptor_set,
    )

    data = path.read_bytes()
    try:
        return service_from_descriptor_set(data, path.name)
    except DescriptorError as exc:
        raise ValueError(
            f"{path.name} is not a readable FileDescriptorSet ({exc}). "
            "Produce one with: protoc --descriptor_set_out=api.desc --include_imports api.proto"
        ) from exc
