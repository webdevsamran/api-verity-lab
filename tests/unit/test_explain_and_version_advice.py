"""`explain <rule-id>` and `breaking --suggest-version`.

Both close the same gap from opposite ends: the engine knew the answer and only
ever told you that you were wrong. A rule nobody understands gets suppressed
rather than fixed, and a policy that says "you needed a major bump" without
saying which version to publish leaves the reader to work it out.
"""

from __future__ import annotations

import contextlib
import io
import json
from typing import Any

import pytest

from apiverity.cli.commands.common import EXIT_OK, EXIT_USAGE
from apiverity.cli.main import main
from apiverity.core.model import Change, ChangeKind, Finding, Severity
from apiverity.rules.breaking import CATALOG
from apiverity.rules.semver import suggest_bump


def _run(argv: list[str]) -> tuple[int, dict[str, Any], str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    text = out.getvalue()
    payload: dict[str, Any] = {}
    if text.strip().startswith("{"):
        payload = json.loads(text)
    return code, payload, err.getvalue()


def _finding(rule_id: str, severity: Severity) -> Finding:
    return Finding(rule_id=rule_id, severity=severity, message="x")


def _change(kind: ChangeKind = ChangeKind.DESCRIPTION_CHANGED) -> Change:
    return Change(id="CHG-X-1", kind=kind, direction="meta", operation_key="k", description="d")


# ------------------------------------------------------------------ explain


def test_explain_returns_the_rule_with_somewhere_to_go_next() -> None:
    code, payload, _ = _run(["explain", "BRK-RESP-FIELD-REMOVED", "--json"])
    assert code == EXIT_OK
    assert payload["rule_id"] == "BRK-RESP-FIELD-REMOVED"
    assert payload["severity"] == "ERROR"
    assert payload["group"] == "Responses"
    # The question someone reaching for an override actually has.
    assert "--severity-override BRK-RESP-FIELD-REMOVED=" in payload["override"]
    assert payload["documentation"].startswith("docs/")


def test_explain_is_case_insensitive() -> None:
    code, payload, _ = _run(["explain", "brk-op-removed", "--json"])
    assert code == EXIT_OK
    assert payload["rule_id"] == "BRK-OP-REMOVED"


def test_a_typo_gets_a_suggestion_rather_than_a_dead_end() -> None:
    code, _, err = _run(["explain", "BRK-RESP-FEILD-REMOVED"])
    assert code == EXIT_USAGE
    assert "BRK-RESP-FIELD-REMOVED" in err


def test_an_unrecognisable_id_still_points_at_the_catalog() -> None:
    code, _, err = _run(["explain", "TOTAL-NONSENSE-XYZ"])
    assert code == EXIT_USAGE
    assert "apiverity rules" in err


@pytest.mark.parametrize("rule_id", sorted(CATALOG))
def test_every_rule_in_the_catalog_can_be_explained(rule_id: str) -> None:
    """No rule may be unexplainable.

    A rule the tool cannot describe is one a reader can only silence.
    """
    code, payload, _ = _run(["explain", rule_id, "--json"])
    assert code == EXIT_OK
    assert payload["description"], f"{rule_id} has an empty description"


def test_no_rule_lands_in_the_unclassified_bucket() -> None:
    """`_guide_for` falls back to "Other"; nothing should reach it.

    A new rule family added without a guide entry would silently point readers
    at the top of the catalogue instead of its own section.
    """
    unguided = []
    for rule_id in sorted(CATALOG):
        _, payload, _ = _run(["explain", rule_id, "--json"])
        if payload["group"] == "Other":
            unguided.append(rule_id)
    assert not unguided, f"rules with no guide entry: {unguided}"


# ---------------------------------------------------------- version advice


def test_a_breaking_change_demands_a_major_and_names_the_rules() -> None:
    advice = suggest_bump(
        "1.4.2",
        [_finding("BRK-OP-REMOVED", Severity.ERROR)],
        [_change()],
    )
    assert advice.required_bump == "major"
    assert advice.suggested_version == "2.0.0"
    # A recommendation with nothing behind it is an opinion, not a verdict.
    assert "BRK-OP-REMOVED (ERROR)" in advice.reasons


def test_an_additive_change_is_a_minor() -> None:
    advice = suggest_bump("1.4.2", [], [_change(ChangeKind.OPERATION_ADDED)])
    assert advice.required_bump == "minor"
    assert advice.suggested_version == "1.5.0"


def test_a_documentation_only_change_is_a_patch() -> None:
    advice = suggest_bump("1.4.2", [], [_change(ChangeKind.DESCRIPTION_CHANGED)])
    assert advice.required_bump == "patch"
    assert advice.suggested_version == "1.4.3"


def test_no_changes_means_no_bump() -> None:
    advice = suggest_bump("1.4.2", [], [])
    assert advice.required_bump == "none"
    assert advice.satisfied is True


def test_warnings_only_force_a_minor_when_the_policy_asks() -> None:
    findings = [_finding("BRK-ENUM-NARROWED-RESPONSE", Severity.WARN)]
    lenient = suggest_bump("1.4.2", findings, [_change()])
    strict = suggest_bump("1.4.2", findings, [_change()], require_minor_for_warnings=True)
    assert strict.required_bump == "minor"
    assert lenient.required_bump == "minor"  # risky changes are still not a patch


def test_an_unparseable_version_yields_a_bump_but_never_a_made_up_number() -> None:
    """The bump is knowable from the findings; the number it lands on is not."""
    advice = suggest_bump(
        "not-a-version", [_finding("BRK-OP-REMOVED", Severity.ERROR)], [_change()]
    )
    assert advice.required_bump == "major"
    assert advice.suggested_version is None
    assert any("unparseable" in reason for reason in advice.reasons)


@pytest.mark.parametrize(
    ("declared", "satisfied"),
    [("2.0.0", True), ("1.5.0", False), ("1.4.3", False), ("3.0.0", True)],
)
def test_satisfied_reports_whether_the_declared_version_already_complies(
    declared: str, satisfied: bool
) -> None:
    advice = suggest_bump(
        "1.4.2",
        [_finding("BRK-OP-REMOVED", Severity.ERROR)],
        [_change()],
        declared_new_version=declared,
    )
    assert advice.satisfied is satisfied


def test_the_cli_flag_reports_advice_alongside_the_findings() -> None:
    code, payload, _ = _run(
        [
            "breaking",
            "fixtures/apis/versioned/v1.yaml",
            "fixtures/apis/versioned/v2.yaml",
            "--suggest-version",
            "--json",
        ]
    )
    assert code == 1  # findings exist, which is the gate working
    advice = payload["version_advice"]
    assert advice["required_bump"] == "major"
    assert advice["suggested_version"] == "2.0.0"
    assert advice["reasons"]


def test_advice_is_absent_unless_asked_for() -> None:
    """An opt-in flag that always fires is not opt-in."""
    _, payload, _ = _run(
        [
            "breaking",
            "fixtures/apis/versioned/v1.yaml",
            "fixtures/apis/versioned/v2.yaml",
            "--json",
        ]
    )
    assert "version_advice" not in payload
