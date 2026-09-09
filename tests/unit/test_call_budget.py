"""Call budgets: how much an agent is allowed to use an interface.

The most-cited worry about agent traffic is not that an agent calls the wrong
endpoint, it is that it calls the right one ten thousand times — and no
contract in any of the six formats this engine reads has a field for saying how
often anything may be called.

Two things get most of the tests. The window is sliding, because a burst that
straddles a clock boundary is exactly the shape a runaway agent makes. And a
limit naming an operation the contract does not declare is an ERROR, because a
file that looks like protection and matches nothing is worse than no file.
"""

from __future__ import annotations

import contextlib
import io
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from apiverity.cli.commands.common import EXIT_FINDINGS, EXIT_OK, EXIT_USAGE
from apiverity.cli.main import main
from apiverity.core.model import Severity
from apiverity.rules.budget import (
    BudgetError,
    busiest_window,
    evaluate,
    load_budget,
    parse_window,
)

_BASE = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)


def _at(seconds: int) -> str:
    return (_BASE + timedelta(seconds=seconds)).isoformat()


def _call(key: str, seconds: int | None = 0) -> dict[str, Any]:
    return {"operation_key": key, "at": _at(seconds) if seconds is not None else None}


def _budget(tmp_path: Path, body: str) -> Any:
    path = tmp_path / "budget.yaml"
    path.write_text(body, encoding="utf-8")
    return load_budget(path)


def _ids(findings: list[Any]) -> dict[str, Severity]:
    return {f.rule_id: f.severity for f in findings}


def _run(argv: list[str]) -> tuple[int, dict[str, Any], str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    text = out.getvalue()
    return code, (json.loads(text) if text.strip().startswith("{") else {}), err.getvalue()


# ------------------------------------------------------------------- windows


@pytest.mark.parametrize(
    ("text", "seconds"),
    [("30s", 30), ("15m", 900), ("2h", 7200), ("1d", 86400), (" 5 m ", 300)],
)
def test_window_syntax(text: str, seconds: int) -> None:
    assert parse_window(text) == timedelta(seconds=seconds)


def test_an_unparseable_window_is_refused_rather_than_defaulted() -> None:
    """Silently using an hour for `1 fortnight` would enforce the wrong thing."""
    with pytest.raises(BudgetError, match="not understood"):
        parse_window("1 fortnight")


def test_the_window_slides_and_catches_a_burst_across_a_boundary() -> None:
    """The case tumbling buckets miss, and the shape a runaway agent makes."""
    instants = [_BASE + timedelta(seconds=s) for s in (50, 60, 70, 80, 90)]
    peak, at = busiest_window(instants, timedelta(minutes=1))
    assert peak == 5
    assert at == instants[0]


def test_calls_spread_beyond_the_window_do_not_accumulate() -> None:
    instants = [_BASE + timedelta(minutes=m) for m in range(10)]
    peak, _ = busiest_window(instants, timedelta(minutes=1))
    assert peak == 2  # the boundary is inclusive: t and t+60s


def test_an_empty_series_has_no_peak() -> None:
    assert busiest_window([], timedelta(hours=1)) == (0, None)


def test_unsorted_input_gives_the_same_answer() -> None:
    instants = [_BASE + timedelta(seconds=s) for s in (90, 50, 70, 60, 80)]
    assert busiest_window(instants, timedelta(minutes=1))[0] == 5


# -------------------------------------------------------------------- parsing


def test_a_tool_limit_is_sugar_for_the_manifest_operation_key(tmp_path: Path) -> None:
    budget = _budget(tmp_path, "version: 1\nlimits:\n  - tool: search\n    max_calls: 5\n")
    assert budget.limits[0].operation_key == "tool search"


def test_a_limit_needs_an_operation_or_a_tool(tmp_path: Path) -> None:
    with pytest.raises(BudgetError, match="either `operation` or `tool`"):
        _budget(tmp_path, "version: 1\nlimits:\n  - max_calls: 5\n")


def test_a_negative_allowance_is_refused(tmp_path: Path) -> None:
    with pytest.raises(BudgetError, match="non-negative"):
        _budget(tmp_path, "version: 1\nlimits:\n  - tool: a\n    max_calls: -1\n")


def test_a_boolean_allowance_is_refused(tmp_path: Path) -> None:
    """`True` is an int in Python, and `max_calls: yes` is a typo, not a limit."""
    with pytest.raises(BudgetError, match="non-negative"):
        _budget(tmp_path, "version: 1\nlimits:\n  - tool: a\n    max_calls: true\n")


def test_a_future_budget_version_is_refused(tmp_path: Path) -> None:
    with pytest.raises(BudgetError, match="not supported"):
        _budget(tmp_path, "version: 2\nlimits: []\n")


def test_a_per_limit_window_overrides_the_default(tmp_path: Path) -> None:
    budget = _budget(
        tmp_path,
        "version: 1\nwindow: 1h\nlimits:\n  - tool: a\n    max_calls: 5\n    window: 30s\n",
    )
    assert budget.limits[0].window == "30s"


# ----------------------------------------------------------------- evaluation


def test_a_forbidden_operation_that_was_called_is_an_error(tmp_path: Path) -> None:
    budget = _budget(tmp_path, "version: 1\nlimits:\n  - tool: wipe\n    max_calls: 0\n")
    findings = evaluate(budget, [_call("tool wipe")])
    assert _ids(findings)["BUDGET-FORBIDDEN"] is Severity.ERROR


def test_exceeding_a_limit_reports_the_peak_and_when_it_started(tmp_path: Path) -> None:
    budget = _budget(
        tmp_path, "version: 1\nlimits:\n  - tool: search\n    max_calls: 3\n    window: 1m\n"
    )
    calls = [_call("tool search", s) for s in (50, 60, 70, 80, 90)]
    (finding,) = [f for f in evaluate(budget, calls) if f.rule_id == "BUDGET-EXCEEDED"]
    assert "reached 5" in finding.message
    assert "2026-03-01T12:00:50" in finding.message


def test_staying_within_a_limit_reports_nothing_about_it(tmp_path: Path) -> None:
    budget = _budget(
        tmp_path, "version: 1\nlimits:\n  - tool: search\n    max_calls: 3\n    window: 1m\n"
    )
    findings = evaluate(budget, [_call("tool search", 0), _call("tool search", 10)])
    assert "BUDGET-EXCEEDED" not in _ids(findings)


def test_a_limit_nothing_exercised_says_so_rather_than_passing_quietly(tmp_path: Path) -> None:
    """A limit that was never tested has not been shown to hold."""
    budget = _budget(tmp_path, "version: 1\nlimits:\n  - tool: ghost\n    max_calls: 5\n")
    finding = next(f for f in evaluate(budget, []) if f.rule_id == "BUDGET-UNUSED")
    assert finding.severity is Severity.INFO
    assert "says nothing about whether it holds" in finding.message


def test_undated_calls_make_the_peak_a_lower_bound(tmp_path: Path) -> None:
    budget = _budget(tmp_path, "version: 1\nlimits:\n  - tool: a\n    max_calls: 5\n")
    findings = evaluate(budget, [_call("tool a", None), _call("tool a", 0)])
    finding = next(f for f in findings if f.rule_id == "BUDGET-UNDATED-CALLS")
    assert finding.severity is Severity.WARN
    assert "lower bound" in finding.message


def test_traffic_nobody_budgeted_is_a_note_by_default(tmp_path: Path) -> None:
    budget = _budget(tmp_path, "version: 1\nlimits: []\n")
    assert _ids(evaluate(budget, [_call("tool loose")]))["BUDGET-UNBUDGETED"] is Severity.INFO


def test_deny_by_default_turns_that_into_an_error(tmp_path: Path) -> None:
    budget = _budget(tmp_path, "version: 1\ndeny_by_default: true\nlimits: []\n")
    assert _ids(evaluate(budget, [_call("tool loose")]))["BUDGET-UNBUDGETED"] is Severity.ERROR


def test_a_limit_naming_an_operation_the_contract_lacks_is_an_error(tmp_path: Path) -> None:
    """The finding this feature is most worth having.

    A budget full of typos passes every run while protecting nothing.
    """
    budget = _budget(tmp_path, "version: 1\nlimits:\n  - operation: GET /usres\n    max_calls: 5\n")
    findings = evaluate(budget, [], declared_operations={"GET /users"})
    finding = next(f for f in findings if f.rule_id == "BUDGET-OPERATION-UNKNOWN")
    assert finding.severity is Severity.ERROR
    assert "looks like protection and is not" in finding.message


def test_without_a_contract_no_such_claim_is_made(tmp_path: Path) -> None:
    """Nothing to check the key against, so nothing is asserted about it."""
    budget = _budget(tmp_path, "version: 1\nlimits:\n  - operation: GET /usres\n    max_calls: 5\n")
    assert "BUDGET-OPERATION-UNKNOWN" not in _ids(evaluate(budget, []))


# --------------------------------------------------------------------- CLI


def _files(tmp_path: Path) -> tuple[str, str]:
    budget = tmp_path / "budget.yaml"
    budget.write_text("version: 1\nlimits:\n  - tool: wipe\n    max_calls: 0\n", encoding="utf-8")
    calls = tmp_path / "calls.json"
    calls.write_text(json.dumps([{"tool": "wipe", "at": _at(0)}]), encoding="utf-8")
    return str(calls), str(budget)


def test_the_command_fails_on_a_forbidden_call(tmp_path: Path) -> None:
    calls, budget = _files(tmp_path)
    code, payload, _ = _run(["budget", calls, "--budget", budget, "--json"])
    assert code == EXIT_FINDINGS
    assert payload["calls_observed"] == 1
    assert "BUDGET-FORBIDDEN" in {f["rule_id"] for f in payload["findings"]}


def test_clean_traffic_exits_zero(tmp_path: Path) -> None:
    budget = tmp_path / "budget.yaml"
    budget.write_text("version: 1\nlimits: []\n", encoding="utf-8")
    calls = tmp_path / "calls.json"
    calls.write_text("[]", encoding="utf-8")
    code, _, _ = _run(["budget", str(calls), "--budget", str(budget), "--json"])
    assert code == EXIT_OK


def test_a_har_without_a_contract_is_refused(tmp_path: Path) -> None:
    """Matching on raw paths would budget /orders/41 and /orders/42 separately."""
    har = tmp_path / "traffic.har"
    har.write_text(json.dumps({"log": {"entries": []}}), encoding="utf-8")
    budget = tmp_path / "budget.yaml"
    budget.write_text("version: 1\nlimits: []\n", encoding="utf-8")
    code, _, err = _run(["budget", str(har), "--budget", str(budget)])
    assert code == EXIT_USAGE
    assert "--spec is needed" in err


def test_a_har_with_a_contract_resolves_paths_to_operations(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    har = tmp_path / "traffic.har"
    har.write_text(
        json.dumps(
            {
                "log": {
                    "entries": [
                        {
                            "startedDateTime": _at(index),
                            "request": {
                                "method": "GET",
                                "url": "https://api.example.com/users/42",
                                "headers": [],
                                "queryString": [],
                            },
                            "response": {"status": 200, "headers": [], "content": {}},
                        }
                        for index in range(4)
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    budget = tmp_path / "budget.yaml"
    budget.write_text(
        "version: 1\nlimits:\n  - operation: GET /users/{id}\n    max_calls: 2\n    window: 1h\n",
        encoding="utf-8",
    )
    code, payload, _ = _run(
        [
            "budget",
            str(har),
            "--budget",
            str(budget),
            "--spec",
            str(root / "fixtures/apis/crud/openapi.yaml"),
            "--json",
        ]
    )
    assert code == EXIT_FINDINGS
    assert payload["calls_observed"] == 4
    assert "BUDGET-EXCEEDED" in {f["rule_id"] for f in payload["findings"]}


def test_an_unreadable_budget_is_a_usage_error(tmp_path: Path) -> None:
    calls = tmp_path / "calls.json"
    calls.write_text("[]", encoding="utf-8")
    code, _, err = _run(["budget", str(calls), "--budget", str(tmp_path / "nope.yaml")])
    assert code == EXIT_USAGE
    assert "error:" in err
