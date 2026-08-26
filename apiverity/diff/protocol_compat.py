"""Protocol-specific compatibility analysis beyond the shared HTTP rules.

Each analyzer speaks the native semantics of its protocol:

- **GraphQL** distinguishes strictly-breaking changes from *dangerous*
  additions that exhaustive clients may notice (GraphQL-spec aligned).
- **gRPC/protobuf** reasons about wire compatibility: RPC removal, request/
  response type swaps, scalar wire-type changes and field removals.

Findings use protocol-prefixed rule IDs so they never collide with HTTP
compatibility findings.
"""

from __future__ import annotations

from apiverity.core.model import (
    Finding,
    Operation,
    Protocol,
    SchemaNode,
    Service,
    Severity,
)

_GRAPHQL_MEDIA = "application/graphql"
_PROTO_MEDIA = "application/x-protobuf"


def analyze_protocol_compat(old: Service, new: Service) -> list[Finding]:
    """Dispatch to the protocol-specific analyzer (empty for OpenAPI/others)."""
    if old.protocol == Protocol.GRAPHQL and new.protocol == Protocol.GRAPHQL:
        return _analyze_graphql(old, new)
    if old.protocol == Protocol.GRPC and new.protocol == Protocol.GRPC:
        return _analyze_grpc(old, new)
    return []


# --- GraphQL --------------------------------------------------------------------


def _return_schema(op: Operation) -> SchemaNode | None:
    for resp in op.responses:
        if _GRAPHQL_MEDIA in resp.content:
            node = resp.content[_GRAPHQL_MEDIA]
            return node if isinstance(node, SchemaNode) else None
    return None


def _analyze_graphql(old: Service, new: Service) -> list[Finding]:
    out: list[Finding] = []
    for key in old.operation_keys():
        new_op = new.find_operation(key)
        old_op = old.find_operation(key)
        if new_op is None or old_op is None:
            out.append(
                Finding(
                    rule_id="GQL-FIELD-REMOVED",
                    severity=Severity.ERROR,
                    message=f"field '{key}' was removed; queries selecting it fail validation",
                    operation_key=key,
                )
            )
            continue
        _graphql_arguments(old_op, new_op, key, out)
        _graphql_return(old_op, new_op, key, out)
    # brand-new fields are safe additions but flagged dangerous for exhaustive clients
    for key in new.operation_keys():
        if old.find_operation(key) is None:
            out.append(
                Finding(
                    rule_id="GQL-DANGEROUS-FIELD-ADDED",
                    severity=Severity.WARN,
                    message=(
                        f"field '{key}' was added; introspection-dependent clients "
                        "(codegens, exhaustive switches) may need regeneration"
                    ),
                    operation_key=key,
                )
            )
    return out


def _graphql_arguments(old_op: Operation, new_op: Operation, key: str, out: list[Finding]) -> None:
    old_args = {p.name: p for p in old_op.parameters}
    new_args = {p.name: p for p in new_op.parameters}
    for name in sorted(set(old_args) - set(new_args)):
        out.append(
            Finding(
                rule_id="GQL-ARGUMENT-REMOVED",
                severity=Severity.ERROR,
                message=f"'{key}' no longer accepts argument '{name}'; callers passing it fail",
                operation_key=key,
            )
        )
    for name in sorted(set(new_args) - set(old_args)):
        p = new_args[name]
        rule = (
            "GQL-REQUIRED-ARGUMENT-ADDED" if p.required else "GQL-DANGEROUS-OPTIONAL-ARGUMENT-ADDED"
        )
        out.append(
            Finding(
                rule_id=rule,
                severity=Severity.ERROR if p.required else Severity.WARN,
                message=(
                    f"'{key}' gained {'required ' if p.required else 'optional '}"
                    f"argument '{name}'" + ("; existing calls break" if p.required else "")
                ),
                operation_key=key,
            )
        )
    for name in sorted(set(old_args) & set(new_args)):
        was, now = old_args[name], new_args[name]
        if was.required and not now.required:
            out.append(
                Finding(
                    rule_id="GQL-DANGEROUS-ARGUMENT-RELAXED",
                    severity=Severity.WARN,
                    message=(
                        f"argument '{name}' of '{key}' changed from required to nullable; "
                        "clients relying on guaranteed presence may misbehave"
                    ),
                    operation_key=key,
                )
            )
        elif not was.required and now.required:
            out.append(
                Finding(
                    rule_id="GQL-ARGUMENT-NULLABILITY-TIGHTENED",
                    severity=Severity.ERROR,
                    message=(
                        f"argument '{name}' of '{key}' became non-null; callers omitting "
                        "it now fail validation"
                    ),
                    operation_key=key,
                )
            )


def _graphql_return(old_op: Operation, new_op: Operation, key: str, out: list[Finding]) -> None:
    old_ret, new_ret = _return_schema(old_op), _return_schema(new_op)
    if old_ret is None or new_ret is None:
        return
    if old_ret.title and new_ret.title and old_ret.title != new_ret.title:
        out.append(
            Finding(
                rule_id="GQL-RETURN-TYPE-CHANGED",
                severity=Severity.ERROR,
                message=f"'{key}' return type changed from {old_ret.title} to {new_ret.title}",
                operation_key=key,
            )
        )
    if not old_ret.nullable and new_ret.nullable:
        out.append(
            Finding(
                rule_id="GQL-DANGEROUS-RETURN-RELAXED",
                severity=Severity.WARN,
                message=(
                    f"'{key}' return became nullable ({old_ret.title}! -> {new_ret.title}); "
                    "clients assuming non-null may crash"
                ),
                operation_key=key,
            )
        )
    elif old_ret.nullable and not new_ret.nullable:
        out.append(
            Finding(
                rule_id="GQL-RETURN-NONNULL-TIGHTENED",
                severity=Severity.ERROR,
                message=(
                    f"'{key}' return became non-null; resolvers may error where they "
                    "previously returned null"
                ),
                operation_key=key,
            )
        )


# --- gRPC / protobuf ---------------------------------------------------------------


def _message_schema(op: Operation, response: bool) -> SchemaNode | None:
    contents: dict[str, SchemaNode] = {}
    if response:
        for resp in op.responses:
            contents.update(resp.content)
    elif op.request_body is not None:
        contents = op.request_body.content
    node = contents.get(_PROTO_MEDIA)
    return node if isinstance(node, SchemaNode) else None


def _analyze_grpc(old: Service, new: Service) -> list[Finding]:
    out: list[Finding] = []
    for key in old.operation_keys():
        new_op = new.find_operation(key)
        old_op = old.find_operation(key)
        if new_op is None or old_op is None:
            out.append(
                Finding(
                    rule_id="PROTO-RPC-REMOVED",
                    severity=Severity.ERROR,
                    message=f"RPC '{key}' was removed; existing stubs fail at runtime",
                    operation_key=key,
                )
            )
            continue
        for label, response in (("request", False), ("response", True)):
            old_msg = _message_schema(old_op, response)
            new_msg = _message_schema(new_op, response)
            if (
                old_msg is not None
                and new_msg is not None
                and old_msg.title
                and new_msg.title
                and old_msg.title != new_msg.title
            ):
                out.append(
                    Finding(
                        rule_id="PROTO-MESSAGE-TYPE-CHANGED",
                        severity=Severity.ERROR,
                        message=(
                            f"RPC '{key}' {label} message changed from {old_msg.title} "
                            f"to {new_msg.title}; payloads decode incorrectly"
                        ),
                        operation_key=key,
                    )
                )
        _proto_wire_fields(_message_schema(old_op, False), _message_schema(new_op, False), key, out)
    return out


def _proto_wire_fields(
    old_msg: SchemaNode | None, new_msg: SchemaNode | None, key: str, out: list[Finding]
) -> None:
    """Compare same-named fields: wire-type changes corrupt encoded payloads."""
    if old_msg is None or new_msg is None:
        return
    for name in sorted(set(old_msg.properties) & set(new_msg.properties)):
        old_node, new_node = old_msg.properties[name], new_msg.properties[name]
        if old_node.type != new_node.type and old_node.type and new_node.type:
            out.append(
                Finding(
                    rule_id="PROTO-WIRE-TYPE-CHANGED",
                    severity=Severity.ERROR,
                    message=(
                        f"RPC '{key}' field '{name}' changed wire type "
                        f"{old_node.type} -> {new_node.type}; on-the-wire values become garbage"
                    ),
                    operation_key=key,
                )
            )
        elif (
            old_node.type == new_node.type
            and old_node.type == "integer"
            and old_node.format
            and new_node.format
            and old_node.format != new_node.format
        ):
            out.append(
                Finding(
                    rule_id="PROTO-WIRE-WIDTH-CHANGED",
                    severity=Severity.WARN,
                    message=(
                        f"RPC '{key}' integer field '{name}' changed {old_node.format} -> "
                        f"{new_node.format}; varint-compatible but overflow behavior differs"
                    ),
                    operation_key=key,
                )
            )
        if old_node.enum and new_node.enum:
            removed = [v for v in old_node.enum if v not in new_node.enum]
            if removed:
                out.append(
                    Finding(
                        rule_id="PROTO-ENUM-VALUE-REMOVED",
                        severity=Severity.ERROR,
                        message=(
                            f"RPC '{key}' enum field '{name}' removed value(s) {removed}; "
                            "peers decoding unknown numerics break"
                        ),
                        operation_key=key,
                    )
                )
    for name in sorted(set(old_msg.properties) - set(new_msg.properties)):
        out.append(
            Finding(
                rule_id="PROTO-FIELD-REMOVED",
                severity=Severity.WARN,
                message=(
                    f"RPC '{key}' message field '{name}' removed; retire (don't reuse) "
                    "its field number to keep wire safety"
                ),
                operation_key=key,
            )
        )
