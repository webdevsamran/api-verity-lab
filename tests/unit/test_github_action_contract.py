"""The published GitHub Action must exist, and its inputs must do something.

README.md advertised "GitHub Action (included)". What existed was
`.github/workflows/api-verity.yml`, a reusable *workflow*. Those are not
interchangeable: a reusable workflow is consumed as a whole job
(`uses:` at job level), an action as a step inside a job the caller owns. A
reader who followed the README with the syntax it implies got
"Can't find 'action.yml'".

Both exist now. These tests hold the action to the standard the rest of the
repository is held to: every advertised input reaches something real, and the
one input that cannot be expressed in exit codes is backed by the artifacts
instead of quietly ignored.

`fail-on` is that input. `apiverity breaking` returns EXIT_FINDINGS only when
there is at least one ERROR finding, so a gate built on exit codes can express
`error` and `never` and nothing else -- `fail-on: warn` would have been an
input that silently does nothing. `scripts/count_findings.py` reads severities
out of the emitted `result-v1` artifacts, which is where that information
actually lives.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

_ROOT = Path(__file__).resolve().parent.parent.parent
_ACTION = _ROOT / "action.yml"


def _counter() -> Any:
    """Import scripts/count_findings.py, which is not an importable package."""
    path = _ROOT / "scripts" / "count_findings.py"
    spec = importlib.util.spec_from_file_location("count_findings", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _action() -> dict:
    return yaml.safe_load(_ACTION.read_text(encoding="utf-8"))


def _artifact(tmp_path: Path, name: str, severities: list[str]) -> None:
    payload = {
        "tool": "apiverity",
        "command": "breaking",
        "findings": [{"rule_id": f"BRK-X-{i}", "severity": s} for i, s in enumerate(severities)],
    }
    (tmp_path / name).write_text(json.dumps(payload), encoding="utf-8")


def test_the_action_exists_and_is_a_composite_action() -> None:
    assert _ACTION.is_file(), (
        "README advertises a GitHub Action; `uses: webdevsamran/api-verity-lab@v1` "
        "resolves to action.yml at the repository root"
    )
    action = _action()
    assert action["runs"]["using"] == "composite"


def test_every_run_step_declares_a_shell() -> None:
    """A composite `run:` step without `shell:` fails at use time, not at lint time."""
    missing = [
        step.get("name", "<unnamed>")
        for step in _action()["runs"]["steps"]
        if "run" in step and not step.get("shell")
    ]
    assert not missing, f"composite run steps with no shell: {missing}"


def test_the_action_installs_the_revision_the_caller_pinned() -> None:
    """`install-from: action` must not silently reach for PyPI.

    The distribution is not published yet, so an action defaulting to
    `pip install api-verity-lab` would be broken for every consumer on day one
    -- while looking, in the YAML, exactly like one that works.
    """
    action = _action()
    assert action["inputs"]["install-from"]["default"] == "action"
    install = next(s for s in action["runs"]["steps"] if s.get("name") == "Install apiverity")
    assert "github.action_path" in json.dumps(install), (
        "the default install path must use github.action_path, so the tool and the "
        "action are the same revision by construction"
    )


def test_declared_outputs_are_all_produced_by_a_step_that_writes_them() -> None:
    """An output is a promise, and YAML will not check it.

    Every declared output must name a step that exists and must map to a key
    that step actually writes to `$GITHUB_OUTPUT`. Nothing else catches a
    renamed step or a typo -- the action still parses, still runs, and hands
    the consumer an empty string.
    """
    action = _action()
    scripts = {step["id"]: step["run"] for step in action["runs"]["steps"] if step.get("id")}
    for name, spec in action["outputs"].items():
        value = spec["value"]
        assert "steps." in value, f"output {name} does not come from a step"
        step_id = value.split("steps.")[1].split(".outputs.")[0].strip()
        assert step_id in scripts, f"output {name!r} names step {step_id!r}, which does not exist"
        key = value.split(".outputs.")[1].split("}")[0].strip()
        assert f"{key}=" in scripts[step_id], (
            f"output {name!r} maps to `{key}`, which step {step_id!r} never writes to "
            "$GITHUB_OUTPUT"
        )


@pytest.mark.parametrize(
    ("fail_on", "expected"),
    [("error", 2), ("warn", 3), ("never", 0)],
)
def test_fail_on_thresholds_count_different_things(
    tmp_path: Path, fail_on: str, expected: int
) -> None:
    """The input is real: each level selects a different set of findings."""
    _artifact(tmp_path, "a.json", ["ERROR", "WARN", "INFO"])
    _artifact(tmp_path, "b.json", ["ERROR"])
    at_or_above, errors, warns = _counter().count(tmp_path, fail_on)
    assert (errors, warns) == (2, 1)
    assert at_or_above == expected


def test_never_reports_findings_without_selecting_any(tmp_path: Path) -> None:
    """`never` must still count, so a report can be published without a failure."""
    _artifact(tmp_path, "a.json", ["ERROR", "ERROR", "WARN"])
    at_or_above, errors, warns = _counter().count(tmp_path, "never")
    assert at_or_above == 0
    assert (errors, warns) == (2, 1)


def test_a_malformed_artifact_fails_rather_than_reporting_zero(tmp_path: Path) -> None:
    """The gate must not read a broken artifact as a clean bill of health."""
    (tmp_path / "broken.json").write_text("{ not json", encoding="utf-8")
    with pytest.raises(SystemExit):
        _counter().count(tmp_path, "error")


def test_an_unknown_severity_never_trips_the_gate_on_its_own(tmp_path: Path) -> None:
    """Ranking a word we do not know would assert what the artifact did not establish."""
    _artifact(tmp_path, "a.json", ["CATASTROPHIC"])
    at_or_above, errors, warns = _counter().count(tmp_path, "error")
    assert (at_or_above, errors, warns) == (0, 0, 0)


def test_an_unknown_fail_on_level_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        _counter().count(tmp_path, "sometimes")


def test_no_findings_is_distinct_from_no_artifacts(tmp_path: Path) -> None:
    """Both count zero, but the gate reports `specs_checked` separately.

    A gate that says "pass" having examined nothing is how a wrong `spec-dirs`
    goes unnoticed, so the action emits the count and a notice as well.
    """
    assert _counter().count(tmp_path, "error") == (0, 0, 0)
    gate = next(s for s in _action()["runs"]["steps"] if s.get("id") == "gate")
    assert "specs_checked=" in gate["run"]
    assert "nothing to check" in gate["run"]
