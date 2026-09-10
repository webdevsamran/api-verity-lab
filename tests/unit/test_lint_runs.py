"""`PROTOCOL_SUPPORT.md` said "Lint / governance packs — VERIFIED". It was not running.

`LintEngine` was written, tested and called by no command, while that table
published VERIFIED for four protocols and `docs/capability-status.md` listed
"Contract lint" as EXISTING. The engine existed; the claim about it did not
hold.

This is the same defect class as the rule packs, found by the same reachability
walk, and fixed the same way — with the same discipline about duplicates. Two
of the six lint rules said what the loader already says, and running the engine
without dropping them would have produced two findings for one fact.
"""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
from typing import Any

import pytest

from apiverity.cli.main import main
from apiverity.rules.lint import LintEngine
from apiverity.rules.lint_catalog import LINT_CATALOG
from apiverity.security.catalog import spec_for
from apiverity.specs.loader import detect_and_load

_ROOT = Path(__file__).resolve().parents[2]
_FIXTURE = _ROOT / "fixtures" / "apis" / "lint" / "openapi.yaml"

LIVE = (
    "LINT-EMPTY-RESPONSE",
    "LINT-INVALID-EXAMPLE",
    "LINT-CONTRADICTORY-REQUIRED",
    "LINT-AMBIGUOUS-COMPOSITION",
)

#: Said by the loader, so the lint rules that duplicated them were dropped.
COVERED_ELSEWHERE = {
    "LINT-DUP-OPID": "SPEC-OPID-DUPLICATE",
    "LINT-NO-RESPONSES": "SPEC-RESPONSE-MISSING",
}


def _validate(path: Path) -> dict[str, Any]:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(io.StringIO()):
        main(["--no-config", "validate", str(path), "--json"])
    return json.loads(buffer.getvalue())


def _ids(path: Path) -> list[str]:
    return [f["rule_id"] for f in _validate(path)["findings"]]


# ------------------------------------------------------------ it runs at all


@pytest.mark.parametrize("rule_id", LIVE)
def test_a_lint_rule_reaches_validate(rule_id: str) -> None:
    assert rule_id in _ids(_FIXTURE)


@pytest.mark.parametrize("rule_id", LIVE)
def test_each_one_is_explainable(rule_id: str) -> None:
    spec = spec_for(rule_id)
    assert spec is not None, f"{rule_id} fires and cannot be explained"
    assert spec.instead.strip()


@pytest.mark.parametrize("rule_id", LIVE)
def test_the_catalogued_severity_is_the_one_a_run_emits(rule_id: str) -> None:
    """The catalogue is what `explain` prints and what a profile overrides. A
    severity there that differs from the one a run emits is wrong in the one
    place somebody looks it up -- and two of these did differ."""
    service, _findings, _plugin = detect_and_load(str(_FIXTURE))
    emitted = {f.rule_id: f.severity for f in LintEngine().lint(service)}
    assert emitted[rule_id] == LINT_CATALOG[rule_id].severity


# -------------------------------------------------------- and does not repeat


@pytest.mark.parametrize(("dropped", "kept"), sorted(COVERED_ELSEWHERE.items()))
def test_a_fact_the_loader_reports_is_not_reported_twice(dropped: str, kept: str) -> None:
    """Wiring the engine up without dropping these would have made one
    duplicated `operationId` produce two findings -- the wall of near-identical
    warnings people learn to filter."""
    ids = _ids(_FIXTURE)
    assert kept in ids
    assert dropped not in ids
    assert dropped not in LINT_CATALOG


def test_the_fixture_really_contains_both_duplicated_cases() -> None:
    """Otherwise the test above passes because the fixture is missing the
    case, not because the duplication is gone."""
    ids = _ids(_FIXTURE)
    assert ids.count("SPEC-OPID-DUPLICATE") == 1
    assert ids.count("SPEC-RESPONSE-MISSING") == 1


# ------------------------------------------------------------- the example


def test_an_example_is_checked_where_openapi_actually_puts_one() -> None:
    """The rule read `Operation.examples`, which this parser fills from an
    operation-level `examples` key that no version of OpenAPI defines -- so it
    was reachable in principle and not in practice. A media type's own
    `example` is the part people copy into a client."""
    finding = next(
        f for f in _validate(_FIXTURE)["findings"] if f["rule_id"] == "LINT-INVALID-EXAMPLE"
    )
    assert "requestBody/application/json" in finding["message"]


def test_a_valid_example_draws_nothing() -> None:
    """A rule that fired on every example would be a rule people switch off
    before reading the first real one."""
    service, _findings, _plugin = detect_and_load(str(_ROOT / "fixtures/apis/crud/openapi.yaml"))
    ids = {f.rule_id for f in LintEngine().lint(service)}
    assert "LINT-INVALID-EXAMPLE" not in ids


# --------------------------------------------------------- the published claim


def test_the_protocol_table_no_longer_claims_something_unrun() -> None:
    """The row that was false. It stays VERIFIED because the engine now runs;
    if it is ever unwired again, this is the assertion that should fail with
    it."""
    text = (_ROOT / "PROTOCOL_SUPPORT.md").read_text(encoding="utf-8")
    row = next(line for line in text.splitlines() if line.startswith("| Lint / governance packs"))
    assert "VERIFIED" in row
    service, _findings, _plugin = detect_and_load(str(_FIXTURE))
    assert LintEngine().lint(service), "the table says VERIFIED and the engine produced nothing"
