"""Re-run a command when the files it reads change.

The loop is trivial. Three things around it are not, and each is the reason
this is a module rather than eight lines in `main.py`.

**What to watch is the command's own arguments.** `apiverity watch -- breaking
old.yaml new.yaml` watches `old.yaml` and `new.yaml` because those are the
paths that command names. A separate `--watch` vocabulary would let the two
drift, and the failure mode is silent: you edit a file, nothing re-runs, and
the last output on screen is stale but looks current.

**An editor does not write a file once.** A save is often truncate-then-write,
and a poll landing between the two reads an empty document -- so a naive
watcher reports a parse error that is gone by the time you look. Changes are
allowed to *settle*: after one is seen, the loop waits until two consecutive
snapshots agree before running anything.

**Process state does not reset itself.** Running N commands in one process is
the arrangement `apiverity/mcp/tools.py` documents at length: the CLI keeps
provenance in module globals set as a side effect of loading a spec, so a run
that fails before the load would stamp its artifact with the *previous* run's
spec path. The loop clears them between iterations.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

#: Extensions a contract is written in. Used only when a *directory* is
#: watched: naming a file watches it whatever it is called.
SPEC_SUFFIXES = frozenset(
    {".yaml", ".yml", ".json", ".proto", ".graphql", ".graphqls", ".gql", ".wsdl", ".xml"}
)

#: How often to look, in seconds. Fast enough to feel immediate, slow enough
#: that a directory of a few hundred files costs nothing measurable.
DEFAULT_INTERVAL = 0.4

#: How long a change has to stop changing before the command runs.
DEFAULT_SETTLE = 0.15

#: A directory is walked, and a repository root is a directory somebody will
#: eventually point this at by mistake. Capped, and the cap is *reported*
#: rather than applied quietly -- a watcher silently ignoring the file you are
#: editing is worse than one that refuses.
MAX_WATCHED_FILES = 500

#: `.git` in a watched tree changes on every command anybody runs elsewhere.
IGNORED_DIRECTORIES = frozenset(
    {".git", ".venv", "venv", "node_modules", "__pycache__", ".mypy_cache", ".ruff_cache", "dist"}
)

#: Missing, rather than an mtime. A file that does not exist yet is a normal
#: state -- you are about to create it -- and `-1.0` would sort as "very old"
#: instead of "absent".
MISSING = -1.0


@dataclass(frozen=True)
class Change:
    path: Path
    kind: str  # "created" | "modified" | "deleted"

    def __str__(self) -> str:
        return f"{self.kind} {self.path}"


@dataclass
class WatchSummary:
    """What the loop did, for the line printed when it stops."""

    runs: int = 0
    last_exit_code: int | None = None
    watched: list[Path] = field(default_factory=list)
    #: Files a directory walk found beyond `MAX_WATCHED_FILES`. Named so the
    #: cap is visible rather than inferred from a watcher that does nothing.
    skipped: int = 0


def expand(
    paths: Iterable[str | Path], *, limit: int = MAX_WATCHED_FILES
) -> tuple[list[Path], int]:
    """Turn the arguments into a concrete file list, plus how many were dropped.

    A named file is watched whatever its extension: the caller said that file.
    A named directory is walked, and only spec-shaped files in it are taken --
    otherwise pointing at a repository means re-running on every `.pyc`.
    """
    found: list[Path] = []
    skipped = 0
    seen: set[Path] = set()

    def take(path: Path) -> None:
        nonlocal skipped
        resolved = path.resolve()
        if resolved in seen:
            return
        seen.add(resolved)
        if len(found) >= limit:
            skipped += 1
            return
        found.append(resolved)

    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            for child in sorted(path.rglob("*")):
                if not child.is_file():
                    continue
                if any(part in IGNORED_DIRECTORIES for part in child.parts):
                    continue
                if child.suffix.lower() in SPEC_SUFFIXES:
                    take(child)
        else:
            # Taken even when absent: watching a file into existence is the
            # normal way to use this while writing one.
            take(path)
    return found, skipped


def snapshot(paths: Sequence[Path]) -> dict[Path, float]:
    """Modification time per path, `MISSING` for one that is not there."""
    out: dict[Path, float] = {}
    for path in paths:
        try:
            out[path] = path.stat().st_mtime
        except OSError:
            out[path] = MISSING
    return out


def diff(before: dict[Path, float], after: dict[Path, float]) -> list[Change]:
    changes: list[Change] = []
    for path, mtime in after.items():
        was = before.get(path, MISSING)
        if was == mtime:
            continue
        if was == MISSING:
            changes.append(Change(path, "created"))
        elif mtime == MISSING:
            changes.append(Change(path, "deleted"))
        else:
            changes.append(Change(path, "modified"))
    return sorted(changes, key=lambda c: str(c.path))


def watch(
    paths: Sequence[Path],
    run: Callable[[], int],
    *,
    interval: float = DEFAULT_INTERVAL,
    settle: float = DEFAULT_SETTLE,
    should_continue: Callable[[WatchSummary], bool] = lambda _summary: True,
    on_change: Callable[[list[Change]], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    reset: Callable[[], None] | None = None,
) -> WatchSummary:
    """Run once, then again each time a watched file settles after a change.

    `should_continue` is the loop condition and is injected rather than being
    `while True`: a loop with no exit is a loop no test can enter. The CLI
    passes one that never stops.

    `sleep` is injected for the same reason -- a test that really waited would
    be a test that takes seconds to say nothing.
    """
    summary = WatchSummary(watched=list(paths))
    summary.last_exit_code = run()
    summary.runs += 1

    state = snapshot(paths)
    while should_continue(summary):
        sleep(interval)
        current = snapshot(paths)
        changes = diff(state, current)
        if not changes:
            continue

        # An editor writing a file is often a truncate followed by a write, and
        # a poll that lands between the two reads an empty document. Wait for
        # two consecutive snapshots to agree before believing either.
        while True:
            sleep(settle)
            settled = snapshot(paths)
            if settled == current:
                break
            current = settled
            changes = diff(state, current)

        state = current
        if on_change is not None:
            on_change(changes)
        if reset is not None:
            reset()
        summary.last_exit_code = run()
        summary.runs += 1
    return summary


__all__ = [
    "DEFAULT_INTERVAL",
    "DEFAULT_SETTLE",
    "IGNORED_DIRECTORIES",
    "MAX_WATCHED_FILES",
    "MISSING",
    "SPEC_SUFFIXES",
    "Change",
    "WatchSummary",
    "diff",
    "expand",
    "snapshot",
    "watch",
]
