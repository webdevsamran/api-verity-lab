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


def evaluate_breaking(
    changes: list[Change], severity_overrides: dict[str, str] | None = None
) -> list[Finding]:
    return BreakingEngine(severity_overrides).evaluate(changes)
