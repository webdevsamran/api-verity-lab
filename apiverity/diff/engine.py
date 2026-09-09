"""Semantic contract differ.

Compares two normalized :class:`Service` contracts and produces
:class:`Change` records with **stable IDs** of the form
``CHG-{KIND}-{operation-hash}-{N}``, where the hash is the first eight hex
characters of sha256 over the canonical operation key and N is an ordinal
within that (kind, operation) pair.

Scoping the ordinal to the operation is what makes the id stable: reordering
the operations in a spec document does not renumber anything, because no
counter is shared across operations. An id therefore survives being quoted in
a review or used to suppress a finding, and changes only when the underlying
change genuinely moves to a different operation.

This docstring previously described a flat ``CHG-{KIND}-{N}`` ordinal as
having that property. It did not: a single shared counter per kind meant
moving one operation up the file renumbered every later change of that kind.
"""

from __future__ import annotations

import hashlib
from typing import Any

from apiverity.core.model import (
    Change,
    ChangeKind,
    Operation,
    OperationKind,
    Parameter,
    Protocol,
    SchemaNode,
    Service,
)

# JSON-Schema-like constraint attributes compared for constraint changes
_CONSTRAINT_ATTRS = (
    "minimum",
    "maximum",
    "exclusive_minimum",
    "exclusive_maximum",
    "multiple_of",
    "min_length",
    "max_length",
    "pattern",
    "min_items",
    "max_items",
    "unique_items",
    "min_properties",
    "max_properties",
)


def _schema_summary(schema: SchemaNode | None) -> str:
    if schema is None:
        return "absent"
    base = schema.type or "any"
    if schema.format:
        base += f"({schema.format})"
    if schema.enum is not None:
        base += f" enum{schema.enum}"
    return base


def _operation_hash(operation_key: str) -> str:
    """Short, stable digest of an operation key.

    Eight hex characters of sha256. Long enough that a collision inside one
    contract is not a practical concern, short enough that the id stays
    readable in a terminal and a review comment. Changes that belong to no
    single operation (a version bump, a server change) share the `global`
    scope rather than being given a hash of the empty string, which would read
    as though it identified something.
    """
    if not operation_key:
        return "global"
    return hashlib.sha256(operation_key.encode("utf-8")).hexdigest()[:8]


def _hint_word(value: object) -> str:
    """Render a tri-state hint for a human.

    "undeclared" is not the same claim as "false": the specification gives each
    hint a documented default, but a default is what a client may assume, not
    what the server said. Collapsing them would report a change that never
    happened the first time a server started stating a hint explicitly.
    """
    if value is True:
        return "true"
    if value is False:
        return "false"
    return "undeclared"


def _tool_shape(op: Operation) -> str:
    """A stable hash of what a tool accepts and returns.

    Deliberately excludes name, title and description: those are exactly what a
    rename changes, so including them would mean no rename is ever suspected.
    """
    body = op.request_body.model_dump_json() if op.request_body else ""
    responses = "".join(sorted(r.model_dump_json() for r in op.responses))
    return hashlib.sha256(f"{body}|{responses}".encode()).hexdigest()


class DiffEngine:
    """Produces the semantic change set between two contracts."""

    def __init__(self, old: Service, new: Service) -> None:
        self.old = old
        self.new = new
        self.changes: list[Change] = []
        self._counters: dict[str, int] = {}

    # -- change construction -------------------------------------------------

    def _add(
        self,
        kind: ChangeKind,
        operation_key: str,
        direction: str,
        description: str,
        *,
        old_value: Any = None,
        new_value: Any = None,
        old_location: Any = None,
        new_location: Any = None,
        breaking_hint: str | None = None,
    ) -> Change:
        key = kind.value.upper()
        # Scoped per (kind, operation) so an id survives reordering of the spec
        # document. ARCHITECTURE.md has always documented
        # `CHG-{kind}-{operation-hash}-{index}` with exactly that property,
        # but the id was a flat per-kind ordinal with no hash: moving an
        # operation up the file renumbered every change after it, so an id
        # quoted in a review or used to suppress a finding pointed somewhere
        # else on the next run. The ordinal is still per-operation, because
        # one operation can produce several changes of the same kind.
        op_hash = _operation_hash(operation_key)
        scope = f"{key}:{op_hash}"
        self._counters[scope] = self._counters.get(scope, 0) + 1
        change = Change(
            id=f"CHG-{key}-{op_hash}-{self._counters[scope]}",
            kind=kind,
            direction=direction,
            operation_key=operation_key,
            description=description,
            old_value=old_value,
            new_value=new_value,
            old_location=old_location,
            new_location=new_location,
            breaking_hint=breaking_hint,
        )
        self.changes.append(change)
        return change

    # -- entry point -----------------------------------------------------------

    def run(self) -> list[Change]:
        old_ops = {op.key: op for op in self.old.operations}
        new_ops = {op.key: op for op in self.new.operations}

        for key in sorted(set(old_ops) - set(new_ops)):
            op = old_ops[key]
            kind = (
                ChangeKind.RPC_REMOVED if op.kind.value != "http" else ChangeKind.OPERATION_REMOVED
            )
            self._add(
                kind,
                key,
                "meta",
                f"operation '{key}' was removed",
                old_location=op.source_location,
                breaking_hint="existing clients calling this operation will fail",
            )

        for key in sorted(set(new_ops) - set(old_ops)):
            op = new_ops[key]
            kind = ChangeKind.RPC_ADDED if op.kind.value != "http" else ChangeKind.OPERATION_ADDED
            self._add(
                kind,
                key,
                "meta",
                f"operation '{key}' was added",
                new_location=op.source_location,
            )

        for key in sorted(set(old_ops) & set(new_ops)):
            self._diff_operation(old_ops[key], new_ops[key])

        if Protocol.MCP in (self.old.protocol, self.new.protocol):
            self._diff_mcp_manifest()

        if self.old.version != self.new.version:
            self._add(
                ChangeKind.DESCRIPTION_CHANGED,
                "(service)",
                "meta",
                f"contract version changed '{self.old.version}' -> '{self.new.version}'",
                old_value=self.old.version,
                new_value=self.new.version,
            )

        old_servers = [s.url for s in self.old.servers]
        new_servers = [s.url for s in self.new.servers]
        if old_servers != new_servers:
            self._add(
                ChangeKind.SERVER_CHANGED,
                "(service)",
                "meta",
                f"server list changed {old_servers} -> {new_servers}",
                old_value=old_servers,
                new_value=new_servers,
            )

        return self.changes

    # -- per-operation ------------------------------------------------------------

    def _diff_operation(self, old: Operation, new: Operation) -> None:
        key = old.key
        self._diff_parameters(old, new, key)
        self._diff_grpc_signature(old, new, key)
        self._diff_request_body(old, new, key)
        self._diff_responses(old, new, key)
        self._diff_security(old, new, key)

        if not old.deprecated and new.deprecated:
            self._add(
                ChangeKind.DEPRECATION_ADDED,
                key,
                "meta",
                f"operation '{key}' is now deprecated",
                new_location=new.source_location,
            )
        elif old.deprecated and not new.deprecated:
            self._add(
                ChangeKind.DEPRECATION_REMOVED,
                key,
                "meta",
                f"operation '{key}' deprecation was removed",
                old_location=old.source_location,
            )

        if old.description != new.description or old.summary != new.summary:
            # For an MCP tool the description is not documentation a human
            # reads -- it is the routing input the model consumes when it picks
            # a tool. A silent edit is the documented tool-poisoning vector
            # (OWASP MCP03), so it gets its own kind and its own rule rather
            # than sharing the INFO-level one every other protocol uses.
            self._add(
                ChangeKind.TOOL_DESCRIPTION_CHANGED
                if old.kind == OperationKind.MCP_TOOL
                else ChangeKind.DESCRIPTION_CHANGED,
                key,
                "meta",
                f"documentation changed for '{key}'",
                old_value=old.summary or old.description,
                new_value=new.summary or new.description,
            )

        if old.kind == OperationKind.MCP_TOOL and new.kind == OperationKind.MCP_TOOL:
            self._diff_mcp_tool(old, new, key)

        old_examples = {e.name: e.value for e in old.examples}
        new_examples = {e.name: e.value for e in new.examples}
        if old_examples != new_examples:
            self._add(
                ChangeKind.EXAMPLE_CHANGED,
                key,
                "meta",
                f"examples changed for '{key}'",
                old_value=sorted(old_examples),
                new_value=sorted(new_examples),
            )

    def _diff_mcp_manifest(self) -> None:
        """Facts about the two manifests as documents, not about any one tool.

        Truncation is reported here and not only at load time because
        `common._pair()` discards load findings, so a page-one capture would
        otherwise reach `breaking` silently -- and acting on one is a mass
        false positive: every tool past the page boundary reads as removed.

        A rename is *suspected*, never asserted. A manifest carries no identity
        but the name, so remove-plus-add and rename are genuinely
        indistinguishable; the suspicion is raised only for exactly one out and
        one in, and it never suppresses the removal finding.
        """
        old_mcp = self.old.bindings.get("mcp") or {}
        new_mcp = self.new.bindings.get("mcp") or {}
        if not isinstance(old_mcp, dict) or not isinstance(new_mcp, dict):
            return

        for label, meta in (("old", old_mcp), ("new", new_mcp)):
            if meta.get("truncated"):
                self._add(
                    ChangeKind.MANIFEST_TRUNCATED,
                    "(service)",
                    "meta",
                    (
                        f"the {label} manifest is one page of a paginated tools/list; "
                        "tools beyond it will read as removed"
                    ),
                    old_value=label == "old",
                    new_value=label == "new",
                )

        new_keys = {o.key for o in self.new.operations}
        old_keys = {o.key for o in self.old.operations}
        removed = sorted(
            op.rpc_name
            for op in self.old.operations
            if op.kind == OperationKind.MCP_TOOL and op.rpc_name and op.key not in new_keys
        )
        added = sorted(
            op.rpc_name
            for op in self.new.operations
            if op.kind == OperationKind.MCP_TOOL and op.rpc_name and op.key not in old_keys
        )
        if len(removed) == 1 and len(added) == 1:
            gone = next(o for o in self.old.operations if o.rpc_name == removed[0])
            fresh = next(o for o in self.new.operations if o.rpc_name == added[0])
            if _tool_shape(gone) == _tool_shape(fresh):
                self._add(
                    ChangeKind.TOOL_RENAME_SUSPECTED,
                    f"tool {removed[0]}",
                    "meta",
                    (
                        f"tool '{removed[0]}' disappeared and '{added[0]}' appeared with an "
                        "identical schema; this may be a rename, which agents calling the old "
                        "name cannot follow"
                    ),
                    old_value=removed[0],
                    new_value=added[0],
                )

    def _diff_mcp_tool(self, old: Operation, new: Operation, key: str) -> None:
        """Changes only an MCP tool can have.

        The four `ToolAnnotations` hints and the presence of an `outputSchema`
        are carried in `Operation.bindings["mcp"]`, deliberately outside the
        shared schema surface, so nothing else in the engine looks at them.

        Transitions are emitted structurally -- `old_value` and `new_value`
        carry `{"annotation": ..., "value": ...}` -- rather than being encoded
        into the message for the rule engine to string-match. Two existing
        dispatches in `rules/breaking.py` sniff `change.description`, and the
        code says outright that this is a compromise; there is no reason to add
        a third.
        """
        old_mcp = old.bindings.get("mcp") or {}
        new_mcp = new.bindings.get("mcp") or {}
        if not isinstance(old_mcp, dict) or not isinstance(new_mcp, dict):
            return

        old_ann = old_mcp.get("annotations") or {}
        new_ann = new_mcp.get("annotations") or {}
        if isinstance(old_ann, dict) and isinstance(new_ann, dict):
            for hint in ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint"):
                before, after = old_ann.get(hint), new_ann.get(hint)
                if before == after:
                    continue
                self._add(
                    ChangeKind.TOOL_ANNOTATION_CHANGED,
                    key,
                    "meta",
                    f"annotation '{hint}' changed {_hint_word(before)} -> {_hint_word(after)}",
                    old_value={"annotation": hint, "value": before},
                    new_value={"annotation": hint, "value": after},
                    old_location=old.source_location,
                    new_location=new.source_location,
                )

        had = bool(old_mcp.get("declares_output_schema"))
        has = bool(new_mcp.get("declares_output_schema"))
        if had != has:
            self._add(
                ChangeKind.TOOL_OUTPUT_SCHEMA_CHANGED,
                key,
                "response",
                (
                    "tool now declares an outputSchema, so its results must conform to it"
                    if has
                    else "tool no longer declares an outputSchema; consumers reading "
                    "structuredContent lose their guarantee"
                ),
                old_value=had,
                new_value=has,
                old_location=old.source_location,
                new_location=new.source_location,
            )

    def _diff_parameters(self, old: Operation, new: Operation, key: str) -> None:
        def index(params: list[Parameter]) -> dict[tuple[str, str], Parameter]:
            return {(p.name, p.location.value): p for p in params}

        old_p, new_p = index(old.parameters), index(new.parameters)
        for ident in sorted(set(old_p) - set(new_p)):
            p = old_p[ident]
            self._add(
                ChangeKind.PARAMETER_REMOVED,
                key,
                "request",
                f"parameter '{ident[0]}' ({ident[1]}) was removed",
                old_location=p.source_location,
                breaking_hint="clients still sending this parameter may receive errors",
            )
        for ident in sorted(set(new_p) - set(old_p)):
            p = new_p[ident]
            self._add(
                ChangeKind.PARAMETER_ADDED,
                key,
                "request",
                f"parameter '{ident[0]}' ({ident[1]}) was added"
                + (" (required)" if p.required else ""),
                new_location=p.source_location,
                breaking_hint=(
                    "new required parameter: existing clients will fail" if p.required else None
                ),
            )
        for ident in sorted(set(old_p) & set(new_p)):
            o, n = old_p[ident], new_p[ident]
            name, loc = ident
            if o.required != n.required:
                self._add(
                    ChangeKind.PARAMETER_REQUIREDNESS,
                    key,
                    "request",
                    f"parameter '{name}' ({loc}) requiredness changed {o.required} -> {n.required}",
                    old_value=o.required,
                    new_value=n.required,
                    old_location=o.source_location,
                    new_location=n.source_location,
                    breaking_hint=(
                        "parameter became required: existing clients omitting it will fail"
                        if n.required
                        else None
                    ),
                )
            if _schema_summary(o.schema_node) != _schema_summary(n.schema_node):
                self._add(
                    ChangeKind.PARAMETER_TYPE_CHANGED,
                    key,
                    "request",
                    f"parameter '{name}' ({loc}) type changed "
                    f"'{_schema_summary(o.schema_node)}' -> '{_schema_summary(n.schema_node)}'",
                    old_value=_schema_summary(o.schema_node),
                    new_value=_schema_summary(n.schema_node),
                    old_location=o.source_location,
                    new_location=n.source_location,
                )
            elif o.schema_node is not None and n.schema_node is not None:
                self._diff_schema(
                    o.schema_node,
                    n.schema_node,
                    key,
                    f"request parameter '{name}'",
                    "request",
                )

    def _diff_grpc_signature(self, old: Operation, new: Operation, key: str) -> None:
        """Streaming direction changes, which no generated client survives.

        A stub generated against a unary RPC calls it unary. Turning that same
        method name into a stream is not a new shape for an existing call --
        it is a different call that happens to share a name, and every
        existing client fails at the transport. The `stream` markers were
        parsed and discarded, so this produced no change at all.
        """
        if old.kind != OperationKind.GRPC_RPC or new.kind != OperationKind.GRPC_RPC:
            return
        if (old.client_streaming, old.server_streaming) == (
            new.client_streaming,
            new.server_streaming,
        ):
            return

        def describe(op: Operation) -> str:
            if op.client_streaming and op.server_streaming:
                return "bidirectional streaming"
            if op.client_streaming:
                return "client streaming"
            if op.server_streaming:
                return "server streaming"
            return "unary"

        self._add(
            ChangeKind.RPC_STREAMING_CHANGED,
            key,
            "meta",
            f"RPC changed from {describe(old)} to {describe(new)}",
            old_value=describe(old),
            new_value=describe(new),
            old_location=old.source_location,
            new_location=new.source_location,
            breaking_hint=(
                "generated clients call this method with the wrong cardinality "
                "and fail at the transport"
            ),
        )

    @staticmethod
    def _wire_shape(node: SchemaNode | None) -> str:
        """How a field is encoded, as far as compatibility is concerned.

        `format` carries the protobuf width, which is what decides
        compatibility: int32 and int64 share a wire type and are
        interchangeable, while int32 and string do not.
        """
        if node is None:
            return "unknown"
        if node.type == "array" and node.items is not None:
            return f"repeated {DiffEngine._wire_shape(node.items)}"
        return node.format or node.type or "unknown"

    def _diff_protobuf_schema(
        self, old: SchemaNode, new: SchemaNode, operation_key: str, label: str, direction: str
    ) -> None:
        """Changes that only mean something in protobuf.

        Field numbers are the wire identity: a rename is safe and a renumber
        is not, and a name-keyed comparison reports the opposite of both.
        """
        # A number whose name changed. Whether that matters depends entirely
        # on the type, and getting this wrong in either direction is bad:
        #
        # - Same type: a rename. The wire carries numbers, not names, so old
        #   data still decodes correctly into the renamed field. It breaks
        #   generated code and JSON transcoding, not the wire. Reporting it as
        #   data corruption would train people to ignore the rule.
        # - Different type: the number now means something else. Data written
        #   by an older client decodes into a field of the wrong type, which
        #   is the exact failure `reserved` exists to prevent.
        for number in sorted(set(old.field_numbers) & set(new.field_numbers)):
            was, now = old.field_numbers[number], new.field_numbers[number]
            if was == now:
                continue
            old_field = old.properties.get(was)
            new_field = new.properties.get(now)
            old_type = self._wire_shape(old_field)
            new_type = self._wire_shape(new_field)
            if old_type == new_type:
                self._add(
                    ChangeKind.REQUEST_SCHEMA_CHANGED
                    if direction == "request"
                    else ChangeKind.RESPONSE_SCHEMA_CHANGED,
                    operation_key,
                    direction,
                    f"{label}: field {number} renamed from '{was}' to '{now}' "
                    f"(same type, wire-compatible)",
                    old_value=was,
                    new_value=now,
                    breaking_hint=(
                        "the wire is unaffected, but generated code and any JSON "
                        "transcoding use the name"
                    ),
                )
                continue
            self._add(
                ChangeKind.FIELD_NUMBER_REUSED,
                operation_key,
                direction,
                f"{label}: field number {number} changed from '{was}' ({old_type}) "
                f"to '{now}' ({new_type})",
                old_value=was,
                new_value=now,
                breaking_hint=(
                    f"data written by older clients still carries field {number} and will "
                    f"decode into '{now}', which has a different type; reserve the number "
                    "instead of reusing it"
                ),
            )

        # A number that is gone without being reserved: nothing stops the next
        # author reusing it.
        dropped = set(old.field_numbers) - set(new.field_numbers)
        unreserved = sorted(dropped - set(new.reserved_numbers))
        for number in unreserved:
            self._add(
                ChangeKind.RESPONSE_SCHEMA_CHANGED
                if direction == "response"
                else ChangeKind.REQUEST_SCHEMA_CHANGED,
                operation_key,
                direction,
                f"{label}: field '{old.field_numbers[number]}' ({number}) removed "
                "without reserving its number",
                old_value=old.field_numbers[number],
                new_value=None,
                breaking_hint=(
                    f"add `reserved {number};` so the number cannot be reused for something else"
                ),
            )

        # Explicit presence, gained or lost.
        for name in sorted(set(old.explicit_presence) - set(new.explicit_presence)):
            if name not in new.properties:
                continue
            self._add(
                ChangeKind.FIELD_PRESENCE_CHANGED,
                operation_key,
                direction,
                f"{label}: field '{name}' lost explicit presence",
                old_value=True,
                new_value=False,
                breaking_hint=(
                    "an unset field and a field set to its default are no longer distinguishable"
                ),
            )

        # oneof membership. Moving a field into a oneof makes it mutually
        # exclusive with fields that were previously independent.
        old_members = {f: g for g, fs in old.oneofs.items() for f in fs}
        new_members = {f: g for g, fs in new.oneofs.items() for f in fs}
        for name in sorted(set(new_members) - set(old_members)):
            if name not in old.properties:
                continue
            self._add(
                ChangeKind.ONEOF_MEMBERSHIP_CHANGED,
                operation_key,
                direction,
                f"{label}: field '{name}' moved into oneof '{new_members[name]}'",
                old_value=None,
                new_value=new_members[name],
                breaking_hint=(
                    "setting this field now clears the others in the oneof; senders "
                    "that set several will silently lose all but the last"
                ),
            )
        for name in sorted(set(old_members) - set(new_members)):
            if name not in new.properties:
                continue
            self._add(
                ChangeKind.ONEOF_MEMBERSHIP_CHANGED,
                operation_key,
                direction,
                f"{label}: field '{name}' moved out of oneof '{old_members[name]}'",
                old_value=old_members[name],
                new_value=None,
            )

        # A number un-reserved: the guard against reuse was removed.
        for number in sorted(set(old.reserved_numbers) - set(new.reserved_numbers)):
            if number in new.field_numbers:
                continue
            self._add(
                ChangeKind.RESERVATION_CHANGED,
                operation_key,
                direction,
                f"{label}: field number {number} is no longer reserved",
                old_value=number,
                new_value=None,
                breaking_hint="nothing now prevents this number being reused",
            )

    @staticmethod
    def _payload_direction(op: Operation) -> str:
        """Which compatibility rules a message payload should be judged by.

        For HTTP the request body is a request: tightening it breaks callers.
        For an event the answer depends on who produces the message. A payload
        the application *sends* is read by consumers, so removing a field from
        it is breaking in exactly the way a response is -- and it was being
        classified as a request relaxation, i.e. reported at INFO with the
        message "senders are unaffected", when the application is the sender
        and it is the consumers who break.
        """
        if op.kind == OperationKind.EVENT and op.direction == "send":
            return "response"
        return "request"

    def _diff_request_body(self, old: Operation, new: Operation, key: str) -> None:
        old_body, new_body = old.request_body, new.request_body
        payload_direction = self._payload_direction(new if new_body is not None else old)
        if old_body is None and new_body is None:
            return
        if old_body is None or new_body is None:
            self._add(
                ChangeKind.REQUEST_SCHEMA_CHANGED,
                key,
                "request",
                "request body " + ("removed" if new_body is None else "added"),
                old_location=old_body.source_location if old_body else None,
                new_location=new_body.source_location if new_body else None,
                breaking_hint=(
                    "request body removed: clients sending bodies may break"
                    if new_body is None
                    else "request body added" + (" and required" if new_body.required else "")
                    if new_body.required
                    else None
                ),
            )
            return
        old_media = set(old_body.content)
        new_media = set(new_body.content)
        for media in sorted(old_media & new_media):
            self._diff_schema(
                old_body.content[media],
                new_body.content[media],
                key,
                ("message payload" if payload_direction == "response" else "request body")
                + f" ({media})",
                payload_direction,
            )
        # Request media types that came or went. Only the intersection was
        # walked before, so dropping a request content type -- narrowing
        # `application/json, application/xml` down to JSON alone -- produced no
        # change at all, while the equivalent response-side removal was
        # reported. Removing one breaks every client still sending it.
        for media in sorted(old_media - new_media):
            self._add(
                ChangeKind.REQUEST_SCHEMA_CHANGED,
                key,
                "request",
                f"request media type '{media}' removed",
                old_value=media,
                breaking_hint=(
                    f"clients sending Content-Type: {media} will be rejected; "
                    "keep accepting it or version the operation"
                ),
            )
        for media in sorted(new_media - old_media):
            self._add(
                ChangeKind.REQUEST_SCHEMA_CHANGED,
                key,
                "request",
                f"request media type '{media}' added",
                new_value=media,
            )
        if old_body.required != new_body.required:
            self._add(
                ChangeKind.REQUEST_SCHEMA_CHANGED,
                key,
                "request",
                f"request body requiredness changed {old_body.required} -> {new_body.required}",
                breaking_hint=("request body became required" if new_body.required else None),
            )

    def _diff_responses(self, old: Operation, new: Operation, key: str) -> None:
        old_r = {r.status: r for r in old.responses}
        new_r = {r.status: r for r in new.responses}
        for status in sorted(set(old_r) - set(new_r)):
            self._add(
                ChangeKind.RESPONSE_REMOVED,
                key,
                "response",
                f"response status '{status}' was removed",
                old_location=old_r[status].source_location,
                breaking_hint="clients handling this status will encounter undeclared responses",
            )
        for status in sorted(set(new_r) - set(old_r)):
            self._add(
                ChangeKind.RESPONSE_ADDED,
                key,
                "response",
                f"response status '{status}' was added",
                new_location=new_r[status].source_location,
            )
        for status in sorted(set(old_r) & set(new_r)):
            o, n = old_r[status], new_r[status]
            for header in sorted(set(o.headers) - set(n.headers)):
                self._add(
                    ChangeKind.HEADER_REMOVED,
                    key,
                    "response",
                    f"response {status} header '{header}' was removed",
                    old_location=o.source_location,
                )
            for header in sorted(set(n.headers) - set(o.headers)):
                self._add(
                    ChangeKind.HEADER_ADDED,
                    key,
                    "response",
                    f"response {status} header '{header}' was added",
                    new_location=n.source_location,
                )
            for media in sorted(set(o.content) & set(n.content)):
                self._diff_schema(
                    o.content[media],
                    n.content[media],
                    key,
                    f"response {status} body ({media})",
                    "response",
                )
            for media in sorted(set(o.content) ^ set(n.content)):
                self._add(
                    ChangeKind.RESPONSE_SCHEMA_CHANGED,
                    key,
                    "response",
                    f"response {status} media type '{media}' "
                    + ("removed" if media in o.content else "added"),
                )

    def _diff_security(self, old: Operation, new: Operation, key: str) -> None:
        def sec_str(op: Operation) -> list[str]:
            reqs = op.security
            if reqs is None:
                reqs = self.new.global_security if op is new else self.old.global_security
            return sorted(r.scheme_name for r in reqs)

        o_sec, n_sec = sec_str(old), sec_str(new)
        if o_sec != n_sec:
            self._add(
                ChangeKind.SECURITY_CHANGED,
                key,
                "security",
                f"security requirements changed {o_sec} -> {n_sec}",
                old_value=o_sec,
                new_value=n_sec,
                old_location=old.source_location,
                new_location=new.source_location,
                breaking_hint="clients without the new credentials will fail authentication",
            )

    # -- schema-level ----------------------------------------------------------------

    def _diff_schema(
        self,
        old: SchemaNode,
        new: SchemaNode,
        operation_key: str,
        where: str,
        direction: str,
        path: str = "",
    ) -> None:
        label = f"{where}{path}"

        # A default is client-visible behaviour, not documentation. Introducing
        # one on a request field changes what the server assumes when the field
        # is omitted; changing or removing one on a response field changes what
        # callers actually receive. _diff_schema compared type, format, enum
        # and constraints but never `default`, so these passed silently.
        if old.field_numbers or new.field_numbers:
            self._diff_protobuf_schema(old, new, operation_key, label, direction)

        if old.default != new.default:
            self._add(
                ChangeKind.REQUEST_SCHEMA_CHANGED
                if direction == "request"
                else ChangeKind.RESPONSE_SCHEMA_CHANGED,
                operation_key,
                direction,
                f"{label}: default changed {old.default!r} -> {new.default!r}",
                old_value=old.default,
                new_value=new.default,
                old_location=old.source_location,
                new_location=new.source_location,
                breaking_hint=(
                    "a default introduced where there was none changes behaviour "
                    "for callers that omit this field"
                    if old.default is None
                    else None
                ),
            )

        if old.type != new.type:
            self._add(
                ChangeKind.PARAMETER_TYPE_CHANGED
                if direction == "request"
                else ChangeKind.RESPONSE_SCHEMA_CHANGED,
                operation_key,
                direction,
                f"{label}: type changed '{old.type}' -> '{new.type}'",
                old_value=old.type,
                new_value=new.type,
                old_location=old.source_location,
                new_location=new.source_location,
            )

        if old.format != new.format:
            self._add(
                ChangeKind.PARAMETER_CONSTRAINT_CHANGED,
                operation_key,
                direction,
                f"{label}: format changed '{old.format}' -> '{new.format}'",
                old_value=old.format,
                new_value=new.format,
                old_location=old.source_location,
                new_location=new.source_location,
            )

        if old.enum != new.enum:
            removed = sorted(set(old.enum or []) - set(new.enum or []))
            added = sorted(set(new.enum or []) - set(old.enum or []))
            self._add(
                ChangeKind.ENUM_CHANGED,
                operation_key,
                direction,
                f"{label}: enum changed (removed {removed}, added {added})",
                old_value=old.enum,
                new_value=new.enum,
                old_location=old.source_location,
                new_location=new.source_location,
                breaking_hint=(f"enum values removed: {removed}" if removed else None),
            )

        for attr in _CONSTRAINT_ATTRS:
            o_val, n_val = getattr(old, attr), getattr(new, attr)
            if o_val != n_val:
                self._add(
                    ChangeKind.PARAMETER_CONSTRAINT_CHANGED,
                    operation_key,
                    direction,
                    f"{label}: constraint '{attr}' changed {o_val!r} -> {n_val!r}",
                    old_value=o_val,
                    new_value=n_val,
                    old_location=old.source_location,
                    new_location=new.source_location,
                )

        # object properties
        for prop in sorted(set(old.properties) - set(new.properties)):
            self._add(
                ChangeKind.PARAMETER_REMOVED
                if direction == "request"
                else ChangeKind.RESPONSE_SCHEMA_CHANGED,
                operation_key,
                direction,
                f"{label}: field '{prop}' was removed",
                old_location=old.properties[prop].source_location,
                breaking_hint=(
                    f"field '{prop}' removed from {direction}: "
                    + (
                        "clients sending it may be rejected"
                        if direction == "request"
                        else "clients reading it will break"
                    )
                ),
            )
        for prop in sorted(set(new.properties) - set(old.properties)):
            n_prop = new.properties[prop]
            self._add(
                ChangeKind.PARAMETER_ADDED
                if direction == "request"
                else ChangeKind.RESPONSE_SCHEMA_CHANGED,
                operation_key,
                direction,
                f"{label}: field '{prop}' was added"
                + (" (required)" if prop in new.required else ""),
                new_location=n_prop.source_location,
                breaking_hint=(
                    f"required field '{prop}' added to request: existing clients fail"
                    if direction == "request" and prop in new.required
                    else None
                ),
            )
        for prop in sorted(set(old.properties) & set(new.properties)):
            self._diff_schema(
                old.properties[prop],
                new.properties[prop],
                operation_key,
                where,
                direction,
                path=f"{path}.{prop}",
            )

        # required list changes
        old_req = set(old.required)
        new_req = set(new.required)
        for prop in sorted(new_req - old_req):
            if prop in new.properties:
                self._add(
                    ChangeKind.PARAMETER_REQUIREDNESS,
                    operation_key,
                    direction,
                    f"{label}: field '{prop}' became required",
                    # Passed explicitly: the rule engine decides severity from
                    # this value, and without it a field *becoming required*
                    # was classified BRK-PARAM-OPTIONALIZED at INFO -- the
                    # exact opposite of what happened, downgrading a breaking
                    # request change to informational so it passed CI gates.
                    old_value=False,
                    new_value=True,
                    new_location=new.properties[prop].source_location,
                    breaking_hint=(
                        f"required field '{prop}' added: existing clients omitting it fail"
                        if direction == "request"
                        else None
                    ),
                )
        for prop in sorted(old_req - new_req):
            if prop in old.properties:
                # The reverse direction, which was not detected at all. It is
                # relaxation in a request and breakage in a response: a client
                # that always read this field may now receive objects without
                # it, and nothing in the contract warned them.
                self._add(
                    ChangeKind.PARAMETER_REQUIREDNESS,
                    operation_key,
                    direction,
                    f"{label}: field '{prop}' became optional",
                    old_value=True,
                    new_value=False,
                    old_location=old.properties[prop].source_location,
                    breaking_hint=(
                        f"field '{prop}' is no longer guaranteed in the response; "
                        "consumers reading it unconditionally will break"
                        if direction == "response"
                        else None
                    ),
                )

        # arrays
        if old.items is not None and new.items is not None:
            self._diff_schema(
                old.items,
                new.items,
                operation_key,
                where,
                direction,
                path=f"{path}[]",
            )

        # polymorphic discriminator
        old_disc = old.discriminator or {}
        new_disc = new.discriminator or {}
        if old_disc or new_disc:
            old_prop = old_disc.get("propertyName")
            new_prop = new_disc.get("propertyName")
            if old_prop != new_prop:
                self._add(
                    ChangeKind.REQUEST_SCHEMA_CHANGED
                    if direction == "request"
                    else ChangeKind.RESPONSE_SCHEMA_CHANGED,
                    operation_key,
                    direction,
                    f"{label}: discriminator property changed {old_prop!r} -> {new_prop!r}",
                    old_value=old_prop,
                    new_value=new_prop,
                    breaking_hint=(
                        "clients branch on the discriminator property; renaming it "
                        "breaks every consumer that deserializes this type"
                    ),
                )
            old_map = dict(old_disc.get("mapping") or {})
            new_map = dict(new_disc.get("mapping") or {})
            for key in sorted(set(old_map) - set(new_map)):
                self._add(
                    ChangeKind.REQUEST_SCHEMA_CHANGED
                    if direction == "request"
                    else ChangeKind.RESPONSE_SCHEMA_CHANGED,
                    operation_key,
                    direction,
                    f"{label}: discriminator mapping removed {key!r}",
                    old_value=key,
                    breaking_hint=(
                        f"variant {key!r} can no longer be resolved; senders using it are rejected"
                        if direction == "request"
                        else f"variant {key!r} was withdrawn from the response contract"
                    ),
                )
            for key in sorted(set(new_map) - set(old_map)):
                # Additive in a request, but not in a response: a consumer with
                # an exhaustive switch over the known variants meets a value it
                # has no branch for.
                self._add(
                    ChangeKind.REQUEST_SCHEMA_CHANGED
                    if direction == "request"
                    else ChangeKind.RESPONSE_SCHEMA_CHANGED,
                    operation_key,
                    direction,
                    f"{label}: discriminator mapping added {key!r}",
                    new_value=key,
                    breaking_hint=(
                        f"new response variant {key!r}: consumers with an exhaustive "
                        "switch over the previous variants will not handle it"
                        if direction == "response"
                        else None
                    ),
                )
            for key in sorted(set(old_map) & set(new_map)):
                if old_map[key] != new_map[key]:
                    self._add(
                        ChangeKind.REQUEST_SCHEMA_CHANGED
                        if direction == "request"
                        else ChangeKind.RESPONSE_SCHEMA_CHANGED,
                        operation_key,
                        direction,
                        f"{label}: discriminator {key!r} now maps to "
                        f"{new_map[key]!r} (was {old_map[key]!r})",
                        old_value=old_map[key],
                        new_value=new_map[key],
                        breaking_hint=(
                            f"the same discriminator value {key!r} now selects a "
                            "different schema; clients deserialize into the wrong type"
                        ),
                    )
        # composition variants
        for attr in ("one_of", "any_of", "all_of"):
            o_variants, n_variants = getattr(old, attr), getattr(new, attr)
            if o_variants and n_variants and len(o_variants) == len(n_variants):
                for i, (o_v, n_v) in enumerate(zip(o_variants, n_variants, strict=True)):
                    self._diff_schema(
                        o_v, n_v, operation_key, where, direction, path=f"{path}/{attr}[{i}]"
                    )


def diff_services(old: Service, new: Service, *, canonical: bool = True) -> list[Change]:
    """Compare two contracts.

    Canonicalized first by default, because the comparison is meant to be
    semantic and the raw documents are not. `allOf: [Base, {extra}]` and the
    same schema written inline describe the same contract, and without this the
    differ -- which zips `allOf` branches positionally -- reports refactoring a
    spec as rewriting it.

    Deliberately here rather than in the loader: `validate` reports on the
    document as written, source locations and all, and should not be shown a
    rewritten one. Only the comparison needs meaning rather than text.

    `canonical=False` compares the documents as they are, which is occasionally
    what you want when the question is about the document rather than the API.
    """
    if canonical:
        from apiverity.core.canonical import canonicalize_service

        old, _ = canonicalize_service(old)
        new, _ = canonicalize_service(new)
    return DiffEngine(old, new).run()


__all__ = ["Change", "diff_services"]
