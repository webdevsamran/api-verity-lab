"""The escape hatch, and the one-line file that used to turn the gate off.

`apiverity/rules/suppressions.py` said suppressions "must carry an owner and
reason, and expire automatically so permanent ignore-lists do not accumulate
silently". `docs/ci.md` said "each one needs an owner, a reason and an expiry".

None of that was enforced. This file is those sentences, made true, plus the
two that were never said out loud: an expiry far enough away is not an expiry,
and a rule silenced across every operation is a different decision from one
silenced on an endpoint.

Every test here fails against the code as it was, which is the only reason to
write one.
"""

from __future__ import annotations

import contextlib
import io
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import yaml

from apiverity.cli.main import main
from apiverity.core.model import Finding, Severity
from apiverity.rules.suppressions import (
    DEFAULT_MAX_LIFETIME_DAYS,
    Suppression,
    apply_suppressions,
    incomplete_suppression_findings,
    load_suppressions,
    unscoped_suppression_findings,
)

_ROOT = Path(__file__).resolve().parents[2]
_V1 = str(_ROOT / "fixtures/apis/versioned/v1.yaml")
_V2 = str(_ROOT / "fixtures/apis/versioned/v2.yaml")
_TODAY = date(2026, 6, 1)


def _ok(**overrides: Any) -> Suppression:
    """A suppression that qualifies, so a test can change exactly one thing."""
    fields: dict[str, Any] = {
        "rule_id": "BRK-RESP-FIELD-REMOVED",
        "operation_key": "GET /things",
        "owner": "platform-team",
        "reason": "agreed with both consumers; removal lands next release",
        "expires": (_TODAY + timedelta(days=30)).isoformat(),
    }
    fields.update(overrides)
    return Suppression(**fields)


def _finding(rule_id: str = "BRK-RESP-FIELD-REMOVED", op: str | None = "GET /things") -> Finding:
    return Finding(rule_id=rule_id, severity=Severity.ERROR, message="m", operation_key=op)


def _apply(suppression: Suppression, **kwargs: Any) -> Any:
    return apply_suppressions([_finding()], [suppression], today=_TODAY, **kwargs)


# ------------------------------------------------- what no longer suppresses


def test_the_one_line_entry_that_used_to_turn_the_gate_off() -> None:
    """`{"rule_id": "..."}` -- no owner, no reason, no expiry, no scope.

    It was the documented format's happy path: accepted, permanent, and
    silencing the rule across every operation with nobody's name on it.
    """
    result = _apply(Suppression(rule_id="BRK-RESP-FIELD-REMOVED"))
    assert result.suppressed == []
    assert [f.rule_id for f in result.active] == ["BRK-RESP-FIELD-REMOVED"]
    assert len(result.incomplete) == 1


def test_an_entry_with_no_owner_does_not_suppress() -> None:
    result = _apply(_ok(owner=""))
    assert result.suppressed == []
    assert "no `owner`" in result.incomplete[0][1][0]


def test_an_entry_with_no_reason_does_not_suppress() -> None:
    result = _apply(_ok(reason="   "))
    assert result.suppressed == []
    assert any("no `reason`" in p for p in result.incomplete[0][1])


def test_an_entry_with_no_expiry_does_not_suppress() -> None:
    result = _apply(_ok(expires=None))
    assert result.suppressed == []
    assert any("no `expires`" in p for p in result.incomplete[0][1])


def test_an_expiry_far_enough_away_is_not_an_expiry() -> None:
    """The failure mode a required-expiry rule does not catch on its own.

    `expires: 2099-01-01` satisfies "each one needs an expiry" and is a
    permanent ignore. This project's own test fixtures used exactly that date
    until the maximum existed.
    """
    result = _apply(_ok(expires="2099-01-01"))
    assert result.suppressed == []
    assert any("more than 90 days out" in p for p in result.incomplete[0][1])


def test_the_maximum_is_a_project_setting() -> None:
    far = (_TODAY + timedelta(days=200)).isoformat()
    assert _apply(_ok(expires=far)).suppressed == []
    assert len(_apply(_ok(expires=far), max_days=365).suppressed) == 1


def test_a_malformed_expiry_is_named_rather_than_called_expired() -> None:
    """`is_expired` treats an unparseable date as expired, which fails closed
    correctly and then says "expired on 'next quarter'" -- sending the reader
    to look for a date that has passed. Completeness is judged first."""
    result = _apply(_ok(expires="next quarter"))
    assert result.suppressed == []
    assert result.expired == []
    assert "not an ISO date" in result.incomplete[0][1][0]


def test_an_approver_is_required_only_when_the_project_asks() -> None:
    """Off by default on purpose: a review model is a fact about a team, and
    defaulting it on would fail every existing suppressions file on upgrade."""
    assert len(_apply(_ok()).suppressed) == 1
    assert _apply(_ok(), require_approver=True).suppressed == []
    assert len(_apply(_ok(approved_by="sre-lead"), require_approver=True).suppressed) == 1


def test_every_missing_field_is_named_at_once() -> None:
    """One pass, not one round-trip per field. Somebody is editing a JSON file
    and being told about one problem at a time is how they stop."""
    problems = _ok(owner="", reason="", expires=None).problems(_TODAY)
    assert len(problems) == 3


# ------------------------------------------------------ what still suppresses


def test_a_complete_entry_suppresses() -> None:
    result = _apply(_ok())
    assert len(result.suppressed) == 1
    assert result.active == []
    assert result.incomplete == []


def test_an_unscoped_entry_still_suppresses_and_is_reported() -> None:
    """INFO, not a refusal. Silencing a rule contract-wide is sometimes right
    -- an API with no pagination does not need the pagination rule on forty
    operations -- and is never something a reader should reconstruct."""
    result = _apply(_ok(operation_key=None))
    assert len(result.suppressed) == 1
    assert len(result.unscoped) == 1
    notes = unscoped_suppression_findings(result.unscoped)
    assert notes[0].severity is Severity.INFO
    assert "every operation" in notes[0].message


def test_an_expired_entry_is_reported_as_expired_not_as_incomplete() -> None:
    """Two different instructions to the reader: fix it and re-justify, versus
    write the field you left out."""
    result = _apply(_ok(expires="2020-01-01"))
    assert len(result.expired) == 1
    assert result.incomplete == []


# ------------------------------------------------------------- the findings


def test_the_incomplete_finding_says_which_field_and_stays_a_warning() -> None:
    """WARN because the finding this entry failed to suppress is still in the
    run at its own severity. ERROR here would fail one build twice."""
    result = _apply(_ok(owner=""))
    findings = incomplete_suppression_findings(result.incomplete)
    assert len(findings) == 1
    assert findings[0].severity is Severity.WARN
    assert findings[0].rule_id == "SUPPRESSION-INCOMPLETE"
    assert "no `owner`" in findings[0].message
    assert findings[0].operation_key == "GET /things"


def test_an_entry_with_no_rule_id_is_reported_rather_than_crashing() -> None:
    result = apply_suppressions([_finding()], [Suppression(rule_id="")], today=_TODAY)
    message = incomplete_suppression_findings(result.incomplete)[0].message
    assert "(no rule id)" in message
    assert "no `rule_id`" in message


def test_loading_never_judges() -> None:
    """A malformed entry loads. Rejecting the file here would take out the
    entries that are fine, and a suppressions file that fails to parse
    quietens nothing -- which sounds safe and is a build nobody can ship."""
    path = _ROOT / "fixtures" / "suppressions" / "unjustified.json"
    entries = load_suppressions(path)
    assert len(entries) == 4
    assert entries[0].rule_id == "BRK-RESP-FIELD-REMOVED"


def test_the_bundled_fixture_demonstrates_each_way_an_entry_fails() -> None:
    """The fixture is the documentation's worked example, so it has to stay
    one entry per failure mode."""
    entries = load_suppressions(_ROOT / "fixtures" / "suppressions" / "unjustified.json")
    result = apply_suppressions([], entries, today=_TODAY)
    reasons = [problems for _s, problems in result.incomplete]
    assert len(reasons) == 3
    joined = " ".join(p for problems in reasons for p in problems)
    assert "no `owner`" in joined
    assert "no `reason`" in joined
    assert "no `expires`" in joined
    assert "days out" in joined


# ----------------------------------------------------- through the whole CLI


def _run(argv: list[str]) -> tuple[int, dict[str, Any]]:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = main(argv)
    try:
        return code, json.loads(buffer.getvalue())
    except ValueError:
        return code, {}


def _project(tmp_path: Path, entry: dict[str, Any], **settings: Any) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "suppressions.json").write_text(
        json.dumps({"suppressions": [entry]}), encoding="utf-8"
    )
    path = tmp_path / ".apiverity.yaml"
    path.write_text(
        yaml.safe_dump({"version": 1, "suppressions": "suppressions.json", **settings}),
        encoding="utf-8",
    )
    return path


def _first_error(payload: dict[str, Any]) -> str:
    return next(f["rule_id"] for f in payload["findings"] if f["severity"] == "ERROR")


def test_an_unjustified_entry_leaves_the_run_failing(tmp_path: Path) -> None:
    """The whole point, end to end: the gate cannot be quietened by a line
    nobody signed."""
    _code, before = _run(["--no-config", "breaking", _V1, _V2, "--json"])
    rule = _first_error(before)

    config = _project(tmp_path, {"rule_id": rule})
    code, payload = _run(["--config", str(config), "breaking", _V1, _V2, "--json"])
    fired = {f["rule_id"] for f in payload["findings"]}
    assert rule in fired
    assert "SUPPRESSION-INCOMPLETE" in fired
    assert code != 0


def test_the_artifact_names_the_entry_that_did_not_apply(tmp_path: Path) -> None:
    """A count tells a reader the file is wrong. A name tells them which line
    to open."""
    _code, before = _run(["--no-config", "breaking", _V1, _V2, "--json"])
    rule = _first_error(before)

    config = _project(tmp_path, {"rule_id": rule, "owner": "me"})
    _code, payload = _run(["--config", str(config), "breaking", _V1, _V2, "--json"])
    record = payload["suppressions"]
    assert record["incomplete"] == 1
    assert record["not_applied"][0]["rule_id"] == rule
    assert any("no `reason`" in p for p in record["not_applied"][0]["problems"])


def test_the_approver_requirement_reaches_the_run(tmp_path: Path) -> None:
    _code, before = _run(["--no-config", "breaking", _V1, _V2, "--json"])
    rule = _first_error(before)
    entry = {
        "rule_id": rule,
        "owner": "platform-team",
        "reason": "agreed with both consumers",
        "expires": (date.today() + timedelta(days=30)).isoformat(),
    }

    without = _project(tmp_path / "a", entry, suppression_require_approver=True)
    _code, payload = _run(["--config", str(without), "breaking", _V1, _V2, "--json"])
    assert payload["suppressions"]["incomplete"] == 1

    with_approver = _project(
        tmp_path / "b", {**entry, "approved_by": "sre-lead"}, suppression_require_approver=True
    )
    _code, payload = _run(["--config", str(with_approver), "breaking", _V1, _V2, "--json"])
    assert payload["suppressions"]["incomplete"] == 0
    assert payload["suppressions"]["suppressed"][0]["approved_by"] == "sre-lead"


def test_the_maximum_reaches_the_run(tmp_path: Path) -> None:
    _code, before = _run(["--no-config", "breaking", _V1, _V2, "--json"])
    rule = _first_error(before)
    entry = {
        "rule_id": rule,
        "owner": "platform-team",
        "reason": "agreed with both consumers",
        "expires": (date.today() + timedelta(days=120)).isoformat(),
    }

    default = _project(tmp_path / "a", entry)
    _code, payload = _run(["--config", str(default), "breaking", _V1, _V2, "--json"])
    assert payload["suppressions"]["incomplete"] == 1

    raised = _project(tmp_path / "b", entry, suppression_max_days=180)
    _code, payload = _run(["--config", str(raised), "breaking", _V1, _V2, "--json"])
    assert payload["suppressions"]["incomplete"] == 0


def test_the_default_maximum_is_the_one_the_documentation_states() -> None:
    assert DEFAULT_MAX_LIFETIME_DAYS == 90
    assert "90" in (_ROOT / "docs" / "ci.md").read_text(encoding="utf-8")
