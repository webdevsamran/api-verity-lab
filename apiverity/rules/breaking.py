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
        RuleSpec(
            "BRK-RESP-NULLABLE-ADDED",
            Severity.WARN,
            "A response value that was never null may now be null; every reader that "
            "did not check breaks on the first one, and in a generated client the "
            "field changes type at every use site.",
        ),
        RuleSpec(
            "BRK-RESP-NULLABLE-REMOVED",
            Severity.INFO,
            "A response value can no longer be null (narrowing a response is safe for readers).",
        ),
        RuleSpec(
            "BRK-REQ-NULLABLE-REMOVED",
            Severity.ERROR,
            "A request field that accepted null no longer does; payloads that were "
            "valid are now rejected.",
        ),
        RuleSpec(
            "BRK-REQ-NULLABLE-ADDED",
            Severity.INFO,
            "A request field now accepts null as well (additive).",
        ),
        RuleSpec(
            "BRK-RESP-CONSTRAINT-LOOSENED",
            Severity.WARN,
            "A bound on a response field was relaxed or removed; the service may now return "
            "values a consumer written against the old bound rejects.",
        ),
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
            "BRK-DEPENDENT-REQUIRED-ADDED",
            Severity.ERROR,
            "Sending one field now requires another. A request that set the first without the "
            "second was valid and is not.",
        ),
        RuleSpec(
            "BRK-DEPENDENT-REQUIRED-REMOVED",
            Severity.WARN,
            "A field no longer forces another to be present. Harmless in a request; in a "
            "response it withdraws a guarantee consumers may read unconditionally.",
        ),
        RuleSpec(
            "BRK-DEPENDENT-SCHEMA-CHANGED",
            Severity.WARN,
            "A schema that applies only when some field is present was added, removed or "
            "changed; what is valid now depends on which fields are sent.",
        ),
        RuleSpec(
            "BRK-TUPLE-SHAPE-CHANGED",
            Severity.ERROR,
            "Positional array items changed length or type. Tuple members are read by index, "
            "so a change at one position shifts or misparses every reader.",
        ),
        RuleSpec(
            "BRK-PATTERN-PROPERTIES-CHANGED",
            Severity.WARN,
            "The schema applied to properties matching a name pattern was added, removed or "
            "changed; a whole family of fields changed shape at once.",
        ),
        RuleSpec(
            "BRK-PROPERTY-NAMES-CHANGED",
            Severity.WARN,
            "The constraint on what property *names* are allowed changed; keys that used to be "
            "accepted may not be.",
        ),
        RuleSpec(
            "BRK-CONTAINS-CHANGED",
            Severity.WARN,
            "An array's `contains` requirement or its bounds changed; an array that satisfied "
            "the old rule may not satisfy the new one.",
        ),
        RuleSpec(
            "BRK-CONDITIONAL-SCHEMA-CHANGED",
            Severity.WARN,
            "An `if`/`then`/`else` branch was added, removed or changed. What is valid now "
            "depends on a condition, and the condition moved.",
        ),
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
        RuleSpec(
            "BRK-RESP-FIELD-GUARANTEED",
            Severity.INFO,
            "A response field that was optional is now always present; consumers gain a "
            "guarantee they did not have.",
        ),
        RuleSpec(
            "BRK-SOAP-ACTION-CHANGED",
            Severity.ERROR,
            "The SOAPAction header changed. Gateways and ESBs route on it and generated "
            "stubs send the old one, with an unchanged body that now reaches nothing.",
        ),
        RuleSpec(
            "BRK-SOAP-STYLE-CHANGED",
            Severity.ERROR,
            "A binding moved between document and rpc style, which changes how the body "
            "is wrapped; every existing client serializes it the old way.",
        ),
        RuleSpec(
            "BRK-SOAP-VERSION-CHANGED",
            Severity.ERROR,
            "A port moved between SOAP 1.1 and 1.2. The envelope namespace and the "
            "Content-Type both change, so a 1.1 client gets a 415 rather than a fault.",
        ),
    ]
}


def _is_body_field(change: Change) -> bool:
    """Is this change about a request body field, or a query/path parameter?

    The distinction is not cosmetic. Three rules in the published catalogue --
    `BRK-REQ-FIELD-REMOVED`, `BRK-REQ-FIELD-ADDED-REQUIRED` and
    `BRK-REQ-FIELD-ADDED-OPTIONAL` -- were emitted by no code path at all,
    because the two branches that handle added and removed properties reported
    every one of them as a *parameter*. A reviewer reading "a request parameter
    was removed" about a field in a JSON body goes and looks at the query
    string.

    The signal is the differ's own wording, because a body property and a
    parameter arrive here under the same `ChangeKind`. It was already being
    tested this way one branch below; the bug was that only that branch did it.
    `engine.py` writes `field '<name>'` for a schema property and
    `parameter '<name>' (<location>)` for a parameter, in one place each.
    """
    return "field '" in change.description


def _constraint_change_is_tightening(attr: str, old: object, new: object) -> bool | None:
    """Return True (tightened), False (loosened) or None (not comparable).

    Three things were wrong here and each of them silenced a real finding.

    A constraint *appearing* where there was none read as not-comparable, so
    adding `maxLength: 64` to a request field that had no limit -- which
    rejects input that was valid the day before -- produced a `Change` and no
    finding at all. A constraint disappearing was silent for the same reason,
    which on a response withdraws a guarantee a consumer was given.

    And the function never returned False, so `BRK-CONSTRAINT-LOOSENED` was
    unreachable: the same defect as `SEC-UNAUTH-WRITE`, a rule in the published
    catalogue that no input could ever produce.
    """
    if attr == "pattern":
        return None  # pattern changes are judged separately as WARN

    if attr == "const":
        # `const` admits exactly one value. Gaining one rejects everything
        # else, and moving one rejects the value every existing caller sends;
        # only losing one accepts more.
        return new is not None

    if attr == "unique_items":
        # A bool, not a bound. Requiring uniqueness rejects arrays that were
        # accepted; dropping the requirement accepts more.
        if bool(old) == bool(new):
            return None
        return bool(new)

    if attr not in _TIGHTEN_ON_INCREASE and attr not in _TIGHTEN_ON_DECREASE:
        return None

    numeric = (int, float)
    # A bound that appears constrains what used to be unconstrained, whichever
    # direction it constrains in; a bound that disappears does the reverse.
    if old is None and isinstance(new, numeric):
        return True
    if new is None and isinstance(old, numeric):
        return False
    if not (isinstance(old, numeric) and isinstance(new, numeric)):
        return None
    if old == new:
        return None

    return (new > old) if attr in _TIGHTEN_ON_INCREASE else (new < old)


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

        # --- SOAP ----------------------------------------------------------
        if kind == ChangeKind.SOAP_ACTION_CHANGED:
            return [self._finding("BRK-SOAP-ACTION-CHANGED", change, change.description)]
        if kind == ChangeKind.SOAP_STYLE_CHANGED:
            return [self._finding("BRK-SOAP-STYLE-CHANGED", change, change.description)]
        if kind == ChangeKind.SOAP_VERSION_CHANGED:
            return [self._finding("BRK-SOAP-VERSION-CHANGED", change, change.description)]

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
            rule = "BRK-REQ-FIELD-REMOVED" if _is_body_field(change) else "BRK-PARAM-REMOVED"
            return [self._finding(rule, change, change.description)]

        if kind == ChangeKind.PARAMETER_ADDED:
            required = "(required)" in change.description
            if _is_body_field(change):
                rule = (
                    "BRK-REQ-FIELD-ADDED-REQUIRED" if required else "BRK-REQ-FIELD-ADDED-OPTIONAL"
                )
            else:
                rule = "BRK-PARAM-ADDED-REQUIRED" if required else "BRK-PARAM-ADDED-OPTIONAL"
            return [self._finding(rule, change, change.description)]

        if kind == ChangeKind.PARAMETER_REQUIREDNESS:
            became_required = change.new_value is True
            # A schema field and a query parameter are different things with
            # different severities, and the response direction inverts which
            # way is breaking: tightening a request breaks senders, relaxing a
            # response breaks readers. Distinguishing them by description was
            # the only signal available without changing the change model.
            if _is_body_field(change):
                if direction == "response":
                    # Not `BRK-RESP-FIELD-ADDED`. The severity was right --
                    # gaining a guarantee breaks nobody -- but the rule said a
                    # field was added when the field was already there, and
                    # `explain` then answered with "consumers ignore fields
                    # they do not know", which is advice about a different
                    # change entirely.
                    rule = (
                        "BRK-RESP-FIELD-GUARANTEED"
                        if became_required
                        else "BRK-RESP-FIELD-OPTIONALIZED"
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

        if kind == ChangeKind.NULLABILITY_CHANGED:
            # Direction inverts, as it does for every other widening: relaxing
            # a response breaks readers, tightening a request breaks senders.
            became = bool(change.new_value)
            if direction == "request":
                rule = "BRK-REQ-NULLABLE-ADDED" if became else "BRK-REQ-NULLABLE-REMOVED"
            else:
                rule = "BRK-RESP-NULLABLE-ADDED" if became else "BRK-RESP-NULLABLE-REMOVED"
            return [self._finding(rule, change, change.description)]

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

        if kind == ChangeKind.DEPENDENT_REQUIRED_CHANGED:
            before = change.old_value if isinstance(change.old_value, list) else []
            after = change.new_value if isinstance(change.new_value, list) else []
            gained = bool(set(after) - set(before))
            # Direction inverts, as everywhere else here: tightening a request
            # breaks senders, relaxing a response breaks readers.
            if gained:
                rule = (
                    "BRK-DEPENDENT-REQUIRED-ADDED"
                    if direction == "request"
                    else "BRK-DEPENDENT-REQUIRED-REMOVED"
                )
            else:
                rule = (
                    "BRK-DEPENDENT-REQUIRED-REMOVED"
                    if direction == "request"
                    else "BRK-DEPENDENT-REQUIRED-ADDED"
                )
            return [self._finding(rule, change, change.description)]

        if kind == ChangeKind.DEPENDENT_SCHEMA_CHANGED:
            return [self._finding("BRK-DEPENDENT-SCHEMA-CHANGED", change, change.description)]

        if kind == ChangeKind.TUPLE_SHAPE_CHANGED:
            return [self._finding("BRK-TUPLE-SHAPE-CHANGED", change, change.description)]

        if kind == ChangeKind.PATTERN_PROPERTIES_CHANGED:
            return [self._finding("BRK-PATTERN-PROPERTIES-CHANGED", change, change.description)]

        if kind == ChangeKind.PROPERTY_NAMES_CHANGED:
            return [self._finding("BRK-PROPERTY-NAMES-CHANGED", change, change.description)]

        if kind == ChangeKind.CONTAINS_CHANGED:
            return [self._finding("BRK-CONTAINS-CHANGED", change, change.description)]

        if kind == ChangeKind.CONDITIONAL_SCHEMA_CHANGED:
            return [self._finding("BRK-CONDITIONAL-SCHEMA-CHANGED", change, change.description)]

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
            # Not `BRK-ENUM-WIDENED`. This branch handles numeric and length
            # bounds, and a `min_length` dropped from 1 was reported under a
            # rule about enum values -- so `explain` answered with advice
            # about enums for a finding about string length. Found by
            # benchmarking against oasdiff, which reports the same change and
            # calls it `response-property-min-length-unset`.
            rule = "BRK-RESP-CONSTRAINT-TIGHTENED" if tightening else "BRK-RESP-CONSTRAINT-LOOSENED"
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
