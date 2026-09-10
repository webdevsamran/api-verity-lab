"""The competitive table's evidence has a date, and the date has to matter.

The claim the document makes is "these were the numbers on this date", and that
claim never expires. What decays is its usefulness: a rival's star count and
last release from eighteen months ago are accurate history and a misleading
comparison, and a reader cannot tell those apart from the table.

Where the check lives is the design decision worth pinning. It is *not* in the
pull-request gate: blocking an unrelated contributor's merge because a quarter
rolled over punishes the wrong person and gets the check deleted. `ci.yml`
verifies that the committed table matches the committed data -- the part a
contributor can actually break -- and the scheduled job is what notices age.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "generate_competitive_table.py"
_DATA = _ROOT / "data" / "competitor-meta.json"
_WORKFLOW = _ROOT / ".github" / "workflows" / "competitor-refresh.yml"

sys.path.insert(0, str(_ROOT / "scripts"))

from generate_competitive_table import (  # noqa: E402
    DEFAULT_MAX_AGE_DAYS,
    evidence_age_days,
    fetch_date,
    freshness_message,
)


def _meta(days_ago: int) -> dict[str, object]:
    stamp = datetime.now(UTC) - timedelta(days=days_ago)
    return {"fetched_utc": stamp.isoformat(), "tool": "test", "repos": {}}


# ------------------------------------------------------------------- the age


def test_the_age_is_measured_from_the_recorded_fetch_date() -> None:
    assert evidence_age_days(_meta(0)) == 0
    assert evidence_age_days(_meta(100)) == 100


def test_the_age_is_computed_against_a_supplied_day() -> None:
    """`date.today()` in a test is a test that fails on one day of the year."""
    meta = {"fetched_utc": "2026-01-01T00:00:00+00:00"}
    assert evidence_age_days(meta, today=date(2026, 4, 2)) == 91


def test_the_refresh_interval_is_about_a_quarter() -> None:
    assert 80 <= DEFAULT_MAX_AGE_DAYS <= 100


def test_the_message_names_the_date_and_the_command_to_run() -> None:
    """A warning that does not say what to do is one people learn to scroll past."""
    message = freshness_message(_meta(200), DEFAULT_MAX_AGE_DAYS)
    assert "fetch_competitor_meta.py" in message
    assert "generate_competitive_table.py" in message
    assert str(DEFAULT_MAX_AGE_DAYS) in message


def test_data_with_no_usable_stamp_is_refused() -> None:
    """Not treated as fresh. Missing evidence of age is not evidence of youth."""
    from generate_competitive_table import RenderError

    with pytest.raises(RenderError):
        fetch_date({"repos": {}})


# ------------------------------------------------------ the committed data


def test_the_committed_evidence_carries_a_date() -> None:
    meta = json.loads(_DATA.read_text(encoding="utf-8"))
    assert fetch_date(meta)
    assert evidence_age_days(meta) >= 0, "evidence gathered in the future is a clock problem"


# --------------------------------------------------------------- the gates


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=_ROOT,
    )


def test_the_default_check_does_not_fail_on_age() -> None:
    """The pull-request gate. It must not go red because time passed."""
    result = _run("--check")
    assert result.returncode == 0, result.stderr


def test_an_explicit_age_limit_can_fail() -> None:
    """The scheduled job's gate, exercised rather than assumed."""
    result = _run("--check", "--max-age-days", "0")
    assert result.returncode == 1
    assert "fetch_competitor_meta.py" in result.stderr


def test_the_check_reports_the_age_it_found() -> None:
    """A number nobody prints is a number nobody notices."""
    result = _run("--check")
    assert "gathered" in result.stdout
    assert "d old" in result.stdout


# ------------------------------------------------------------ the schedule


def test_a_scheduled_job_exists_to_do_the_refreshing() -> None:
    """Otherwise the interval is a number in a docstring."""
    workflow = yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))
    triggers = workflow.get("on") or workflow.get(True)
    assert "schedule" in triggers
    assert triggers["schedule"], "a schedule block with no cron entry runs never"


def test_the_scheduled_job_opens_a_pull_request_rather_than_pushing() -> None:
    """This table is a claim this project makes about other people's projects.

    A number nobody read is the one that turns out to be wrong, so the refresh
    lands where a person has to look at it.
    """
    text = _WORKFLOW.read_text(encoding="utf-8")
    assert "gh pr create" in text
    assert "git push --set-upstream origin" in text
    assert "git push origin main" not in text


def test_the_fetch_step_does_not_swallow_its_own_failure() -> None:
    """A half-fetched file publishes "this competitor has no releases" when the
    truth is that we could not ask."""
    workflow = yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))
    fetch = next(
        step
        for step in workflow["jobs"]["refresh"]["steps"]
        if step.get("name") == "Fetch live metadata"
    )
    body = fetch["run"]
    assert "set -euo pipefail" in body
    assert "fetch_competitor_meta.py || true" not in body
