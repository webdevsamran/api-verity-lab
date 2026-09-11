"""A per-team contract-health digest, and what it refuses to call good news.

`apiverity sweep` answers a platform team's question -- which contracts are
failing and whose they are -- as one document covering everything. A digest is
the same data cut the other way: one document per team, holding only what that
team owns, so it can be sent to that team.

## Why a digest may repeat itself and a monitor may not

`apiverity monitor` reports only transitions, because a five-minute check that
re-prints the standing state is muted inside a week. A weekly digest is the
opposite: surfacing standing debt *is* its job. A contract that has been
failing for three weeks belongs in every one of those three digests, with the
number of weeks attached.

So a digest carries both -- what moved since the last one, and what has not
moved at all.

## The comparison that produces a false all-clear

Two sweeps are two walks of a tree, and the tree can change underneath them.
Last week's sweep found forty contracts; this week's `--limit` was lower, or a
service moved to another repository, or the discovery glob changed. Twelve
contracts are simply absent from the second run.

Differenced naively, that is *twelve contracts fixed*.

:func:`compare` keeps those in `no_longer_swept` and never in `fixed`. A
contract is fixed when this sweep looked at it and found no errors; a contract
absent from this sweep was not looked at, and the digest says which of the two
happened.

## Unowned contracts

A per-team digest that only reports owned contracts silently drops the
contracts nobody will be asked about -- which are exactly the ones most likely
to rot. They are gathered under `(unowned)` and reported as a team, so the
platform team receives them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: The bucket for contracts no CODEOWNERS rule matched. Not dropped: a digest
#: that reports only owned contracts hides the ones nobody is accountable for.
UNOWNED = "(unowned)"


def _contracts(sweep: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """A sweep artifact's contract records, keyed by path."""
    records = sweep.get("contracts")
    if not isinstance(records, list):
        raise ValueError(
            "this is not a sweep artifact: it has no top-level `contracts` array. "
            "Produce one with `apiverity sweep . --json`"
        )
    return {str(r.get("path")): r for r in records if isinstance(r, dict) and r.get("path")}


def _finding_keys(record: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """A contract's findings keyed the way the monitor keys them."""
    from apiverity.runtime.monitor import finding_key

    out: dict[str, dict[str, Any]] = {}
    for finding in record.get("findings") or []:
        if isinstance(finding, dict):
            out[finding_key(finding)] = finding
    return out


@dataclass
class TeamDigest:
    """One team's slice of a sweep, and how it moved since the last one."""

    team: str
    #: Contracts this team owns, in the order the sweep walked them.
    contracts: list[dict[str, Any]] = field(default_factory=list)
    failing: list[str] = field(default_factory=list)
    #: Failing now, not failing in the previous sweep.
    newly_failing: list[str] = field(default_factory=list)
    #: Failing before, looked at again, and clean now. Never a contract that
    #: merely went missing -- see `no_longer_swept`.
    fixed: list[str] = field(default_factory=list)
    #: In the previous sweep and not in this one. Not fixed: not looked at.
    no_longer_swept: list[str] = field(default_factory=list)
    #: In this sweep and not the previous one.
    newly_swept: list[str] = field(default_factory=list)
    appeared: list[dict[str, Any]] = field(default_factory=list)
    resolved: list[dict[str, Any]] = field(default_factory=list)
    errors: int = 0
    warnings: int = 0
    #: True when there was no previous sweep to compare against.
    baseline: bool = True

    @property
    def unreadable(self) -> list[str]:
        return [str(c["path"]) for c in self.contracts if c.get("status") == "unreadable"]

    @property
    def standing(self) -> list[str]:
        """Failing now *and* failing before: the debt a weekly digest exists for.

        Empty on a baseline digest. There is no previous sweep, so "still
        failing" would be a claim about a week nobody looked at -- which is
        how the first rendering of this said "Failing in the previous digest
        too" above a list produced by the first run there had ever been.
        """
        if self.baseline:
            return []
        new = set(self.newly_failing)
        return [path for path in self.failing if path not in new]

    @property
    def quiet(self) -> bool:
        """Nothing to say at all -- no debt and no movement.

        A digest for a quiet team is not sent. This is *not* the monitor's
        rule: standing failures are never quiet here, however old they are.
        """
        return not (
            self.failing
            or self.appeared
            or self.resolved
            or self.no_longer_swept
            or self.unreadable
        )

    def summary(self) -> str:
        if self.baseline:
            return (
                f"{len(self.contracts)} contract(s), {len(self.failing)} failing, "
                f"{self.errors} error(s) -- first digest, nothing compared"
            )
        parts = [f"{len(self.contracts)} contract(s)"]
        if self.newly_failing:
            parts.append(f"{len(self.newly_failing)} newly failing")
        if self.fixed:
            parts.append(f"{len(self.fixed)} fixed")
        if self.standing:
            parts.append(f"{len(self.standing)} still failing")
        if self.no_longer_swept:
            parts.append(f"{len(self.no_longer_swept)} no longer swept")
        if len(parts) == 1:
            parts.append("nothing changed, nothing failing")
        return ", ".join(parts)


def compare(
    current: dict[str, Any], previous: dict[str, Any] | None = None
) -> dict[str, TeamDigest]:
    """One digest per team, from a sweep artifact and optionally the last one.

    Teams come from the sweep's own ownership resolution, so a digest cannot
    disagree with the sweep it is built from about who owns what.
    """
    now = _contracts(current)
    before = _contracts(previous) if previous is not None else {}
    baseline = previous is None

    digests: dict[str, TeamDigest] = {}
    for path, record in now.items():
        owners = [str(o) for o in (record.get("owners") or [])] or [UNOWNED]
        was = before.get(path)
        failing = bool(record.get("errors"))
        was_failing = bool(was.get("errors")) if was else False
        current_findings = _finding_keys(record)
        previous_findings = _finding_keys(was) if was else {}

        for owner in owners:
            digest = digests.setdefault(owner, TeamDigest(team=owner, baseline=baseline))
            digest.contracts.append(record)
            digest.errors += int(record.get("errors") or 0)
            digest.warnings += int(record.get("warnings") or 0)
            if failing:
                digest.failing.append(path)
            if baseline:
                continue
            if was is None:
                digest.newly_swept.append(path)
                # Everything about a contract nobody swept before is new to
                # this digest, but it is not a regression -- it is the first
                # look. Counted as newly failing only if it fails.
                if failing:
                    digest.newly_failing.append(path)
                continue
            if failing and not was_failing:
                digest.newly_failing.append(path)
            elif was_failing and not failing:
                digest.fixed.append(path)
            digest.appeared.extend(
                f for key, f in current_findings.items() if key not in previous_findings
            )
            digest.resolved.extend(
                f for key, f in previous_findings.items() if key not in current_findings
            )

    # Contracts the previous sweep saw and this one did not. Deliberately last,
    # and deliberately not `fixed`: this sweep did not look at them.
    for path, record in before.items():
        if path in now:
            continue
        for owner in [str(o) for o in (record.get("owners") or [])] or [UNOWNED]:
            digest = digests.setdefault(owner, TeamDigest(team=owner, baseline=baseline))
            digest.no_longer_swept.append(path)

    return {team: digests[team] for team in sorted(digests)}


def render(digest: TeamDigest, *, root: str | None = None, limit: int = 20) -> str:
    """One team's digest as markdown, for a channel, an email or a file."""
    lines = [f"# Contract health — {digest.team}", "", digest.summary(), ""]
    if root:
        lines += [f"Swept from `{root}`.", ""]

    def block(title: str, paths: list[str], note: str = "") -> None:
        if not paths:
            return
        lines.append(f"## {title} ({len(paths)})")
        if note:
            lines.append("")
            lines.append(note)
        lines.append("")
        lines.extend(f"- `{path}`" for path in paths[:limit])
        if len(paths) > limit:
            lines.append(f"- …and {len(paths) - limit} more")
        lines.append("")

    if digest.baseline:
        block(
            "Failing",
            digest.failing,
            "The current state. Nothing here is called new or old: there is no "
            "previous digest to compare against.",
        )
    else:
        block("Newly failing", digest.newly_failing)
        block("Still failing", digest.standing, "Failing in the previous digest too.")
        block("Fixed", digest.fixed)
    block(
        "No longer swept",
        digest.no_longer_swept,
        "Present in the previous sweep and absent from this one. This is not "
        "the same as fixed: this run did not look at them.",
    )
    block(
        "Would not load",
        digest.unreadable,
        "A contract that will not parse is the loudest finding about that "
        "contract, not an absence of findings.",
    )

    if digest.appeared:
        lines.append(f"## New findings ({len(digest.appeared)})")
        lines.append("")
        for finding in digest.appeared[:limit]:
            rule = finding.get("rule_id") or "?"
            where = finding.get("operation_key") or finding.get("path") or ""
            lines.append(f"- **{rule}** {where} — {finding.get('message', '')}".rstrip(" —"))
        if len(digest.appeared) > limit:
            lines.append(f"- …and {len(digest.appeared) - limit} more")
        lines.append("")

    if digest.baseline:
        lines.append(
            "_First digest for this team: the contracts above are the current state, "
            "not a change. Pass `--since` with this run's artifact next time to get "
            "a comparison._"
        )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def as_dict(digest: TeamDigest) -> dict[str, Any]:
    """The digest as data, with `findings` holding what `notify` should route."""
    return {
        "team": digest.team,
        "summary": digest.summary(),
        "baseline": digest.baseline,
        "contracts": [str(c.get("path")) for c in digest.contracts],
        "errors": digest.errors,
        "warnings": digest.warnings,
        "failing": digest.failing,
        "newly_failing": digest.newly_failing,
        "still_failing": digest.standing,
        "fixed": digest.fixed,
        "newly_swept": digest.newly_swept,
        "no_longer_swept": digest.no_longer_swept,
        "unreadable": digest.unreadable,
        # `findings` is the key `apiverity notify` reads. On a baseline digest
        # there is nothing new, so nothing is routed -- the first digest is for
        # reading, not for paging.
        "findings": digest.appeared,
        "resolved": digest.resolved,
    }


__all__ = ["UNOWNED", "TeamDigest", "as_dict", "compare", "render"]
