"""Every way of detecting drift must produce one readable finding shape.

`apiverity drift` has four modes -- a live HTTP probe, a recorded HAR corpus,
GraphQL introspection, and an MCP server -- and each returned a report whose
findings had a different set of fields. Same command, same flag, four payloads,
and a consumer had to work out which mode ran before it could read anything.

None of them was covered by the published contract either: `result-v1`
constrains a *top-level* `findings` array and every mode nested its findings
under `report`, so the one place the shape is written down did not apply to the
command that varied most. `scripts/validate_result_artifacts.py` never ran
`drift`, which is why nobody noticed.
"""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
from typing import Any

import pytest

from apiverity.cli.main import main
from apiverity.runtime.findings import unify, unify_all

_ROOT = Path(__file__).resolve().parents[2]
_REQUIRED = {"rule_id", "severity", "message"}


def _run(argv: list[str]) -> dict[str, Any]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        main(argv)
    return json.loads(out.getvalue())


# ---------------------------------------------------------------- the shape


def test_the_three_required_fields_are_always_present() -> None:
    assert set(unify({"rule_id": "X-Y", "severity": "warn", "message": "m"})) >= _REQUIRED


def test_severity_is_normalised_to_upper_case() -> None:
    assert unify({"rule_id": "X", "severity": "warn", "message": "m"})["severity"] == "WARN"


def test_a_field_a_mode_cannot_establish_is_absent_not_zero() -> None:
    """Absent and zero are different claims, and only one of them is true."""
    out = unify({"rule_id": "X", "severity": "WARN", "message": "m"})
    assert "occurrences" not in out
    assert "first_seen" not in out


def test_a_mode_that_counts_contributes_its_counts() -> None:
    out = unify(
        {
            "rule_id": "DRIFT-STATUS",
            "severity": "WARN",
            "message": "m",
            "occurrences": 2,
            "observations": 3,
            "first_seen": "2026-03-02T09:00:00Z",
        }
    )
    assert (out["occurrences"], out["observations"]) == (2, 3)
    assert out["first_seen"] == "2026-03-02T09:00:00Z"


def test_a_frequency_is_rounded_so_two_runs_agree() -> None:
    out = unify({"rule_id": "X", "severity": "WARN", "message": "m", "frequency": 2 / 3})
    assert out["frequency"] == 0.6667


def test_it_reads_a_model_as_readily_as_a_dict() -> None:
    """The four modes return three different pydantic classes."""
    from apiverity.runtime.mcp_drift import McpFinding

    out = unify(
        McpFinding(
            rule_id="MCP-DRIFT-SCHEMA",
            severity="ERROR",
            message="m",
            tool="search",
            change_id="CHG-1",
            source_rule_id="BRK-RPC-REMOVED",
        )
    )
    assert out["tool"] == "search"
    assert out["source_rule_id"] == "BRK-RPC-REMOVED"


def test_unify_all_preserves_order() -> None:
    findings = [{"rule_id": f"R-{i}", "severity": "WARN", "message": "m"} for i in range(4)]
    assert [f["rule_id"] for f in unify_all(findings)] == ["R-0", "R-1", "R-2", "R-3"]


# ------------------------------------------------------------- through the CLI


def test_a_corpus_run_writes_a_top_level_findings_array() -> None:
    payload = _run(
        [
            "drift",
            str(_ROOT / "fixtures/apis/crud/openapi.yaml"),
            "--corpus",
            str(_ROOT / "fixtures/traffic/crud.har"),
            "--json",
        ]
    )
    assert payload["findings"], "a corpus with an undeclared status should report something"
    for finding in payload["findings"]:
        assert set(finding) >= _REQUIRED


def test_the_mode_specific_report_is_still_there() -> None:
    """Additive on purpose: a consumer reading `report` keeps working."""
    payload = _run(
        [
            "drift",
            str(_ROOT / "fixtures/apis/crud/openapi.yaml"),
            "--corpus",
            str(_ROOT / "fixtures/traffic/crud.har"),
            "--json",
        ]
    )
    assert "report" in payload
    assert len(payload["report"]["findings"]) == len(payload["findings"])


def test_the_corpus_mode_contributes_frequency_and_span() -> None:
    payload = _run(
        [
            "drift",
            str(_ROOT / "fixtures/apis/crud/openapi.yaml"),
            "--corpus",
            str(_ROOT / "fixtures/traffic/crud.har"),
            "--json",
        ]
    )
    finding = next(f for f in payload["findings"] if f["rule_id"] == "DRIFT-STATUS")
    assert finding["occurrences"] == 2
    assert finding["first_seen"] < finding["last_seen"]


@pytest.mark.parametrize(
    "field",
    ["tool", "occurrences", "observations", "frequency", "first_seen", "change_id"],
)
def test_every_optional_field_is_published_in_the_schema(field: str) -> None:
    """A field a consumer may read has to be in the contract they read it from."""
    schema = json.loads((_ROOT / "schemas" / "result-v1.schema.json").read_text(encoding="utf-8"))
    assert field in schema["properties"]["findings"]["items"]["properties"]
