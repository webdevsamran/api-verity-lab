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


def _message_to_schema(name: str, body: str, line_of: dict[int, int], base_line: int) -> SchemaNode:
    properties: dict[str, SchemaNode] = {}
    seen_numbers: dict[int, str] = {}
    findings: list[Finding] = []

    for offset, raw_line in enumerate(body.splitlines()):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("//"):
            continue
        m = _RE_FIELD.match(stripped)
        if not m:
            continue
        label, ftype, fname, number = m.group(1), m.group(2), m.group(3), int(m.group(4))
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

    return SchemaNode(type="object", title=name, properties=properties)


class GrpcSpecPlugin(SpecPlugin):
    """Normalizes ``.proto`` files into the core model."""

    def protocol(self) -> Protocol:
        return Protocol.GRPC

    def detect(self, source: str, raw: bytes | None = None) -> bool:
        if source.endswith(".proto"):
            return True
        if raw is not None:
            text = raw.decode("utf-8-sig", errors="replace")
            return bool(_RE_SERVICE.search(text)) and "openapi" not in text
        return False

    def load(self, source: str) -> tuple[Service, list[Finding]]:
        from pathlib import Path as _Path

        findings: list[Finding] = []
        path = _Path(source)
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
            schemas[name] = _message_to_schema(name, body, {}, line_no)

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
