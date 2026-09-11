"""Wire-compatible changes that break every generated client.

The headline case is one line of YAML: rename an `operationId`. The request and
the response are byte-identical, every rule in the catalogue is silent, and
`apiverity diff` reports no change at all -- because `operation_id` is compared
by nothing. Every generated client's call site for the old name stops
compiling.

The second half of this file covers what was found while building the fixture:
`SchemaNode.nullable` was written by the parser and read by nothing, and the
3.1 spelling of it would not load at all.
"""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
from typing import Any

import pytest

from apiverity.cli.commands.common import EXIT_USAGE
from apiverity.cli.main import main
from apiverity.diff.engine import diff_services
from apiverity.diff.sdk_catalog import SDK_CATALOG
from apiverity.diff.sdk_surface import CONVENTIONS, RULE_CONVENTIONS, analyze_sdk_surface
from apiverity.rules.breaking import CATALOG, evaluate_breaking
from apiverity.specs.loader import detect_and_load

_ROOT = Path(__file__).resolve().parents[2]
_V1 = str(_ROOT / "fixtures/apis/sdk/v1.yaml")
_V2 = str(_ROOT / "fixtures/apis/sdk/v2.yaml")


@pytest.fixture(scope="module")
def pair() -> tuple[Any, Any]:
    old, _, _ = detect_and_load(_V1)
    new, _, _ = detect_and_load(_V2)
    return old, new


def _ids(findings: list[Any]) -> set[str]:
    return {f.rule_id for f in findings}


def _run(argv: list[str]) -> tuple[int, dict[str, Any]]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        code = main(argv)
    text = out.getvalue()
    return code, (json.loads(text) if text.strip().startswith("{") else {})


# ------------------------------------------------------------------ the point


def test_a_renamed_operation_id_is_invisible_to_the_wire_diff(pair: tuple[Any, Any]) -> None:
    """The reason this family exists, stated as an assertion.

    `getUser` becomes `fetchUser`. No parameter, schema, status or header
    moves, and the diff produces nothing that names the operation at all.
    """
    old, new = pair
    changes = diff_services(old, new)
    about_rename = [
        c for c in changes if "operationId" in c.description or "operation_id" in c.description
    ]
    assert about_rename == [], "the wire diff grew an operationId comparison"
    assert _ids(evaluate_breaking(changes)) & {"SDK-OPERATION-ID-CHANGED"} == set(), (
        "a breaking rule now covers this; the SDK rule is redundant"
    )


def test_and_the_sdk_pass_reports_it(pair: tuple[Any, Any]) -> None:
    old, new = pair
    findings = analyze_sdk_surface(old, new)
    changed = [f for f in findings if f.rule_id == "SDK-OPERATION-ID-CHANGED"]
    assert len(changed) == 1
    assert "getUser" in changed[0].message and "fetchUser" in changed[0].message
    assert changed[0].operation_key == "GET /users/{id}"


# ---------------------------------------------------------------- every rule


def test_the_fixture_exercises_every_rule_in_the_family(pair: tuple[Any, Any]) -> None:
    """A catalogued rule no input produces is a published rule that is dead."""
    old, new = pair
    fired = _ids(analyze_sdk_surface(old, new))
    missing = set(SDK_CATALOG) - fired - {"SDK-OPERATION-ID-ADDED"}
    assert not missing, f"{sorted(missing)} are catalogued and never produced by the fixture"


def test_an_operation_id_appearing_is_reported_too(pair: tuple[Any, Any]) -> None:
    """The inverse of the fixture's removal, which needs the pair reversed."""
    old, new = pair
    fired = _ids(analyze_sdk_surface(new, old))
    assert "SDK-OPERATION-ID-ADDED" in fired


def test_a_retagged_operation_moves_client_namespace(pair: tuple[Any, Any]) -> None:
    old, new = pair
    finding = next(
        f for f in analyze_sdk_surface(old, new) if f.rule_id == "SDK-TAG-NAMESPACE-CHANGED"
    )
    assert "users" in finding.message and "people" in finding.message


def test_a_widened_response_enum_is_safe_on_the_wire_and_not_in_a_client(
    pair: tuple[Any, Any],
) -> None:
    """The two rules disagree on purpose, and both are right."""
    old, new = pair
    wire = [f for f in evaluate_breaking(diff_services(old, new)) if f.rule_id.startswith("BRK-")]
    widened = next(f for f in wire if f.rule_id == "BRK-ENUM-WIDENED")
    assert widened.severity.value == "INFO", "the wire verdict is additive and safe"

    sdk = next(f for f in analyze_sdk_surface(old, new) if f.rule_id == "SDK-ENUM-VALUE-ADDED")
    assert sdk.severity.value == "WARN"
    assert "enterprise" in sdk.message


def test_reordered_required_parameters_are_reported(pair: tuple[Any, Any]) -> None:
    old, new = pair
    finding = next(
        f for f in analyze_sdk_surface(old, new) if f.rule_id == "SDK-PARAMETER-ORDER-CHANGED"
    )
    assert "'id', 'tenant'" in finding.message
    assert "'tenant', 'id'" in finding.message


def test_an_added_required_parameter_is_not_reported_as_a_reorder(pair: tuple[Any, Any]) -> None:
    """It is already a wire-level finding; twice is noise, not thoroughness."""
    old, _ = pair
    new = old.model_copy(deep=True)
    operation = new.find_operation("GET /users/{id}")
    assert operation is not None
    operation.parameters.insert(
        0, operation.parameters[0].model_copy(deep=True, update={"name": "extra"})
    )
    assert "SDK-PARAMETER-ORDER-CHANGED" not in _ids(analyze_sdk_surface(old, new))


def test_a_removed_operation_produces_no_sdk_noise(pair: tuple[Any, Any]) -> None:
    old, _ = pair
    new = old.model_copy(deep=True)
    new.operations = [op for op in new.operations if op.key != "GET /reports"]
    findings = analyze_sdk_surface(old, new)
    assert findings == [], "an operation that is gone got SDK findings about its surface"


# --------------------------------------------------------------- conventions


def test_every_rule_names_a_convention_that_exists() -> None:
    assert set(RULE_CONVENTIONS) == set(SDK_CATALOG), (
        "a rule is either emitted without a convention or catalogued without a rule"
    )
    assert set(RULE_CONVENTIONS.values()) <= set(CONVENTIONS)
    unused = set(CONVENTIONS) - set(RULE_CONVENTIONS.values())
    assert not unused, f"{sorted(unused)} is a documented convention no rule depends on"


def test_narrowing_the_conventions_removes_rules_rather_than_downgrading_them(
    pair: tuple[Any, Any],
) -> None:
    old, new = pair
    only_ids = analyze_sdk_surface(old, new, {"operation-id-names"})
    assert _ids(only_ids) == {"SDK-OPERATION-ID-CHANGED", "SDK-OPERATION-ID-REMOVED"}


def test_no_conventions_means_no_findings(pair: tuple[Any, Any]) -> None:
    old, new = pair
    assert analyze_sdk_surface(old, new, set()) == []


def test_an_unknown_convention_is_refused(pair: tuple[Any, Any]) -> None:
    old, new = pair
    with pytest.raises(ValueError, match="unknown SDK convention"):
        analyze_sdk_surface(old, new, {"kebab-case-methods"})


def test_every_finding_carries_the_assumption_it_rests_on(pair: tuple[Any, Any]) -> None:
    """A reader who disagrees can see which switch to turn off."""
    old, new = pair
    for finding in analyze_sdk_surface(old, new):
        assert finding.metadata["convention"] in CONVENTIONS
        assert finding.metadata["assumes"] == CONVENTIONS[finding.metadata["convention"]]


def test_nothing_in_this_family_outranks_a_real_breaking_change() -> None:
    """An SDK rule at ERROR gets disabled along with everything near it."""
    loud = [r for r, s in SDK_CATALOG.items() if s.severity.value == "ERROR"]
    assert not loud, f"{loud} claim ERROR for a change that is wire-compatible"


# ------------------------------------------------------------------ the flags


def test_the_sdk_pass_is_off_by_default() -> None:
    _, payload = _run(["breaking", _V1, _V2, "--json"])
    assert not [f for f in payload["findings"] if f["rule_id"].startswith("SDK-")]
    assert "sdk_conventions" not in payload


def test_the_artifact_records_what_it_was_allowed_to_assume() -> None:
    """A narrowed run and a full one would otherwise read as the same run."""
    _, full = _run(["breaking", _V1, _V2, "--sdk", "--json"])
    assert full["sdk_conventions"] == sorted(CONVENTIONS)

    _, narrow = _run(["breaking", _V1, _V2, "--sdk", "--sdk-convention", "closed-enums", "--json"])
    assert narrow["sdk_conventions"] == ["closed-enums"]
    assert {f["rule_id"] for f in narrow["findings"] if f["rule_id"].startswith("SDK-")} == {
        "SDK-ENUM-VALUE-ADDED"
    }


def test_an_unknown_convention_on_the_command_line_is_a_usage_error() -> None:
    code, _ = _run(["breaking", _V1, _V2, "--sdk", "--sdk-convention", "nope"])
    assert code == EXIT_USAGE


def test_explain_knows_these_rules() -> None:
    """A rule nobody can explain gets suppressed rather than fixed."""
    code, payload = _run(["explain", "SDK-OPERATION-ID-CHANGED", "--json"])
    assert code == 0
    assert payload["group"] == "Generated SDKs"
    assert payload["severity"] == "WARN"


# ------------------------------------------------- nullability, found en route


def test_the_3_1_spelling_of_nullable_loads_at_all() -> None:
    """`type: [string, "null"]` raised a pydantic error inside the constructor.

    The parser had a branch for type arrays three lines below the constructor
    that refused them, so the code written for exactly this case could never
    run and a valid 3.1 document failed to load.
    """
    service, _, _ = detect_and_load(_V2)
    operation = service.find_operation("GET /users/{id}")
    assert operation is not None
    schema = operation.responses[0].content["application/json"]
    assert schema.properties["nickname"].nullable is True
    assert schema.properties["nickname"].type == "string", "the non-null type was lost"


def test_a_response_that_may_now_be_null_is_a_finding(pair: tuple[Any, Any]) -> None:
    """`nullable` was parsed for every document and compared by nothing."""
    old, new = pair
    findings = evaluate_breaking(diff_services(old, new))
    added = next(f for f in findings if f.rule_id == "BRK-RESP-NULLABLE-ADDED")
    assert added.severity.value == "WARN"


def test_the_direction_inverts_the_way_it_does_everywhere_else(pair: tuple[Any, Any]) -> None:
    """Relaxing a response breaks readers; tightening a request breaks senders."""
    old, new = pair
    reverse = evaluate_breaking(diff_services(new, old))
    assert "BRK-RESP-NULLABLE-REMOVED" in _ids(reverse)
    assert CATALOG["BRK-RESP-NULLABLE-REMOVED"].severity.value == "INFO"
    assert CATALOG["BRK-REQ-NULLABLE-REMOVED"].severity.value == "ERROR"
    assert CATALOG["BRK-REQ-NULLABLE-ADDED"].severity.value == "INFO"


def test_a_request_field_that_stops_accepting_null_is_an_error() -> None:
    old, _, _ = detect_and_load(_V1)
    new = old.model_copy(deep=True)
    for service, nullable in ((old, True), (new, False)):
        operation = service.find_operation("GET /users/{id}")
        assert operation is not None
        parameter = next(p for p in operation.parameters if p.name == "tenant")
        assert parameter.schema_node is not None
        parameter.schema_node.nullable = nullable
    findings = evaluate_breaking(diff_services(old, new))
    assert "BRK-REQ-NULLABLE-REMOVED" in _ids(findings)
