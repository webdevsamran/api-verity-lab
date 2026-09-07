"""Read a compiled `FileDescriptorSet` (#17).

`protoc --descriptor_set_out` is what a real gRPC project already produces:
imports resolved, options applied, `optional` and `oneof` disambiguated by the
compiler rather than by a regex. Reading it is strictly better input than
re-parsing `.proto` text, and for anything with imports it is the only input
that can be correct.

This decodes the protobuf wire format directly rather than depending on the
`protobuf` runtime. Two reasons, in order: a contract-checking CLI should not
make its users install a code generator's runtime to read a file, and the
subset of `descriptor.proto` that matters here is about eighty lines of table.
The cost is that the tables below have to match `descriptor.proto`; they are
quoted from it in the comments so a reader can check.

Only the fields the diff actually uses are decoded. Everything else is skipped
by length, which is what makes the wire format safe to read partially.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "DescriptorSet",
    "FieldDescriptor",
    "MessageDescriptor",
    "MethodDescriptor",
    "ServiceDescriptor",
    "parse_descriptor_set",
]

# --- wire format ------------------------------------------------------------

_VARINT, _FIXED64, _LENGTH, _START_GROUP, _END_GROUP, _FIXED32 = 0, 1, 2, 3, 4, 5


class DescriptorError(ValueError):
    """The bytes are not a readable FileDescriptorSet.

    Distinct from a generic ValueError so the CLI can tell "this file is not a
    descriptor set" from "this descriptor set describes something odd".
    """


def _read_varint(data: bytes, pos: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while True:
        if pos >= len(data):
            raise DescriptorError("truncated varint")
        if shift > 63:
            raise DescriptorError("varint longer than 64 bits")
        byte = data[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, pos
        shift += 7


def _fields(data: bytes) -> list[tuple[int, int, Any]]:
    """Decode one message into (field_number, wire_type, value) triples.

    Repeated fields appear more than once, in order, which is how the wire
    format represents them and why this returns a list rather than a dict.
    """
    out: list[tuple[int, int, Any]] = []
    pos = 0
    value: Any
    while pos < len(data):
        tag, pos = _read_varint(data, pos)
        number, wire = tag >> 3, tag & 0x07
        if wire == _VARINT:
            value, pos = _read_varint(data, pos)
        elif wire == _FIXED64:
            value, pos = data[pos : pos + 8], pos + 8
        elif wire == _LENGTH:
            length, pos = _read_varint(data, pos)
            if pos + length > len(data):
                raise DescriptorError("length-delimited field runs past the end")
            value, pos = data[pos : pos + length], pos + length
        elif wire == _FIXED32:
            value, pos = data[pos : pos + 4], pos + 4
        elif wire in (_START_GROUP, _END_GROUP):
            # Groups are deprecated and descriptor.proto does not use them.
            raise DescriptorError("group wire type is not supported")
        else:
            raise DescriptorError(f"unknown wire type {wire}")
        out.append((number, wire, value))
    return out


def _sub(entries: list[tuple[int, int, Any]], number: int) -> list[bytes]:
    return [bytes(v) for n, w, v in entries if n == number and w == _LENGTH]


def _text(entries: list[tuple[int, int, Any]], number: int, default: str = "") -> str:
    for n, w, v in entries:
        if n == number and w == _LENGTH:
            return bytes(v).decode("utf-8", errors="replace")
    return default


def _int(entries: list[tuple[int, int, Any]], number: int, default: int = 0) -> int:
    for n, w, v in entries:
        if n == number and w == _VARINT:
            return int(v)
    return default


def _bool(entries: list[tuple[int, int, Any]], number: int) -> bool:
    return _int(entries, number, 0) != 0


def _has(entries: list[tuple[int, int, Any]], number: int) -> bool:
    return any(n == number for n, _, _ in entries)


# --- descriptor.proto, the parts that matter --------------------------------

#: FieldDescriptorProto.Type, from descriptor.proto. Mapped to the core
#: model's JSON-schema-ish vocabulary; `format` keeps the protobuf width,
#: because int32 -> int64 is wire-compatible and int32 -> string is not.
_TYPES: dict[int, tuple[str, str | None]] = {
    1: ("number", "double"),
    2: ("number", "float"),
    3: ("integer", "int64"),
    4: ("integer", "uint64"),
    5: ("integer", "int32"),
    6: ("integer", "fixed64"),
    7: ("integer", "fixed32"),
    8: ("boolean", None),
    9: ("string", None),
    10: ("object", "group"),
    11: ("object", None),
    12: ("string", "bytes"),
    13: ("integer", "uint32"),
    14: ("string", "enum"),
    15: ("integer", "sfixed32"),
    16: ("integer", "sfixed64"),
    17: ("integer", "sint32"),
    18: ("integer", "sint64"),
}

#: FieldDescriptorProto.Label
_LABEL_OPTIONAL, _LABEL_REQUIRED, _LABEL_REPEATED = 1, 2, 3


@dataclass
class FieldDescriptor:
    name: str
    number: int
    type: int
    type_name: str = ""
    label: int = _LABEL_OPTIONAL
    oneof_index: int | None = None
    proto3_optional: bool = False

    @property
    def repeated(self) -> bool:
        return self.label == _LABEL_REPEATED

    @property
    def json_type(self) -> tuple[str, str | None]:
        return _TYPES.get(self.type, ("string", None))


@dataclass
class MessageDescriptor:
    name: str
    fields: list[FieldDescriptor] = field(default_factory=list)
    oneof_names: list[str] = field(default_factory=list)
    reserved_numbers: list[int] = field(default_factory=list)
    reserved_names: list[str] = field(default_factory=list)
    nested: list[MessageDescriptor] = field(default_factory=list)

    def oneofs(self) -> dict[str, list[str]]:
        """oneof name -> member field names.

        A field carrying `proto3_optional` is *synthetically* placed in a
        one-field oneof by protoc; it is explicit presence, not a real union,
        and reporting it as a oneof would invent a constraint the author never
        wrote.
        """
        out: dict[str, list[str]] = {}
        for f in self.fields:
            if f.oneof_index is None or f.proto3_optional:
                continue
            if 0 <= f.oneof_index < len(self.oneof_names):
                out.setdefault(self.oneof_names[f.oneof_index], []).append(f.name)
        return out

    def explicit_presence(self) -> list[str]:
        return sorted(f.name for f in self.fields if f.proto3_optional or f.oneof_index is not None)


@dataclass
class MethodDescriptor:
    name: str
    input_type: str = ""
    output_type: str = ""
    client_streaming: bool = False
    server_streaming: bool = False


@dataclass
class ServiceDescriptor:
    name: str
    methods: list[MethodDescriptor] = field(default_factory=list)


@dataclass
class EnumDescriptor:
    name: str
    values: dict[str, int] = field(default_factory=dict)
    reserved_numbers: list[int] = field(default_factory=list)
    reserved_names: list[str] = field(default_factory=list)


@dataclass
class FileDescriptor:
    name: str = ""
    package: str = ""
    syntax: str = "proto2"
    messages: list[MessageDescriptor] = field(default_factory=list)
    enums: list[EnumDescriptor] = field(default_factory=list)
    services: list[ServiceDescriptor] = field(default_factory=list)


@dataclass
class DescriptorSet:
    files: list[FileDescriptor] = field(default_factory=list)

    def all_messages(self) -> dict[str, MessageDescriptor]:
        """Fully-qualified name -> message, including nested ones."""
        out: dict[str, MessageDescriptor] = {}

        def walk(prefix: str, message: MessageDescriptor) -> None:
            qualified = f"{prefix}.{message.name}" if prefix else message.name
            out[qualified] = message
            for nested in message.nested:
                walk(qualified, nested)

        for f in self.files:
            for message in f.messages:
                walk(f.package, message)
        return out


# --- decoding ---------------------------------------------------------------


def _field(data: bytes) -> FieldDescriptor:
    e = _fields(data)
    return FieldDescriptor(
        name=_text(e, 1),
        number=_int(e, 3),
        label=_int(e, 4, _LABEL_OPTIONAL),
        type=_int(e, 5),
        type_name=_text(e, 6),
        # oneof_index is a real index, and 0 is valid, so presence has to be
        # tested rather than truthiness.
        oneof_index=_int(e, 9) if _has(e, 9) else None,
        proto3_optional=_bool(e, 17),
    )


def _ranges(blobs: list[bytes]) -> list[int]:
    """Flatten ReservedRange entries into the numbers they cover.

    `end` is exclusive in descriptor.proto, which is the opposite of how
    `reserved 2 to 4;` reads in a .proto file. Getting it wrong by one is how
    a checker misses a message reusing the last reserved number.
    """
    numbers: list[int] = []
    for blob in blobs:
        e = _fields(blob)
        start = _int(e, 1)
        end = _int(e, 2, start + 1)
        if end <= start:
            continue
        # A range up to the protobuf maximum would be 500 million entries; the
        # cap keeps a malformed or deliberately huge range from exhausting
        # memory, and no real message reserves more than a handful.
        numbers.extend(range(start, min(end, start + 10_000)))
    return numbers


def _message(data: bytes) -> MessageDescriptor:
    e = _fields(data)
    return MessageDescriptor(
        name=_text(e, 1),
        fields=[_field(b) for b in _sub(e, 2)],
        nested=[_message(b) for b in _sub(e, 3)],
        oneof_names=[_text(_fields(b), 1) for b in _sub(e, 8)],
        reserved_numbers=_ranges(_sub(e, 9)),
        reserved_names=[bytes(b).decode("utf-8", "replace") for b in _sub(e, 10)],
    )


def _enum(data: bytes) -> EnumDescriptor:
    e = _fields(data)
    values: dict[str, int] = {}
    for blob in _sub(e, 2):
        ve = _fields(blob)
        values[_text(ve, 1)] = _int(ve, 2)
    return EnumDescriptor(
        name=_text(e, 1),
        values=values,
        reserved_numbers=_ranges(_sub(e, 4)),
        reserved_names=[bytes(b).decode("utf-8", "replace") for b in _sub(e, 5)],
    )


def _service(data: bytes) -> ServiceDescriptor:
    e = _fields(data)
    methods = []
    for blob in _sub(e, 2):
        me = _fields(blob)
        methods.append(
            MethodDescriptor(
                name=_text(me, 1),
                input_type=_text(me, 2),
                output_type=_text(me, 3),
                client_streaming=_bool(me, 5),
                server_streaming=_bool(me, 6),
            )
        )
    return ServiceDescriptor(name=_text(e, 1), methods=methods)


def _file(data: bytes) -> FileDescriptor:
    e = _fields(data)
    return FileDescriptor(
        name=_text(e, 1),
        package=_text(e, 2),
        messages=[_message(b) for b in _sub(e, 4)],
        enums=[_enum(b) for b in _sub(e, 5)],
        services=[_service(b) for b in _sub(e, 6)],
        syntax=_text(e, 12, "proto2"),
    )


def parse_descriptor_set(data: bytes) -> DescriptorSet:
    """Decode a `FileDescriptorSet` produced by `protoc --descriptor_set_out`."""
    if not data:
        raise DescriptorError("empty descriptor set")
    try:
        entries = _fields(data)
    except DescriptorError:
        raise
    except Exception as exc:  # pragma: no cover - defensive
        raise DescriptorError(f"could not decode descriptor set: {exc}") from exc

    files = [_file(blob) for blob in _sub(entries, 1)]
    if not files:
        raise DescriptorError(
            "no FileDescriptorProto entries; is this a descriptor set produced by "
            "'protoc --descriptor_set_out'?"
        )
    return DescriptorSet(files=files)


# --- normalization ----------------------------------------------------------


def _schema_for(
    message: MessageDescriptor, messages: dict[str, MessageDescriptor], depth: int = 0
) -> Any:
    """Turn a message descriptor into the core model's SchemaNode.

    Nested message fields expand one level per recursion and stop at a depth
    cap: protobuf allows a message to contain itself, and a schema tree cannot.
    """
    from apiverity.core.model import SchemaNode

    properties: dict[str, Any] = {}
    field_numbers: dict[int, str] = {}
    for f in message.fields:
        json_type, fmt = f.json_type
        if f.type == 11 and depth < 4:  # TYPE_MESSAGE
            nested = messages.get(f.type_name.lstrip("."))
            node = (
                _schema_for(nested, messages, depth + 1)
                if nested is not None
                else SchemaNode(type="object", title=f.type_name.rsplit(".", 1)[-1])
            )
        else:
            node = SchemaNode(type=json_type, format=fmt)
            if f.type_name:
                node.title = f.type_name.rsplit(".", 1)[-1]
        if f.repeated:
            node = SchemaNode(type="array", items=node)
        properties[f.name] = node
        field_numbers[f.number] = f.name

    return SchemaNode(
        type="object",
        title=message.name,
        properties=properties,
        field_numbers=field_numbers,
        reserved_numbers=sorted(message.reserved_numbers),
        reserved_names=sorted(message.reserved_names),
        explicit_presence=message.explicit_presence(),
        oneofs={k: sorted(v) for k, v in message.oneofs().items()},
    )


def service_from_descriptor_set(data: bytes, label: str) -> tuple[Any, list[Any]]:
    """Normalize a FileDescriptorSet into a `Service` plus load-time findings."""
    from apiverity.core.model import (
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

    descriptor_set = parse_descriptor_set(data)
    messages = descriptor_set.all_messages()
    findings: list[Any] = []

    primary = descriptor_set.files[-1]
    service = Service(
        title=primary.package or label.rsplit(".", 1)[0],
        version="0",
        protocol=Protocol.GRPC,
        source_file=label,
    )

    for file in descriptor_set.files:
        for message in file.messages:
            qualified = f"{file.package}.{message.name}" if file.package else message.name
            duplicates = [
                f.number
                for f in message.fields
                if sum(1 for g in message.fields if g.number == f.number) > 1
            ]
            for number in sorted(set(duplicates)):
                names = [f.name for f in message.fields if f.number == number]
                findings.append(
                    Finding(
                        rule_id="PROTO-FIELD-NUMBER-REUSE",
                        severity=Severity.ERROR,
                        message=(
                            f"message '{qualified}' reuses field number {number} "
                            f"({', '.join(names)}) -- this corrupts wire data"
                        ),
                        location=SourceLocation(file=label),
                    )
                )
            for f in message.fields:
                if f.number in message.reserved_numbers:
                    findings.append(
                        Finding(
                            rule_id="PROTO-RESERVED-NUMBER-USED",
                            severity=Severity.ERROR,
                            message=(
                                f"message '{qualified}' field '{f.name}' uses reserved "
                                f"number {f.number}"
                            ),
                            location=SourceLocation(file=label),
                        )
                    )
                if f.name in message.reserved_names:
                    findings.append(
                        Finding(
                            rule_id="PROTO-RESERVED-NAME-USED",
                            severity=Severity.ERROR,
                            message=(
                                f"message '{qualified}' declares field '{f.name}', "
                                "which is reserved"
                            ),
                            location=SourceLocation(file=label),
                        )
                    )

        for descriptor in file.services:
            seen: set[str] = set()
            for method in descriptor.methods:
                if method.name in seen:
                    findings.append(
                        Finding(
                            rule_id="PROTO-RPC-DUPLICATE",
                            severity=Severity.ERROR,
                            message=(
                                f"service '{descriptor.name}' declares duplicate RPC "
                                f"'{method.name}'"
                            ),
                            location=SourceLocation(file=label),
                        )
                    )
                seen.add(method.name)

                op = Operation(
                    kind=OperationKind.GRPC_RPC,
                    rpc_name=method.name,
                    service_name=descriptor.name,
                    summary=f"{descriptor.name}.{method.name}",
                    client_streaming=method.client_streaming,
                    server_streaming=method.server_streaming,
                    source_location=SourceLocation(file=label),
                )
                request = messages.get(method.input_type.lstrip("."))
                if request is not None:
                    op.request_body = RequestBody(
                        required=True,
                        content={"application/x-protobuf": _schema_for(request, messages)},
                    )
                response = messages.get(method.output_type.lstrip("."))
                if response is not None:
                    op.responses.append(
                        Response(
                            status="OK",
                            content={"application/x-protobuf": _schema_for(response, messages)},
                        )
                    )
                service.operations.append(op)

    service.operations.sort(key=lambda o: o.key)
    return service, findings
