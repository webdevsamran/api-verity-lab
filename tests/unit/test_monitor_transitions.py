"""A monitor that reports the same twelve findings every five minutes is muted.

These tests are mostly about one thing: the run that could not look must not
be mistaken for the run that found nothing. Those two produce an identical
finding list and mean opposite things, and only one of them is good news.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from apiverity.runtime.monitor import (
    STATE_VERSION,
    UNOBSERVABLE_RULES,
    MonitorState,
    apply_run,
    finding_key,
    measured_count,
    report,
    unobserved_operations,
)

_ROOT = Path(__file__).resolve().parents[2]


def _finding(rule: str, operation: str | None = None, message: str = "m") -> dict[str, object]:
    out: dict[str, object] = {"rule_id": rule, "severity": "ERROR", "message": message}
    if operation:
        out["operation_key"] = operation
    return out


# ------------------------------------------------------------------- identity


def test_a_finding_is_identified_by_its_rule_and_operation() -> None:
    a = _finding("DRIFT-MISSING-FIELD", "GET /users", message="p95 was 210ms")
    b = _finding("DRIFT-MISSING-FIELD", "GET /users", message="p95 was 512ms")
    assert finding_key(a) == finding_key(b)


def test_the_same_rule_on_two_operations_is_two_findings() -> None:
    a = _finding("DRIFT-MISSING-FIELD", "GET /users")
    b = _finding("DRIFT-MISSING-FIELD", "GET /orders")
    assert finding_key(a) != finding_key(b)


def test_a_changed_message_is_not_a_transition_but_is_counted() -> None:
    state = MonitorState()
    apply_run(state, [_finding("R", "GET /a", message="p95 210ms")])
    moved = apply_run(state, [_finding("R", "GET /a", message="p95 512ms")])
    assert moved.appeared == [] and moved.resolved == []
    assert moved.message_changed == 1
    assert moved.persisted[0]["message"] == "p95 512ms"


# ------------------------------------------------------------------- baseline


def test_the_first_run_records_a_baseline_and_alerts_on_nothing() -> None:
    """Otherwise the monitor pages somebody about the existing state of the world."""
    state = MonitorState()
    moved = apply_run(state, [_finding("R", "GET /a"), _finding("R", "GET /b")])
    assert moved.baseline is True
    assert moved.appeared == []
    assert len(moved.persisted) == 2
    assert "none reported as new" in moved.summary()
    assert moved.alerting is False


def test_the_second_run_is_the_first_that_can_report_something_new() -> None:
    state = MonitorState()
    apply_run(state, [_finding("R", "GET /a")])
    moved = apply_run(state, [_finding("R", "GET /a"), _finding("R", "GET /b")])
    assert [f["operation_key"] for f in moved.appeared] == ["GET /b"]
    assert moved.baseline is False
    assert moved.alerting is True


def test_a_finding_that_stops_being_reported_is_resolved() -> None:
    state = MonitorState()
    apply_run(state, [_finding("R", "GET /a")])
    moved = apply_run(state, [])
    assert [f["operation_key"] for f in moved.resolved] == ["GET /a"]
    assert state.findings == {}


def test_a_run_that_changes_nothing_is_not_worth_sending() -> None:
    state = MonitorState()
    apply_run(state, [_finding("R", "GET /a")])
    assert apply_run(state, [_finding("R", "GET /a")]).alerting is False


# ------------------------------------------------- the run that could not look


def test_an_unreachable_operation_does_not_resolve_what_was_known_about_it() -> None:
    """The bug this whole module exists to prevent.

    A probe that fails produces no findings for that operation. Differenced
    naively that reads as "fixed", which is the shape of good news arriving at
    the moment the service stopped answering.
    """
    state = MonitorState()
    apply_run(state, [_finding("DRIFT-MISSING-FIELD", "GET /users")])
    moved = apply_run(state, [_finding("DRIFT-UNREACHABLE", "GET /users")])

    assert moved.resolved == [], "a finding about an unmeasured operation was called fixed"
    assert [f["rule_id"] for f in moved.carried] == ["DRIFT-MISSING-FIELD"]
    assert moved.unobserved == ["GET /users"]
    # And it is still known next time, so the run after this one can resolve it.
    assert any(f["rule_id"] == "DRIFT-MISSING-FIELD" for f in state.findings.values())


def test_a_recovered_operation_resolves_normally_afterwards() -> None:
    state = MonitorState()
    apply_run(state, [_finding("DRIFT-MISSING-FIELD", "GET /users")])
    apply_run(state, [_finding("DRIFT-UNREACHABLE", "GET /users")])
    moved = apply_run(state, [])
    assert sorted(f["rule_id"] for f in moved.resolved) == [
        "DRIFT-MISSING-FIELD",
        "DRIFT-UNREACHABLE",
    ]


def test_one_unreachable_operation_does_not_silence_the_other_forty() -> None:
    """All-or-nothing in either direction is wrong; this partitions."""
    state = MonitorState()
    apply_run(state, [_finding("R", "GET /a"), _finding("R", "GET /b")])
    moved = apply_run(state, [_finding("DRIFT-UNREACHABLE", "GET /a")], measured=39)
    assert [f["operation_key"] for f in moved.resolved] == ["GET /b"]
    assert [f["operation_key"] for f in moved.carried] == ["GET /a"]
    assert moved.inconclusive is None


def test_a_run_where_nothing_at_all_was_measured_says_so() -> None:
    state = MonitorState()
    apply_run(state, [_finding("R", "GET /a"), _finding("R", "GET /b")], measured=2)
    moved = apply_run(
        state,
        [_finding("DRIFT-UNREACHABLE", "GET /a"), _finding("DRIFT-UNREACHABLE", "GET /b")],
        measured=0,
    )
    assert moved.inconclusive is not None
    assert "nothing was measured" in moved.summary()
    assert moved.resolved == []
    assert moved.alerting is True


def test_an_outage_is_read_from_the_count_not_guessed_from_the_findings() -> None:
    """A healthy API with one dead endpoint has the same finding shape as an outage.

    Both runs below carry nothing but unreachable findings. Only the one that
    also reports measuring nothing is an outage; calling the other one
    inconclusive would silence the forty operations that answered.
    """
    healthy = MonitorState()
    apply_run(healthy, [], measured=40)
    still_mostly_fine = apply_run(healthy, [_finding("DRIFT-UNREACHABLE", "GET /a")], measured=39)
    assert still_mostly_fine.inconclusive is None

    down = MonitorState()
    apply_run(down, [], measured=40)
    outage = apply_run(down, [_finding("DRIFT-UNREACHABLE", "GET /a")], measured=0)
    assert outage.inconclusive is not None


def test_a_command_that_reports_no_count_gets_no_guessed_outage() -> None:
    state = MonitorState()
    apply_run(state, [], measured=None)
    moved = apply_run(state, [_finding("DRIFT-UNREACHABLE", "GET /a")], measured=None)
    assert moved.inconclusive is None


def test_the_measured_count_is_found_wherever_the_command_puts_it() -> None:
    assert measured_count({"report": {"operations_checked": 7}}) == 7
    assert measured_count({"report": {"probed": 0}}) == 0
    assert measured_count({"findings": []}) is None
    # `True` is an int in Python and would read as "one thing measured".
    assert measured_count({"operations_checked": True}) is None


def test_a_run_that_never_started_carries_the_whole_state_forward() -> None:
    state = MonitorState()
    apply_run(state, [_finding("R", "GET /a")])
    moved = apply_run(state, None, inconclusive="`drift api.yaml` exited 3")
    assert moved.inconclusive == "`drift api.yaml` exited 3"
    assert moved.resolved == [] and moved.appeared == []
    assert [f["operation_key"] for f in moved.carried] == ["GET /a"]
    assert state.findings, "an inconclusive run erased what was known"
    assert state.runs == 1, "an inconclusive run counted as a run"


def test_the_reported_findings_are_the_new_ones_not_the_standing_ones() -> None:
    """`notify` reads `findings`; sending it the standing state is the muting."""
    state = MonitorState()
    apply_run(state, [_finding("R", "GET /a")])
    moved = apply_run(state, [_finding("R", "GET /a"), _finding("R", "GET /b")])
    body = report(moved, target="drift api.yaml")
    assert [f["operation_key"] for f in body["findings"]] == ["GET /b"]
    assert body["unchanged_count"] == 1, "GET /a was unchanged; GET /b was new"
    assert body["target"] == "drift api.yaml"


# ------------------------------------------------------------------- flapping


def test_a_finding_that_crosses_repeatedly_is_counted_not_suppressed() -> None:
    state = MonitorState()
    apply_run(state, [_finding("R", "GET /a")])
    for _ in range(3):
        apply_run(state, [])
        moved = apply_run(state, [_finding("R", "GET /a")])
    assert state.flaps[finding_key(_finding("R", "GET /a"))] == 6
    assert report(moved)["flapping"], "a repeatedly flapping finding was not named"


def test_a_finding_that_appeared_once_is_not_a_flap() -> None:
    state = MonitorState()
    apply_run(state, [])
    moved = apply_run(state, [_finding("R", "GET /a")])
    assert report(moved)["flapping"] == {}


# ---------------------------------------------------------------- state files


def test_state_survives_a_round_trip(tmp_path: Path) -> None:
    state = MonitorState()
    apply_run(state, [_finding("R", "GET /a")])
    state.target = "drift api.yaml"
    state.save(tmp_path / "s.json")
    again = MonitorState.load(tmp_path / "s.json")
    assert again.findings == state.findings
    assert again.runs == 1
    assert again.target == "drift api.yaml"


def test_a_missing_state_file_is_a_first_run_not_an_error(tmp_path: Path) -> None:
    assert MonitorState.load(tmp_path / "nope.json").runs == 0


def test_a_state_file_from_another_version_is_refused(tmp_path: Path) -> None:
    """Starting over silently would alert on every existing finding as new."""
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"state_version": STATE_VERSION + 1}), encoding="utf-8")
    with pytest.raises(ValueError, match="state version"):
        MonitorState.load(path)


def test_state_is_written_with_sorted_keys_so_two_runs_diff_cleanly(tmp_path: Path) -> None:
    state = MonitorState()
    apply_run(state, [_finding("R", "GET /b"), _finding("R", "GET /a")])
    state.save(tmp_path / "s.json")
    body = (tmp_path / "s.json").read_text(encoding="utf-8")
    assert body.index('"findings"') < body.index('"flaps"') < body.index('"runs"')
    assert json.loads(body)["state_version"] == STATE_VERSION
    assert body.endswith("\n")


# ------------------------------------------------ the list bound to the code


_RULE_ID = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+$")


def _rule_id_literals() -> set[str]:
    """Every rule-id-shaped string literal the package contains.

    Read through `ast` rather than by regex over `rule_id=`, because rules are
    also emitted from dispatch tables where the id is a bare list element.
    """
    found: set[str] = set()
    for path in (_ROOT / "apiverity").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docstrings = {
            node.body[0].value
            for node in ast.walk(tree)
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
        }
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and node not in docstrings
                and _RULE_ID.match(node.value)
            ):
                found.add(node.value)
    return found


def test_every_rule_that_reports_a_failure_to_observe_is_in_the_list() -> None:
    """A rule added later, not listed here, silently resolves real findings.

    `UNOBSERVABLE_RULES` is the difference between "this operation is fine now"
    and "nobody asked it". A new `*-UNREACHABLE` rule that never reaches the
    list gets the first meaning, which is the wrong one.
    """
    conventional = {rule for rule in _rule_id_literals() if "UNREACHABLE" in rule}
    assert conventional, "the scan found no unreachable-style rules at all"
    missing = conventional - UNOBSERVABLE_RULES
    assert not missing, (
        f"{sorted(missing)} report a failure to observe but are not in "
        "UNOBSERVABLE_RULES, so a monitor would call findings about those "
        "operations resolved"
    )


def test_nothing_in_the_list_has_been_deleted_from_the_code() -> None:
    """The other direction: a listed rule no input can produce is dead weight."""
    stale = UNOBSERVABLE_RULES - _rule_id_literals()
    assert not stale, f"{sorted(stale)} is listed but no longer emitted anywhere"


def test_unobserved_operations_ignores_ordinary_findings() -> None:
    assert unobserved_operations([_finding("DRIFT-MISSING-FIELD", "GET /a")]) == set()
    assert unobserved_operations([_finding("DRIFT-UNREACHABLE", "GET /a")]) == {"GET /a"}
