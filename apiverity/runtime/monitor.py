"""Run a check on a schedule and report what *changed*, not what is.

A cron entry that runs `apiverity drift` every five minutes and posts the
result produces two hundred and eighty-eight identical reports a day. People
mute it inside a week, and the run that finally differs arrives in a muted
channel. Synthetic monitoring is only useful if it says *"this is new"*.

So this keeps the previous run's finding set in a state file and reports
transitions: **appeared**, **resolved**, and everything that persisted. What
goes to a channel is the first two.

## The failure that makes a naive differ dangerous

An operation that could not be probed produces no findings about that
operation. Differenced against a previous run that had three, that reads as
*three findings resolved* -- the single most misleading thing a monitor can
say, because it is the shape of good news and it arrives at exactly the moment
the service stopped answering.

`apiverity drift` and `apiverity ghosts` already say this per operation, in
the finding itself: `GHOST-UNREACHABLE` reads "this run establishes nothing
about whether it is still served". :data:`UNOBSERVABLE_RULES` is that same
sentence made machine-readable, so the differ can act on it.

The consequence is partitioned rather than all-or-nothing. One flaky endpoint
out of forty should not silence a monitor, and forty out of forty must not
read as forty fixes:

* an operation named by an unobservable finding is **carried forward** --
  whatever was known about it stays known, and nothing about it is called
  resolved;
* every other operation is differenced normally;
* a run that measured *nothing* is `inconclusive`, and says so -- and that
  is read from the count the command itself reports (`operations_checked`,
  `probed`), never guessed from the findings. "Every finding is an unreachable
  one" is the shape of a healthy API with one dead endpoint as much as it is
  the shape of an outage, and the two must not be conflated.

## What counts as the same finding

`(rule_id, operation_key)`. A message carries values that move between runs --
a p95, a sample count, an observed status -- and keying on the message would
make every run report the whole set as resolved-and-reappeared.

That, too, has a consequence stated rather than hidden: a finding whose
*message* changed while its rule and operation stayed the same is not a
transition. It is in `persisted`, with the latest message, and
`message_changed` counts them so a report can say so.

## Flapping

A finding that appears and resolves on alternate runs is one alert every five
minutes in both directions. `flaps` counts how many times each key has
crossed, carried in the state file, so a report can name the unstable ones
instead of paging about each crossing. Nothing here suppresses an alert on its
own -- that is a policy decision, and the count is what makes it possible to
take one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: Version of the state file's shape. A monitor that silently misread an older
#: state would report the whole world as new, which is the alert nobody wants.
STATE_VERSION = 1

#: Keys under which a command reports how many things it actually measured.
#: A run with none measured and something unreachable is an outage; a run with
#: none measured and nothing to measure is just an empty run.
MEASURED_KEYS = ("operations_checked", "probed")

#: Rules that report a failure to observe rather than something observed. A
#: finding carrying one of these means its operation was not measured on this
#: run, so nothing about that operation may be called resolved.
#:
#: Listed rather than inferred from the rule id, because "UNREACHABLE" in a
#: name is a convention and a convention is not a contract. A test walks every
#: rule id the package emits and fails when one matches the convention and is
#: missing here, which is what keeps this bound to the code rather than
#: drifting from it.
UNOBSERVABLE_RULES = frozenset({"DRIFT-UNREACHABLE", "GHOST-UNREACHABLE"})


def finding_key(finding: dict[str, Any]) -> str:
    """What makes two findings across two runs the same finding.

    Not the message: it carries a p95, a sample count or an observed status,
    and keying on it would report every run as a full turnover.
    """
    rule = str(finding.get("rule_id") or "")
    operation = finding.get("operation_key")
    return f"{rule}\t{operation}" if operation else rule


def measured_count(artifact: dict[str, Any]) -> int | None:
    """How many things the run says it measured, or None when it does not say.

    Looked for at the top level and inside `report`, which is where the
    runtime commands put their own summary. A command that reports no count
    gets no outage detection rather than a guessed one.
    """
    for scope in (artifact, artifact.get("report") or {}):
        if not isinstance(scope, dict):
            continue
        for key in MEASURED_KEYS:
            value = scope.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                return value
    return None


def unobserved_operations(findings: list[dict[str, Any]]) -> set[str]:
    """The operations this run failed to measure, read out of its own findings."""
    return {
        str(finding["operation_key"])
        for finding in findings
        if finding.get("rule_id") in UNOBSERVABLE_RULES and finding.get("operation_key")
    }


@dataclass
class MonitorState:
    """What the previous runs established, and how unstable each finding is."""

    #: key -> the finding as last seen.
    findings: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: key -> how many times it has crossed between present and absent.
    flaps: dict[str, int] = field(default_factory=dict)
    #: How many runs have contributed to this state. Zero means the next run
    #: records a baseline, which is the difference between "twelve new
    #: findings" and "twelve findings, and this is the first time anybody
    #: looked".
    runs: int = 0
    #: The command this state describes. Two different commands sharing one
    #: state file report each other's findings as a full turnover: every
    #: finding resolved and every finding new, on every alternate run.
    target: str | None = None

    @classmethod
    def load(cls, path: str | Path) -> MonitorState:
        """Read a state file, or start empty when there is none.

        A missing file is the normal first run, not an error. A malformed one
        is an error: silently starting over would alert on every existing
        finding as though it were new.
        """
        source = Path(path)
        if not source.exists():
            return cls()
        raw = json.loads(source.read_text(encoding="utf-8"))
        version = raw.get("state_version")
        if version != STATE_VERSION:
            raise ValueError(
                f"{source} was written by state version {version!r}; this build writes "
                f"{STATE_VERSION}. Delete it to start a new baseline -- the next run "
                "will then record the current findings as a baseline rather than alert "
                "on them as new."
            )
        return cls(
            findings={str(k): v for k, v in (raw.get("findings") or {}).items()},
            flaps={str(k): int(v) for k, v in (raw.get("flaps") or {}).items()},
            runs=int(raw.get("runs") or 0),
            target=raw.get("target"),
        )

    def save(self, path: str | Path) -> None:
        destination = Path(path)
        if str(destination.parent) not in ("", "."):
            destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(
                {
                    "state_version": STATE_VERSION,
                    "target": self.target,
                    "runs": self.runs,
                    "findings": self.findings,
                    "flaps": self.flaps,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )


@dataclass
class Transitions:
    """What one run changed against the run before it."""

    appeared: list[dict[str, Any]] = field(default_factory=list)
    resolved: list[dict[str, Any]] = field(default_factory=list)
    persisted: list[dict[str, Any]] = field(default_factory=list)
    #: Findings carried forward because their operation was not measured. Not
    #: resolved, not re-confirmed: last known, and labelled as such.
    carried: list[dict[str, Any]] = field(default_factory=list)
    #: Operations this run could not measure.
    unobserved: list[str] = field(default_factory=list)
    #: Persisted findings whose message changed. Counted, not reported as a
    #: transition: see the module docstring.
    message_changed: int = 0
    #: True when this run recorded the baseline rather than compared to one.
    baseline: bool = False
    #: Set when the run established nothing at all. The previous state is
    #: carried forward whole and nothing is called resolved.
    inconclusive: str | None = None
    #: key -> crossings so far, for the keys this run moved.
    flaps: dict[str, int] = field(default_factory=dict)

    @property
    def alerting(self) -> bool:
        """Whether a report of this run is worth sending anywhere."""
        if self.inconclusive:
            return True
        return bool(self.appeared or self.resolved)

    def summary(self) -> str:
        if self.inconclusive:
            return f"inconclusive: {self.inconclusive}"
        if self.baseline:
            return (
                f"baseline recorded: {len(self.persisted)} finding(s) known, none reported as new"
            )
        parts = [f"{len(self.appeared)} appeared", f"{len(self.resolved)} resolved"]
        if self.message_changed:
            parts.append(f"{self.message_changed} changed message only")
        parts.append(f"{len(self.persisted)} unchanged")
        if self.unobserved:
            parts.append(
                f"{len(self.unobserved)} operation(s) not measured, "
                f"{len(self.carried)} finding(s) carried forward"
            )
        return ", ".join(parts)


def apply_run(
    state: MonitorState,
    findings: list[dict[str, Any]] | None,
    *,
    inconclusive: str | None = None,
    measured: int | None = None,
) -> Transitions:
    """Fold one run into the state and say what moved.

    `inconclusive` is the reason a run established nothing before it began --
    a usage error, a spec that would not load, a transport that never opened.
    Passing it carries the previous state forward untouched. What it does not
    cover is the partial case, where some operations answered and some did
    not; that is read out of the findings themselves, through
    :data:`UNOBSERVABLE_RULES`.

    `measured` is what the command says it managed to observe -- see
    :func:`measured_count`. Zero, with something unreachable in the findings,
    is the whole target being down.
    """
    if inconclusive:
        return Transitions(
            carried=list(state.findings.values()),
            inconclusive=inconclusive,
            baseline=state.runs == 0,
        )

    observed = list(findings or [])
    unobserved = unobserved_operations(observed)
    current = {finding_key(f): f for f in observed}
    previous = dict(state.findings)
    baseline = state.runs == 0

    out = Transitions(baseline=baseline, unobserved=sorted(unobserved))
    for key, finding in current.items():
        was = previous.get(key)
        if was is None:
            # On a baseline run everything is "already there", not "new".
            (out.persisted if baseline else out.appeared).append(finding)
            if not baseline:
                state.flaps[key] = state.flaps.get(key, 0) + 1
                out.flaps[key] = state.flaps[key]
        else:
            out.persisted.append(finding)
            if was.get("message") != finding.get("message"):
                out.message_changed += 1

    carried: dict[str, dict[str, Any]] = {}
    for key, finding in previous.items():
        if key in current:
            continue
        if str(finding.get("operation_key") or "") in unobserved:
            # Its operation did not answer. The finding is not resolved; it is
            # exactly as known as it was before this run.
            carried[key] = finding
            out.carried.append(finding)
            continue
        out.resolved.append(finding)
        state.flaps[key] = state.flaps.get(key, 0) + 1
        out.flaps[key] = state.flaps[key]

    # The command measured nothing and reported something unreachable: this
    # run established facts about the network, not about the API.
    if measured == 0 and unobserved:
        out.inconclusive = (
            f"nothing was measured; {len(unobserved)} operation(s) could not be reached"
        )

    state.findings = {**current, **carried}
    state.runs += 1
    return out


def report(transitions: Transitions, *, target: str | None = None) -> dict[str, Any]:
    """The transition report, in the shape `notify` already reads.

    `findings` holds what changed, so routing a monitor run to a team sends
    them the new thing rather than the standing state. The standing state is
    counted beside it.
    """
    return {
        "target": target,
        "summary": transitions.summary(),
        "baseline": transitions.baseline,
        "inconclusive": transitions.inconclusive,
        "findings": list(transitions.appeared),
        "resolved": transitions.resolved,
        "unobserved": transitions.unobserved,
        "carried_forward": len(transitions.carried),
        # Unchanged since last run -- not the size of the standing set, which
        # is this plus whatever appeared.
        "unchanged_count": len(transitions.persisted),
        "message_changed": transitions.message_changed,
        # Only the keys this run moved, and only when one has crossed more than
        # once: a key at 1 appeared and has never gone away, which is not a flap.
        "flapping": {key: count for key, count in transitions.flaps.items() if count > 1},
    }


__all__ = [
    "MEASURED_KEYS",
    "STATE_VERSION",
    "UNOBSERVABLE_RULES",
    "MonitorState",
    "Transitions",
    "apply_run",
    "finding_key",
    "measured_count",
    "report",
    "unobserved_operations",
]
