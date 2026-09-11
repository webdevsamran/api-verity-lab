"""The names branch protection matches, and the event it has to match on.

Two failures here are silent and expensive, which is why they are pinned.

**A renamed job.** Branch protection stores required checks as strings and
matches them byte for byte. Rename `python` to `lint-and-test` and the required
check called `python` never reports — the pull request waits forever, or, if
the requirement was dropped instead, merges with nothing having run.

**A gate that only runs on `pull_request`.** It proves nothing about the merge
*result*. Two pull requests that are individually safe can combine into a
breaking change — one removes a field's last declared consumer, the other
removes the field — and the merge queue is the only place that combination is
ever built.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOWS = _ROOT / ".github/workflows"

#: The job names branch protection is configured with. Changing one of these
#: is changing a string somebody typed into a settings page, so it is a
#: deliberate act with a migration, not a rename.
REQUIRED_JOBS = {"python", "platform-matrix", "schema-validation", "frontend", "sbom"}

#: Workflows that gate a merge, and therefore have to run where merges happen.
GATING = ("ci.yml", "api-verity.yml")


def _workflow(name: str) -> dict:
    # `on:` is parsed by PyYAML as the boolean True -- YAML 1.1 again -- so the
    # key is read back both ways rather than by name alone.
    return yaml.safe_load((_WORKFLOWS / name).read_text(encoding="utf-8"))


def _triggers(document: dict) -> dict:
    for key in ("on", True):
        if key in document:
            return document[key] or {}
    raise AssertionError("the workflow declares no triggers")


def test_the_required_job_names_have_not_moved() -> None:
    """Branch protection matches these byte for byte."""
    jobs = set(_workflow("ci.yml")["jobs"])
    missing = REQUIRED_JOBS - jobs
    assert not missing, (
        f"{sorted(missing)} are required checks in branch protection and no longer exist "
        "in ci.yml. A pull request will wait for them forever."
    )


def test_a_new_job_is_noticed_rather_than_assumed_required() -> None:
    """The other direction. A job added to ci.yml is not automatically a
    required check, and whoever adds one should decide which it is."""
    jobs = set(_workflow("ci.yml")["jobs"])
    unlisted = jobs - REQUIRED_JOBS
    assert not unlisted, (
        f"{sorted(unlisted)} exist in ci.yml and are not in REQUIRED_JOBS. Add them to "
        "branch protection and to this list, or record here that they are advisory."
    )


@pytest.mark.parametrize("name", GATING)
def test_a_gating_workflow_runs_in_the_merge_queue(name: str) -> None:
    """Otherwise a passing pull request says nothing about what merges."""
    triggers = _triggers(_workflow(name))
    assert "merge_group" in triggers, (
        f"{name} gates a merge and does not run on `merge_group`. Enqueue two pull "
        "requests that are individually safe and combine into a breaking change, and "
        "nothing checks the combination."
    )


@pytest.mark.parametrize("name", GATING)
def test_a_gating_workflow_still_runs_on_pull_requests(name: str) -> None:
    """The merge queue is the last gate, not the first. Finding out at merge
    time is finding out after review."""
    assert "pull_request" in _triggers(_workflow(name))


def test_the_action_can_find_a_base_ref_in_a_merge_queue() -> None:
    """`github.base_ref` is empty for a `merge_group` event -- it is not a pull
    request. Without a fallback the action reached its "no base ref" branch and
    exited 1, so it could not be a required check in a merge queue at all."""
    action = (_ROOT / "action.yml").read_text(encoding="utf-8")
    assert "github.event.merge_group.base_ref" in action
    # And the ref arrives as `refs/heads/main`, while everything downstream
    # builds `origin/$BASE`.
    assert "refs/heads/" in action


def test_the_action_still_refuses_when_there_is_no_base_at_all() -> None:
    """A gate that cannot find a base and proceeds anyway is a gate that
    passes."""
    action = (_ROOT / "action.yml").read_text(encoding="utf-8")
    assert "no spec-paths given and no base ref to diff against" in action


def test_the_comment_step_is_still_scoped_to_pull_requests() -> None:
    """There is no pull request to comment on in a merge-queue run, and a step
    that tried would fail the gate for a reason that has nothing to do with the
    contract."""
    action = (_ROOT / "action.yml").read_text(encoding="utf-8")
    assert "github.event_name == 'pull_request'" in action
