"""Direction-aware breaking-change rules.

Each rule maps a semantic :class:`Change` to a :class:`Finding` with a
severity that understands **request-vs-response compatibility**:

- Removing/narrowing things clients *send* (requests) is breaking.
- Removing things clients *read* (responses) is breaking.
- Adding response fields or loosening response constraints is safe.
- Narrowing response enums is risky (clients may see unknown values).

Severities can be overridden per rule ID via configuration.
"""

from __future__ import annotations

from dataclasses import dataclass

from apiverity.core.model import Change, ChangeKind, Finding, Severity

# Constraint attributes where an increase tightens the contract.
_TIGHTEN_ON_INCREASE = {
    "minimum",
    "exclusive_minimum",
    "min_length",
    "min_items",
    "min_properties",
    "multiple_of",
}
# Constraint attributes where a decrease tightens the contract.
_TIGHTEN_ON_DECREASE = {
    "maximum",
    "exclusive_maximum",
    "max_length",
    "max_items",
    "max_properties",
}


@dataclass(frozen=True)
class RuleSpec:
    rule_id: str
    severity: Severity
    description: str


#: The documented rule catalog (also rendered by ``apiverity rules``).
CATALOG: dict[str, RuleSpec] = {
    spec.rule_id: spec
    for spec in [
        RuleSpec(
            "BRK-OP-REMOVED",
            Severity.ERROR,
            "An operation was removed; existing callers will fail.",
        ),
        RuleSpec(
            "BRK-RPC-STREAMING-CHANGED",
            Severity.ERROR,
            "An RPC changed streaming cardinality; generated clients call it wrongly.",
        ),
        RuleSpec(
            "BRK-FIELD-NUMBER-REUSED",
            Severity.ERROR,
            "A protobuf field number now names a different field; stored data misdecodes.",
        ),
        RuleSpec(
            "BRK-FIELD-NUMBER-UNRESERVED",
            Severity.WARN,
            "A protobuf field was removed without reserving its number.",
        ),
        RuleSpec(
            "BRK-FIELD-PRESENCE-LOST",
            Severity.ERROR,
            "A protobuf field lost explicit presence; unset and default are now the same.",
        ),
        RuleSpec(
            "BRK-ONEOF-NARROWED",
            Severity.ERROR,
            "A protobuf field moved into a oneof; it is now exclusive with the others.",
        ),
        RuleSpec(
            "BRK-ONEOF-WIDENED",
            Severity.INFO,
            "A protobuf field moved out of a oneof; no existing sender can notice.",
        ),
        RuleSpec(
            "BRK-RESERVATION-REMOVED",
            Severity.WARN,
            "A protobuf field number is no longer reserved and can be reused by mistake.",
        ),
        RuleSpec(
            "BRK-RPC-REMOVED", Severity.ERROR, "A gRPC RPC was removed; existing callers will fail."
        ),
        RuleSpec(
            "BRK-OP-ADDED", Severity.INFO, "A new operation was added (additive, non-breaking)."
        ),
        RuleSpec(
            "BRK-RPC-ADDED", Severity.INFO, "A new gRPC RPC was added (additive, non-breaking)."
        ),
        RuleSpec("BRK-PARAM-REMOVED", Severity.ERROR, "A request parameter was removed."),
        RuleSpec(
            "BRK-PARAM-ADDED-REQUIRED",
            Severity.ERROR,
            "A new required request parameter was added.",
        ),
        RuleSpec(
            "BRK-PARAM-ADDED-OPTIONAL", Severity.INFO, "A new optional request parameter was added."
        ),
        RuleSpec(
            "BRK-PARAM-REQUIRED", Severity.ERROR, "An optional request parameter became required."
        ),
        RuleSpec(
            "BRK-PARAM-OPTIONALIZED", Severity.INFO, "A required request parameter became optional."
        ),
        RuleSpec(
            "BRK-PARAM-TYPE-CHANGED", Severity.ERROR, "A request parameter's type/format changed."
        ),
        RuleSpec(
            "BRK-RESP-TYPE-CHANGED",
            Severity.WARN,
            "A response field's type changed; consumers may misparse values.",
        ),
        RuleSpec(
            "BRK-CONSTRAINT-TIGHTENED",
            Severity.ERROR,
            "A request constraint was tightened; previously valid inputs fail.",
        ),
        RuleSpec(
            "BRK-CONSTRAINT-LOOSENED",
            Severity.INFO,
            "A request constraint was loosened (previously invalid inputs pass).",
        ),
        RuleSpec(
            "BRK-RESP-CONSTRAINT-TIGHTENED",
            Severity.WARN,
            "A response constraint was tightened; returned values may fall "
            "outside what clients expect.",
        ),
        RuleSpec(
            "BRK-ENUM-NARROWED-REQUEST",
            Severity.ERROR,
            "Request enum values were removed; clients sending old values fail.",
        ),
        RuleSpec(
            "BRK-ENUM-NARROWED-RESPONSE",
            Severity.WARN,
            "Response enum values were removed; clients may encounter "
            "undeclared values at runtime.",
        ),
        RuleSpec("BRK-ENUM-WIDENED", Severity.INFO, "Enum values were added (additive)."),
        RuleSpec("BRK-REQ-FIELD-REMOVED", Severity.ERROR, "A request body field was removed."),
        RuleSpec(
            "BRK-REQ-FIELD-OPTIONALIZED",
            Severity.INFO,
            "A request body field became optional; senders are unaffected.",
        ),
        RuleSpec(
            "BRK-RESP-FIELD-OPTIONALIZED",
            Severity.ERROR,
            "A response field is no longer guaranteed; consumers reading it "
            "unconditionally will break.",
        ),
        RuleSpec(
            "BRK-REQ-FIELD-ADDED-REQUIRED",
            Severity.ERROR,
            "A required field was added to a request body.",
        ),
        RuleSpec(
            "BRK-REQ-FIELD-ADDED-OPTIONAL",
            Severity.INFO,
            "An optional field was added to a request body.",
        ),
        RuleSpec(
            "BRK-REQ-FIELD-BECAME-REQUIRED", Severity.ERROR, "A request body field became required."
        ),
        RuleSpec(
            "BRK-RESP-FIELD-REMOVED",
            Severity.ERROR,
            "A response body field was removed; readers of it break.",
        ),
        RuleSpec(
            "BRK-RESP-FIELD-ADDED",
            Severity.INFO,
            "A response body field was added (consumers ignore unknown fields).",
        ),
        RuleSpec("BRK-REQ-BODY-REMOVED", Severity.ERROR, "The request body was removed."),
        RuleSpec(
            "BRK-REQ-BODY-ADDED-REQUIRED", Severity.ERROR, "A required request body was added."
        ),
        RuleSpec(
            "BRK-REQ-BODY-ADDED-OPTIONAL", Severity.INFO, "An optional request body was added."
        ),
        RuleSpec("BRK-REQ-BODY-REQUIRED", Severity.ERROR, "The request body became required."),
        RuleSpec(
            "BRK-RESP-STATUS-REMOVED", Severity.ERROR, "A declared response status was removed."
        ),
        RuleSpec("BRK-RESP-STATUS-ADDED", Severity.INFO, "A new response status was declared."),
        RuleSpec("BRK-HEADER-REMOVED", Severity.WARN, "A declared response header was removed."),
        RuleSpec("BRK-HEADER-ADDED", Severity.INFO, "A new response header was declared."),
        RuleSpec(
            "BRK-SECURITY-CHANGED",
            Severity.ERROR,
            "Security requirements changed; unprepared clients fail auth.",
        ),
        RuleSpec(
            "BRK-DEPRECATION-ADDED",
            Severity.WARN,
            "The operation is now deprecated; plan migration.",
        ),
        RuleSpec("BRK-DEPRECATION-REMOVED", Severity.INFO, "The deprecation marker was removed."),
        RuleSpec(
            "BRK-MEDIA-TYPE-CHANGED",
            Severity.ERROR,
            "A request/response media type was added or removed.",
        ),
        # -- MCP tool manifests ------------------------------------------------
        #
        # Upstream MCP defines no breaking-change semantics for a tool
        # manifest: tools carry no version field, and SEP-1575 "Tool Semantic
        # Versioning" is an open, unsponsored proposal. This taxonomy is
        # api-verity-lab's own, and the generated catalogue says so.
        #
        # Only the changes the shared engine cannot already see live here.
        # A removed tool, a newly-required argument, a narrowed enum and a
        # dropped response field all fire through BRK-RPC-REMOVED,
        # BRK-PARAM-ADDED-REQUIRED, BRK-ENUM-NARROWED-REQUEST and
        # BRK-RESP-FIELD-REMOVED, because an MCP manifest compiles into the
        # same model as every other contract. Duplicating them under an MCP
        # prefix would claim novelty where there is none.
        RuleSpec(
            "BRK-MCP-TOOL-DESCRIPTION-CHANGED",
            Severity.WARN,
            "A tool description changed. For an MCP tool the description is the routing "
            "input the model reads, not documentation for a human, so a silent edit can "
            "redirect an agent (OWASP MCP03, tool poisoning). WARN rather than ERROR "
            "because copy edits are routine; raise it with --severity-override if you "
            "treat a manifest as supply chain.",
        ),
        RuleSpec(
            "BRK-MCP-OUTPUT-SCHEMA-REMOVED",
            Severity.ERROR,
            "A tool stopped declaring an outputSchema; consumers parsing its "
            "structuredContent lose the guarantee they were written against.",
        ),
        RuleSpec(
            "BRK-MCP-OUTPUT-SCHEMA-ADDED",
            Severity.WARN,
            "A tool now declares an outputSchema, so its own results must conform to it "
            "from this version on.",
        ),
        # The four hint rules are WARN, not ERROR, and the reason is the same
        # reason `idempotentHint` is not mapped onto Operation.idempotent: the
        # specification says clients MUST treat annotations as untrusted unless
        # the server is trusted. A rule cannot rest the catalogue's highest
        # severity on a field the protocol itself declines to trust. This
        # matches COMPAT-IDEMPOTENCY-REVOKED, which is WARN for the same
        # reason.
        RuleSpec(
            "BRK-MCP-READONLY-HINT-CLEARED",
            Severity.WARN,
            "A tool stopped claiming readOnlyHint. A host that auto-approved it as safe "
            "to call may now be invoking something that writes.",
        ),
        RuleSpec(
            "BRK-MCP-READONLY-HINT-SET",
            Severity.WARN,
            "A tool now claims readOnlyHint; hosts may stop asking for confirmation on a "
            "claim nobody verified.",
        ),
        RuleSpec(
            "BRK-MCP-DESTRUCTIVE-HINT-SET",
            Severity.WARN,
            "A tool now declares it may perform irreversible updates.",
        ),
        RuleSpec(
            "BRK-MCP-DESTRUCTIVE-HINT-CLEARED",
            Severity.WARN,
            "A tool stopped declaring destructiveHint; hosts may stop gating behaviour "
            "that nobody re-verified as safe.",
        ),
        RuleSpec(
            "BRK-MCP-IDEMPOTENT-HINT-CLEARED",
            Severity.WARN,
            "A tool stopped claiming idempotentHint; a retry that was safe may now "
            "duplicate its effect.",
        ),
        RuleSpec(
            "BRK-MCP-IDEMPOTENT-HINT-SET",
            Severity.WARN,
            "A tool now claims idempotentHint; hosts may begin retrying a call that was "
            "not previously retry-safe.",
        ),
        RuleSpec(
            "BRK-MCP-OPENWORLD-HINT-CHANGED",
            Severity.INFO,
            "openWorldHint changed. It describes the domain a tool reaches into and "
            "constrains no caller.",
        ),
        RuleSpec(
            "BRK-MCP-ANNOTATION-DECLARATION-CHANGED",
            Severity.INFO,
            "An annotation moved between false and undeclared without changing what it asserts.",
        ),
        RuleSpec(
            "BRK-MCP-TOOL-RENAME-SUSPECTED",
            Severity.INFO,
            "Exactly one tool disappeared and one appeared with an identical schema. "
            "Context for the removal, which is still reported: a manifest carries no "
            "identity but the name, so a rename cannot be distinguished from "
            "remove-plus-add.",
        ),
        RuleSpec(
            "BRK-MCP-MANIFEST-TRUNCATED",
            Severity.ERROR,
            "One side is a single page of a paginated tools/list. Every tool past the "
            "page boundary reads as removed, so the whole comparison is unsound.",
        ),
    ]
}


def _constraint_change_is_tightening(attr: str, old: object, new: object) -> bool | None:
    """Return True (tightened), False (loosened) or None (not comparable)."""
    if attr == "pattern":
        return None  # pattern changes are judged separately as WARN
    tightened_up = (
        attr in _TIGHTEN_ON_INCREASE
        and isinstance(old, (int, float))
        and isinstance(new, (int, float))
        and new > old
    )
    tightened_down = (
        attr in _TIGHTEN_ON_DECREASE
        and isinstance(old, (int, float))
        and isinstance(new, (int, float))
        and new < old
    )
    if tightened_up or tightened_down:
        return True
    return None


class BreakingEngine:
    """Evaluates a change set against the breaking-rule catalog."""

    def __init__(self, severity_overrides: dict[str, str] | None = None) -> None:
        self.overrides = {
            rule_id: Severity(value) for rule_id, value in (severity_overrides or {}).items()
        }

    def severity_for(self, rule_id: str) -> Severity:
        return self.overrides.get(rule_id, CATALOG[rule_id].severity)

    def evaluate(self, changes: list[Change]) -> list[Finding]:
        findings: list[Finding] = []
        for change in changes:
            findings.extend(self._evaluate_change(change))
        return findings

    def _finding(
        self, rule_id: str, change: Change, message: str, hint: str | None = None
    ) -> Finding:
        return Finding(
            rule_id=rule_id,
            severity=self.severity_for(rule_id),
            message=message,
            operation_key=change.operation_key,
            location=change.old_location,
            new_location=change.new_location,
            change_id=change.id,
            hint=hint or change.breaking_hint,
        )

    def _evaluate_change(self, change: Change) -> list[Finding]:
        kind, direction = change.kind, change.direction

        if kind in (ChangeKind.OPERATION_REMOVED,):
            return [self._finding("BRK-OP-REMOVED", change, change.description)]
        if kind == ChangeKind.RPC_REMOVED:
            return [self._finding("BRK-RPC-REMOVED", change, change.description)]

        # --- MCP tool manifests ---------------------------------------------
        if kind == ChangeKind.TOOL_DESCRIPTION_CHANGED:
            return [self._finding("BRK-MCP-TOOL-DESCRIPTION-CHANGED", change, change.description)]
        if kind == ChangeKind.TOOL_OUTPUT_SCHEMA_CHANGED:
            rule = (
                "BRK-MCP-OUTPUT-SCHEMA-ADDED"
                if change.new_value
                else "BRK-MCP-OUTPUT-SCHEMA-REMOVED"
            )
            return [self._finding(rule, change, change.description)]
        if kind == ChangeKind.TOOL_RENAME_SUSPECTED:
            return [self._finding("BRK-MCP-TOOL-RENAME-SUSPECTED", change, change.description)]
        if kind == ChangeKind.MANIFEST_TRUNCATED:
            return [self._finding("BRK-MCP-MANIFEST-TRUNCATED", change, change.description)]
        if kind == ChangeKind.TOOL_ANNOTATION_CHANGED:
            annotation_rule = _mcp_annotation_rule(change)
            if annotation_rule is None:
                return []
            return [self._finding(annotation_rule, change, change.description)]

        # --- protobuf ------------------------------------------------------
        if kind == ChangeKind.RPC_STREAMING_CHANGED:
            return [self._finding("BRK-RPC-STREAMING-CHANGED", change, change.description)]
        if kind == ChangeKind.FIELD_NUMBER_REUSED:
            return [self._finding("BRK-FIELD-NUMBER-REUSED", change, change.description)]
        if kind == ChangeKind.FIELD_PRESENCE_CHANGED:
            return [self._finding("BRK-FIELD-PRESENCE-LOST", change, change.description)]
        if kind == ChangeKind.ONEOF_MEMBERSHIP_CHANGED:
            # Moving *into* a oneof narrows what a message may contain: two
            # fields that could both be set no longer can. Moving out widens
            # it, which no existing sender can notice. Two rules rather than
            # one severity switch, so a project can override either.
            rule = (
                "BRK-ONEOF-NARROWED" if "moved into" in change.description else "BRK-ONEOF-WIDENED"
            )
            return [self._finding(rule, change, change.description)]
        if kind == ChangeKind.RESERVATION_CHANGED:
            return [self._finding("BRK-RESERVATION-REMOVED", change, change.description)]
        if (
            kind in (ChangeKind.REQUEST_SCHEMA_CHANGED, ChangeKind.RESPONSE_SCHEMA_CHANGED)
            and "without reserving its number" in change.description
        ):
            return [self._finding("BRK-FIELD-NUMBER-UNRESERVED", change, change.description)]
        if kind in (ChangeKind.OPERATION_ADDED,):
            return [self._finding("BRK-OP-ADDED", change, change.description)]
        if kind == ChangeKind.RPC_ADDED:
            return [self._finding("BRK-RPC-ADDED", change, change.description)]

        if kind == ChangeKind.PARAMETER_REMOVED:
            return [self._finding("BRK-PARAM-REMOVED", change, change.description)]

        if kind == ChangeKind.PARAMETER_ADDED:
            required = "(required)" in change.description
            rule = "BRK-PARAM-ADDED-REQUIRED" if required else "BRK-PARAM-ADDED-OPTIONAL"
            return [self._finding(rule, change, change.description)]

        if kind == ChangeKind.PARAMETER_REQUIREDNESS:
            became_required = change.new_value is True
            # A schema field and a query parameter are different things with
            # different severities, and the response direction inverts which
            # way is breaking: tightening a request breaks senders, relaxing a
            # response breaks readers. Distinguishing them by description was
            # the only signal available without changing the change model.
            is_body_field = "field '" in change.description
            if is_body_field:
                if direction == "response":
                    rule = (
                        "BRK-RESP-FIELD-ADDED" if became_required else "BRK-RESP-FIELD-OPTIONALIZED"
                    )
                else:
                    rule = (
                        "BRK-REQ-FIELD-BECAME-REQUIRED"
                        if became_required
                        else "BRK-REQ-FIELD-OPTIONALIZED"
                    )
            else:
                rule = "BRK-PARAM-REQUIRED" if became_required else "BRK-PARAM-OPTIONALIZED"
            return [self._finding(rule, change, change.description)]

        if kind == ChangeKind.PARAMETER_TYPE_CHANGED:
            rule = "BRK-PARAM-TYPE-CHANGED" if direction == "request" else "BRK-RESP-TYPE-CHANGED"
            return [self._finding(rule, change, change.description)]

        if kind == ChangeKind.PARAMETER_CONSTRAINT_CHANGED:
            return self._evaluate_constraint(change)

        if kind == ChangeKind.ENUM_CHANGED:
            # decide by comparing values directly when available
            old_enum = change.old_value if isinstance(change.old_value, list) else []
            new_enum = change.new_value if isinstance(change.new_value, list) else []
            removed_vals = [v for v in old_enum if v not in new_enum]
            added_vals = [v for v in new_enum if v not in old_enum]
            if removed_vals and direction == "request":
                return [self._finding("BRK-ENUM-NARROWED-REQUEST", change, change.description)]
            if removed_vals:
                return [self._finding("BRK-ENUM-NARROWED-RESPONSE", change, change.description)]
            if added_vals:
                return [self._finding("BRK-ENUM-WIDENED", change, change.description)]
            return []

        if kind == ChangeKind.REQUEST_SCHEMA_CHANGED:
            desc = change.description
            if desc.endswith("removed"):
                return [self._finding("BRK-REQ-BODY-REMOVED", change, desc)]
            if "requiredness changed False -> True" in desc or "became required" in desc:
                return [self._finding("BRK-REQ-BODY-REQUIRED", change, desc)]
            if desc.endswith("added"):
                required = "and required" in desc
                rule = "BRK-REQ-BODY-ADDED-REQUIRED" if required else "BRK-REQ-BODY-ADDED-OPTIONAL"
                return [self._finding(rule, change, desc)]
            return []

        if kind == ChangeKind.RESPONSE_SCHEMA_CHANGED:
            desc = change.description
            if "field" in desc and "was removed" in desc:
                return [self._finding("BRK-RESP-FIELD-REMOVED", change, desc)]
            if "field" in desc and "was added" in desc:
                return [self._finding("BRK-RESP-FIELD-ADDED", change, desc)]
            if "media type" in desc:
                return [self._finding("BRK-MEDIA-TYPE-CHANGED", change, desc)]
            return [self._finding("BRK-RESP-TYPE-CHANGED", change, desc)]

        if kind == ChangeKind.RESPONSE_REMOVED:
            return [self._finding("BRK-RESP-STATUS-REMOVED", change, change.description)]
        if kind == ChangeKind.RESPONSE_ADDED:
            return [self._finding("BRK-RESP-STATUS-ADDED", change, change.description)]
        if kind == ChangeKind.HEADER_REMOVED:
            return [self._finding("BRK-HEADER-REMOVED", change, change.description)]
        if kind == ChangeKind.HEADER_ADDED:
            return [self._finding("BRK-HEADER-ADDED", change, change.description)]
        if kind == ChangeKind.SECURITY_CHANGED:
            return [self._finding("BRK-SECURITY-CHANGED", change, change.description)]
        if kind == ChangeKind.DEPRECATION_ADDED:
            return [self._finding("BRK-DEPRECATION-ADDED", change, change.description)]
        if kind == ChangeKind.DEPRECATION_REMOVED:
            return [self._finding("BRK-DEPRECATION-REMOVED", change, change.description)]

        return []

    def _evaluate_constraint(self, change: Change) -> list[Finding]:
        desc = change.description
        # format change
        if "format changed" in desc:
            rule = (
                "BRK-PARAM-TYPE-CHANGED"
                if change.direction == "request"
                else "BRK-RESP-TYPE-CHANGED"
            )
            return [self._finding(rule, change, desc)]
        # pattern change
        if "'pattern' changed" in desc:
            return [
                self._finding(
                    "BRK-CONSTRAINT-TIGHTENED"
                    if change.direction == "request"
                    else "BRK-RESP-CONSTRAINT-TIGHTENED",
                    change,
                    desc,
                )
            ]
        # numeric/item constraints
        attr = desc.split("constraint '")[1].split("'")[0] if "constraint '" in desc else ""
        tightening = _constraint_change_is_tightening(attr, change.old_value, change.new_value)
        if tightening is None:
            return []
        if change.direction == "request":
            rule = "BRK-CONSTRAINT-TIGHTENED" if tightening else "BRK-CONSTRAINT-LOOSENED"
        else:
            rule = "BRK-RESP-CONSTRAINT-TIGHTENED" if tightening else "BRK-ENUM-WIDENED"
        return [self._finding(rule, change, desc)]


#: (hint, transition) -> rule id. A transition is "set" when the hint becomes
#: true, "cleared" when it stops being true, and None when it moves between
#: false and undeclared -- which changes what the server *says* without
#: changing what it *asserts*.
_MCP_ANNOTATION_RULES: dict[tuple[str, str], str] = {
    ("readOnlyHint", "set"): "BRK-MCP-READONLY-HINT-SET",
    ("readOnlyHint", "cleared"): "BRK-MCP-READONLY-HINT-CLEARED",
    ("destructiveHint", "set"): "BRK-MCP-DESTRUCTIVE-HINT-SET",
    ("destructiveHint", "cleared"): "BRK-MCP-DESTRUCTIVE-HINT-CLEARED",
    ("idempotentHint", "set"): "BRK-MCP-IDEMPOTENT-HINT-SET",
    ("idempotentHint", "cleared"): "BRK-MCP-IDEMPOTENT-HINT-CLEARED",
    ("openWorldHint", "set"): "BRK-MCP-OPENWORLD-HINT-CHANGED",
    ("openWorldHint", "cleared"): "BRK-MCP-OPENWORLD-HINT-CHANGED",
}


def _mcp_annotation_rule(change: Change) -> str | None:
    """Classify an annotation transition from its structured values.

    Reads `old_value`/`new_value`, which the differ emits as
    `{"annotation": name, "value": tri-state}`, rather than matching on the
    message text. Two other dispatches in this file do sniff `description`, and
    both carry a comment saying that is a compromise; a new rule family has no
    reason to inherit it.
    """
    old_value = change.old_value if isinstance(change.old_value, dict) else {}
    new_value = change.new_value if isinstance(change.new_value, dict) else {}
    hint = old_value.get("annotation") or new_value.get("annotation")
    if not isinstance(hint, str):
        return None
    before, after = old_value.get("value"), new_value.get("value")
    if after is True and before is not True:
        transition = "set"
    elif before is True and after is not True:
        transition = "cleared"
    else:
        # false <-> undeclared. The assertion is unchanged, so this is INFO
        # rather than silence: a reviewer can still see the manifest moved.
        return "BRK-MCP-ANNOTATION-DECLARATION-CHANGED"
    return _MCP_ANNOTATION_RULES.get((hint, transition))


def evaluate_breaking(
    changes: list[Change], severity_overrides: dict[str, str] | None = None
) -> list[Finding]:
    return BreakingEngine(severity_overrides).evaluate(changes)
