"""Adopting a drift gate on an API that already has drift.

Point `drift` at a service that has run for three years and it reports forty
findings, all of them true and none of them today's problem. The gate goes red
on its first run, somebody makes it advisory, and it never comes back. A
baseline records what was already wrong so the gate fails on what is *newly*
wrong -- the only thing a pull request can be held responsible for.

`drift_trend.py` has had the comparison since the first version and nothing in
the CLI ever called it. The mechanism existed and was unreachable, which is the
same defect this repository keeps finding in itself.
"""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
from typing import Any

from apiverity.cli.commands.common import EXIT_FINDINGS, EXIT_OK
from apiverity.cli.main import main
from apiverity.runtime.drift_trend import classify, export, fingerprint, read_baseline

_ROOT = Path(__file__).resolve().parents[2]
_SPEC = str(_ROOT / "fixtures/apis/crud/openapi.yaml")
_HAR = str(_ROOT / "fixtures/traffic/crud.har")


def _finding(rule: str = "DRIFT-STATUS", message: str = "m", op: str = "GET /users") -> dict:
    return {"rule_id": rule, "severity": "WARN", "message": message, "operation_key": op}


def _run(argv: list[str]) -> tuple[int, dict[str, Any], str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    text = out.getvalue()
    return code, (json.loads(text) if text.strip().startswith("{") else {}), err.getvalue()


# ------------------------------------------------------------- fingerprints


def test_the_same_finding_fingerprints_the_same_way() -> None:
    assert fingerprint(_finding()) == fingerprint(_finding())


def test_a_different_message_is_a_different_finding() -> None:
    assert fingerprint(_finding()) != fingerprint(_finding(message="something else"))


def test_severity_is_not_part_of_the_identity() -> None:
    """A finding whose grade was overridden is the same finding.

    A baseline that forgot it because somebody changed a threshold would
    re-report old drift as new, which is the failure this exists to avoid.
    """
    lowered = {**_finding(), "severity": "INFO"}
    assert fingerprint(_finding()) == fingerprint(lowered)


def test_an_mcp_finding_keyed_by_tool_still_fingerprints() -> None:
    """A baseline from one mode has to be the same kind of file as another's."""
    mcp = {"rule_id": "MCP-DRIFT-SCHEMA", "severity": "ERROR", "message": "m", "tool": "search"}
    assert fingerprint(mcp)


# --------------------------------------------------------------- classifying


def test_a_finding_in_the_baseline_is_known() -> None:
    baseline = read_baseline(export([_finding()], target="t"))
    marked, resolved = classify([_finding()], baseline)
    assert [f["state"] for f in marked] == ["known"]
    assert resolved == []


def test_a_finding_not_in_the_baseline_is_new() -> None:
    baseline = read_baseline(export([_finding()], target="t"))
    marked, _ = classify([_finding(message="fresh")], baseline)
    assert [f["state"] for f in marked] == ["new"]


def test_a_baseline_finding_that_went_away_is_reported_as_resolved() -> None:
    """The half of the report that makes the other half credible."""
    baseline = read_baseline(export([_finding(), _finding(message="gone")], target="t"))
    marked, resolved = classify([_finding()], baseline)
    assert len(resolved) == 1
    assert all(f["state"] == "known" for f in marked)


def test_an_empty_baseline_makes_everything_new() -> None:
    marked, _ = classify([_finding()], set())
    assert marked[0]["state"] == "new"


def test_a_baseline_file_records_what_it_is_of() -> None:
    data = export([_finding()], target="https://api.example.com")
    assert data["baseline_version"] == 1
    assert data["target"] == "https://api.example.com"
    assert data["finding_count"] == 1


def test_a_malformed_baseline_reads_as_empty_rather_than_raising() -> None:
    assert read_baseline({"fingerprints": "not-a-list"}) == set()


# ----------------------------------------------------------------- the gate


def test_without_a_baseline_a_finding_fails_the_run() -> None:
    code, _, _ = _run(["drift", _SPEC, "--corpus", _HAR, "--json"])
    assert code == EXIT_FINDINGS


def test_a_known_finding_no_longer_fails_the_run(tmp_path: Path) -> None:
    """The whole point: a gate you can turn on today."""
    baseline = tmp_path / "baseline.json"
    _run(["drift", _SPEC, "--corpus", _HAR, "--save-baseline", str(baseline), "--json"])

    code, payload, _ = _run(
        ["drift", _SPEC, "--corpus", _HAR, "--baseline", str(baseline), "--json"]
    )
    assert code == EXIT_OK
    assert payload["trend"]["new"] == 0
    assert payload["trend"]["known"] == 1


def test_a_known_finding_is_still_in_the_artifact(tmp_path: Path) -> None:
    """Silenced for the gate, not deleted from the report."""
    baseline = tmp_path / "baseline.json"
    _run(["drift", _SPEC, "--corpus", _HAR, "--save-baseline", str(baseline), "--json"])
    _, payload, _ = _run(["drift", _SPEC, "--corpus", _HAR, "--baseline", str(baseline), "--json"])
    assert [f["state"] for f in payload["findings"]] == ["known"]


def test_a_new_finding_against_a_baseline_still_fails(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps(export([], target="t")), encoding="utf-8")
    code, payload, _ = _run(
        ["drift", _SPEC, "--corpus", _HAR, "--baseline", str(baseline), "--json"]
    )
    assert code == EXIT_FINDINGS
    assert payload["trend"]["new"] == 1


def test_an_unreadable_baseline_is_a_usage_error(tmp_path: Path) -> None:
    code, _, err = _run(
        ["drift", _SPEC, "--corpus", _HAR, "--baseline", str(tmp_path / "nope.json")]
    )
    assert code == 2
    assert "could not read baseline" in err


def test_the_flag_works_in_text_mode_too(tmp_path: Path) -> None:
    """It did not. The text branch fell through to its own gate, so
    `--baseline` silenced nothing unless `--json` was also passed."""
    baseline = tmp_path / "baseline.json"
    _run(["drift", _SPEC, "--corpus", _HAR, "--save-baseline", str(baseline), "--json"])

    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        code = main(["drift", _SPEC, "--corpus", _HAR, "--baseline", str(baseline)])
    assert code == EXIT_OK
    body = out.getvalue()
    assert "0 new, 1 known" in body
    assert "[known]" in body
