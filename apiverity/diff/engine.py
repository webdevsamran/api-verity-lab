"""Semantic contract differ.

Compares two normalized :class:`Service` contracts and produces
:class:`Change` records with **stable IDs** of the form
``CHG-{KIND}-{N}`` where N is a per-kind ordinal derived from the sorted
order of affected operation keys — so IDs survive document reordering
but move predictably when the underlying change moves operations.
"""

from __future__ import annotations

from typing import Any, Optional

from apiverity.core.model import (
    Change,
    ChangeKind,
    Operation,
    Parameter,
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


def _schema_summary(schema: Optional[SchemaNode]) -> str:
    if schema is None:
        return "absent"
    base = schema.type or "any"
    if schema.format:
        base += f"({schema.format})"
    if schema.enum is not None:
        base += f" enum{schema.enum}"
    return base


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
        breaking_hint: Optional[str] = None,
    ) -> Change:
        key = kind.value.upper()
        self._counters[key] = self._counters.get(key, 0) + 1
        change = Change(
            id=f"CHG-{key}-{self._counters[key]}",
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
                ChangeKind.RPC_REMOVED
                if op.kind.value != "http"
                else ChangeKind.OPERATION_REMOVED
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
            kind = (
                ChangeKind.RPC_ADDED
                if op.kind.value != "http"
                else ChangeKind.OPERATION_ADDED
            )
            self._add(
                kind,
                key,
                "meta",
                f"operation '{key}' was added",
                new_location=op.source_location,
            )

        for key in sorted(set(old_ops) & set(new_ops)):
            self._diff_operation(old_ops[key], new_ops[key])

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
            self._add(
                ChangeKind.DESCRIPTION_CHANGED,
                key,
                "meta",
                f"documentation changed for '{key}'",
                old_value=old.summary or old.description,
                new_value=new.summary or new.description,
            )

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
                    "new required parameter: existing clients will fail"
                    if p.required
                    else None
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
                    f"parameter '{name}' ({loc}) requiredness changed "
                    f"{o.required} -> {n.required}",
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

    def _diff_request_body(self, old: Operation, new: Operation, key: str) -> None:
        old_body, new_body = old.request_body, new.request_body
        if old_body is None and new_body is None:
            return
        if old_body is None or new_body is None:
            self._add(
                ChangeKind.REQUEST_SCHEMA_CHANGED,
                key,
                "request",
                "request body "
                + ("removed" if new_body is None else "added"),
                old_location=old_body.source_location if old_body else None,
                new_location=new_body.source_location if new_body else None,
                breaking_hint=(
                    "request body removed: clients sending bodies may break"
                    if new_body is None
                    else "request body added"
                    + (" and required" if new_body.required else "")
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
                f"request body ({media})",
                "request",
            )
        if old_body.required != new_body.required:
            self._add(
                ChangeKind.REQUEST_SCHEMA_CHANGED,
                key,
                "request",
                f"request body requiredness changed {old_body.required} -> {new_body.required}",
                breaking_hint=(
                    "request body became required" if new_body.required else None
                ),
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
        def sec_str(op: Operation) -> list[list[str]]:
            reqs = op.security if op.security is not None else None
            if reqs is None:
                reqs = self.new.global_security if op is new else self.old.global_security
            return sorted([sorted(r.scheme_name for r in req)] for req in reqs) if reqs else []

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
                breaking_hint=(
                    f"enum values removed: {removed}" if removed else None
                ),
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
                    breaking_hint=(
                        f"required field '{prop}' added: existing clients omitting it fail"
                        if direction == "request"
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

        # composition variants
        for attr in ("one_of", "any_of", "all_of"):
            o_variants, n_variants = getattr(old, attr), getattr(new, attr)
            if o_variants and n_variants and len(o_variants) == len(n_variants):
                for i, (o_v, n_v) in enumerate(zip(o_variants, n_variants)):
                    self._diff_schema(
                        o_v, n_v, operation_key, where, direction, path=f"{path}/{attr}[{i}]"
                    )


def diff_services(old: Service, new: Service) -> list[Change]:
    return DiffEngine(old, new).run()