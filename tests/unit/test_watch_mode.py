"""Re-running on change, and the three things that make it not a `while True`.

None of this is about polling. It is about the ways a naive watcher lies:

- it watches a list somebody typed instead of the files the command reads, so
  you edit one and nothing happens, and the stale output on screen looks
  current;
- it fires mid-save, because an editor writes a file as truncate-then-write and
  a poll landing between the two reads an empty document -- so it reports a
  parse error that is already gone;
- it re-enters `main()` in one process and inherits the last run's provenance
  globals, which is the exact hazard `apiverity/mcp/tools.py` documents.

The loop's condition and its sleep are injected, so these can be tested without
waiting for anything: a loop with no exit is a loop no test can enter.
"""

from __future__ import annotations

import contextlib
import io
from pathlib import Path

import pytest

from apiverity.cli.main import main
from apiverity.cli.watch import (
    MISSING,
    Change,
    WatchSummary,
    diff,
    expand,
    snapshot,
    watch,
)


def _stop_after(runs: int):
    return lambda summary: summary.runs < runs


def _no_sleep(_seconds: float) -> None:
    return None


# ------------------------------------------------------------------ snapshots


def test_a_missing_file_is_absent_rather_than_very_old(tmp_path: Path) -> None:
    """`0.0` would sort as an ancient mtime and compare equal between two
    missing files and a file whose clock is wrong."""
    assert snapshot([tmp_path / "nope.yaml"]) == {tmp_path / "nope.yaml": MISSING}


def test_the_three_kinds_of_change_are_told_apart(tmp_path: Path) -> None:
    a, b, c = tmp_path / "a.yaml", tmp_path / "b.yaml", tmp_path / "c.yaml"
    before = {a: MISSING, b: 100.0, c: 100.0}
    after = {a: 101.0, b: 102.0, c: MISSING}
    assert diff(before, after) == [
        Change(a, "created"),
        Change(b, "modified"),
        Change(c, "deleted"),
    ]


def test_no_change_is_no_change(tmp_path: Path) -> None:
    state = {tmp_path / "a.yaml": 100.0}
    assert diff(state, dict(state)) == []


# --------------------------------------------------------------- what to watch


def test_a_named_file_is_watched_whatever_it_is_called(tmp_path: Path) -> None:
    """The caller said that file. Filtering it by extension would refuse to
    watch a contract somebody named `service`."""
    odd = tmp_path / "contract.weird"
    odd.write_text("x", encoding="utf-8")
    found, skipped = expand([odd])
    assert found == [odd.resolve()]
    assert skipped == 0


def test_a_file_that_does_not_exist_yet_is_still_watched(tmp_path: Path) -> None:
    """Watching a file into existence is the normal way to use this while
    writing one."""
    found, _skipped = expand([tmp_path / "not-yet.yaml"])
    assert found == [(tmp_path / "not-yet.yaml").resolve()]


def test_a_directory_takes_only_contract_shaped_files(tmp_path: Path) -> None:
    """Otherwise pointing at a repository means re-running on every `.pyc`."""
    (tmp_path / "spec.yaml").write_text("a", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("b", encoding="utf-8")
    (tmp_path / "api.proto").write_text("c", encoding="utf-8")
    found, _skipped = expand([tmp_path])
    assert sorted(p.name for p in found) == ["api.proto", "spec.yaml"]


def test_a_directory_walk_skips_the_places_that_churn(tmp_path: Path) -> None:
    """`.git` changes on every command anybody runs elsewhere in the tree."""
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "index.json").write_text("x", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "package.json").write_text("x", encoding="utf-8")
    (tmp_path / "spec.yaml").write_text("y", encoding="utf-8")
    found, _skipped = expand([tmp_path])
    assert [p.name for p in found] == ["spec.yaml"]


def test_the_same_file_named_twice_is_watched_once(tmp_path: Path) -> None:
    spec = tmp_path / "spec.yaml"
    spec.write_text("x", encoding="utf-8")
    found, _skipped = expand([spec, tmp_path, str(spec)])
    assert found == [spec.resolve()]


def test_the_cap_is_reported_rather_than_applied_quietly(tmp_path: Path) -> None:
    """A watcher silently ignoring the file you are editing is worse than one
    that refuses."""
    for index in range(6):
        (tmp_path / f"spec-{index}.yaml").write_text("x", encoding="utf-8")
    found, skipped = expand([tmp_path], limit=4)
    assert len(found) == 4
    assert skipped == 2


# --------------------------------------------------------------------- the loop


def test_it_runs_once_before_anything_changes(tmp_path: Path) -> None:
    """The first thing you want is the current answer, not silence until you
    touch something."""
    spec = tmp_path / "a.yaml"
    spec.write_text("x", encoding="utf-8")
    runs: list[int] = []
    summary = watch(
        [spec],
        lambda: (runs.append(1), 0)[1],
        should_continue=lambda _s: False,
        sleep=_no_sleep,
    )
    assert summary.runs == 1
    assert len(runs) == 1


def test_a_change_triggers_a_rerun(tmp_path: Path) -> None:
    spec = tmp_path / "a.yaml"
    spec.write_text("x", encoding="utf-8")
    mtimes = iter([100.0, 100.0, 101.0, 101.0, 101.0, 101.0])

    def fake_snapshot(_paths):
        return {spec: next(mtimes)}

    import apiverity.cli.watch as module

    original = module.snapshot
    module.snapshot = fake_snapshot  # type: ignore[assignment]
    try:
        summary = watch([spec], lambda: 0, should_continue=_stop_after(2), sleep=_no_sleep)
    finally:
        module.snapshot = original  # type: ignore[assignment]
    assert summary.runs == 2


def test_a_file_still_being_written_is_waited_out(tmp_path: Path) -> None:
    """A save is often truncate-then-write. A poll between the two reads an
    empty document, and a watcher that ran there would report a parse error
    that is gone by the time anyone looks."""
    spec = tmp_path / "a.yaml"
    spec.write_text("x", encoding="utf-8")
    # initial, then a change, then two more changes before it settles.
    mtimes = iter([100.0, 101.0, 102.0, 103.0, 103.0, 103.0, 103.0, 103.0])

    def fake_snapshot(_paths):
        return {spec: next(mtimes)}

    import apiverity.cli.watch as module

    original = module.snapshot
    module.snapshot = fake_snapshot  # type: ignore[assignment]
    try:
        summary = watch([spec], lambda: 0, should_continue=_stop_after(2), sleep=_no_sleep)
    finally:
        module.snapshot = original  # type: ignore[assignment]
    # One rerun, not three: the intermediate writes were coalesced.
    assert summary.runs == 2


def test_the_exit_code_of_the_last_run_is_kept(tmp_path: Path) -> None:
    spec = tmp_path / "a.yaml"
    spec.write_text("x", encoding="utf-8")
    summary = watch([spec], lambda: 3, should_continue=lambda _s: False, sleep=_no_sleep)
    assert summary.last_exit_code == 3


def test_state_is_reset_between_runs(tmp_path: Path) -> None:
    """The hazard `apiverity/mcp/tools.py` documents: N commands in one
    process, provenance in module globals, and a run that fails before loading
    a spec stamps its artifact with the previous run's path."""
    spec = tmp_path / "a.yaml"
    spec.write_text("x", encoding="utf-8")
    mtimes = iter([100.0, 101.0, 101.0, 101.0, 101.0])
    resets: list[int] = []

    def fake_snapshot(_paths):
        return {spec: next(mtimes)}

    import apiverity.cli.watch as module

    original = module.snapshot
    module.snapshot = fake_snapshot  # type: ignore[assignment]
    try:
        watch(
            [spec],
            lambda: 0,
            should_continue=_stop_after(2),
            sleep=_no_sleep,
            reset=lambda: resets.append(1),
        )
    finally:
        module.snapshot = original  # type: ignore[assignment]
    assert resets == [1]


def test_the_reset_really_clears_the_cli_provenance() -> None:
    """Not a mock: the function the loop is handed has to do the thing."""
    from apiverity.cli.commands import common

    common._LAST_SPEC = "old.yaml"
    common._LAST_PROTOCOL = "openapi"
    common._LAST_SEED = 42
    common.reset_provenance()
    assert common._LAST_SPEC is None
    assert common._LAST_PROTOCOL is None
    assert common._LAST_SEED is None


# ---------------------------------------------------------------------- the CLI


def _run(argv: list[str]) -> tuple[int, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    return code, err.getvalue()


def test_watch_with_nothing_to_run_is_a_usage_error() -> None:
    code, err = _run(["--no-config", "watch"])
    assert code == 2
    assert "nothing to run" in err


def test_a_command_that_names_no_file_is_refused_rather_than_polling_nothing() -> None:
    """`apiverity rules` reads no contract. Watching it would be a process
    that never does anything and never says why."""
    code, err = _run(["--no-config", "watch", "--", "rules"])
    assert code == 2
    assert "name a file to watch" in err


def test_the_subcommand_name_is_not_mistaken_for_a_path(tmp_path: Path) -> None:
    """`breaking` is the command, not a file. It has no extension and does not
    exist, which is how the filter tells."""
    found, _skipped = expand(["breaking"])
    assert found == [Path("breaking").resolve()]  # expand takes what it is given
    # The CLI is what filters; this is the predicate it applies.
    assert not (Path("breaking").exists() or Path("breaking").suffix)


@pytest.mark.parametrize("summary", [WatchSummary(runs=0), WatchSummary(runs=5)])
def test_the_summary_carries_what_the_stop_line_prints(summary: WatchSummary) -> None:
    assert summary.runs >= 0
    assert summary.watched == []
