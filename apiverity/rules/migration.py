"""The guide the API owner already wrote, attached to the finding that blocks.

`DeprecationInfo.migration_guide` has existed in the model since the beginning
and was populated by no parser and read by no rule. `Approval.migration_guide`
is a column in the server database, accepted on every approval request, typed
in the dashboard's `Approval` interface — and rendered nowhere.

Two fields, in two places, both written and never read. This makes the first
one live.

## What it is for

A breaking-change finding says *what* broke. It does not say what to do
instead, and the person who knows that is the API owner, who very often wrote
it down next to the operation:

    /users/{id}:
      get:
        deprecated: true
        x-deprecation:
          sunset: 2027-01-01
          guide: https://docs.example.com/migrating-to-v2
          impact: mobile clients pinned below 3.4 will need a release

`attach` puts that on every finding about that operation, under
`metadata.migration_guide`, so `breaking --summary` and the PR comment carry it
to the reader who is looking at the objection.

## Where the guide comes from, and why it is the *old* contract

The operation being broken is the one in the old document. A guide added to the
new contract in the same change is the author's note to themselves; the guide
that helps a consumer is the one that was already published when they wrote
against it.

So `attach` reads the old service. If the new contract adds a guide and the old
one had none, the finding carries nothing — and `LIFECYCLE-DEPRECATED-NO-GUIDE`
is the rule that objects to that in advance, which is the point at which it is
still cheap to fix.

## What it does not do

Fetch the guide. A URL in a contract is a URL somebody else controls, and this
project does not request addresses the caller did not choose — the same rule
`--allow-remote-refs` exists for. The finding carries the link; the reader
follows it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from apiverity.core.model import DeprecationInfo, Finding, Operation, Service

#: Extension keys carrying a structured deprecation block.
STRUCTURED_KEYS = ("x-deprecation", "x-deprecated")

#: Flat extension keys carrying only the guide, which is what most contracts
#: in the wild actually write. Read as well as the structured block, because a
#: rule that only understood the tidy form would report "points nowhere" about
#: contracts that point somewhere.
GUIDE_KEYS = ("x-migration", "x-migration-guide", "x-deprecation-link", "x-sunset-link")


def _text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def deprecation_of(op: Operation) -> DeprecationInfo | None:
    """What the operation says about its own retirement, as one object.

    `Operation.deprecation` is populated by no parser -- the information is
    scattered across extensions that different documents spell differently --
    so this assembles it on demand rather than adding a fifth spelling.
    """
    announced: str | None = None
    sunset: str | None = None
    guide: str | None = None
    impact: str | None = None

    for key in STRUCTURED_KEYS:
        block = op.extensions.get(key)
        if isinstance(block, dict):
            announced = announced or _text(block.get("announced") or block.get("date"))
            sunset = sunset or _text(block.get("sunset") or block.get("sunset_date"))
            guide = guide or _text(
                block.get("guide") or block.get("link") or block.get("migration_guide")
            )
            impact = impact or _text(block.get("impact") or block.get("consumer_impact"))
        elif _text(block):
            # `x-deprecation: 2026-01-01` is the flat form, and it is a date.
            announced = announced or _text(block)

    for key in GUIDE_KEYS:
        guide = guide or _text(op.extensions.get(key))
    for key in ("x-sunset", "x-sunset-date"):
        sunset = sunset or _text(op.extensions.get(key))

    if not any((announced, sunset, guide, impact)):
        return None
    return DeprecationInfo(
        announced_date=announced,
        sunset_date=sunset,
        migration_guide=guide,
        consumer_impact=impact,
    )


@dataclass
class Guides:
    """operation key -> what its owner said about moving off it."""

    by_operation: dict[str, DeprecationInfo]

    def for_key(self, key: str | None) -> DeprecationInfo | None:
        return self.by_operation.get(key or "")

    def __bool__(self) -> bool:
        return bool(self.by_operation)


def collect(service: Service) -> Guides:
    """Every migration guide a contract declares."""
    found: dict[str, DeprecationInfo] = {}
    for op in service.operations:
        info = deprecation_of(op)
        if info is not None and (info.migration_guide or info.consumer_impact):
            found[op.key] = info
    return Guides(by_operation=found)


def attach(findings: list[Finding], old: Service) -> list[Finding]:
    """Put the owner's guidance on every finding about an operation that has it.

    Read from the *old* contract: the operation being broken is the one
    consumers wrote against, and a guide added in the same change that breaks
    them was not published when they needed it.

    Returns new findings; the originals are not mutated, because the same list
    is read by the semver policy and the summary after this runs.
    """
    guides = collect(old)
    if not guides:
        return findings

    out: list[Finding] = []
    for finding in findings:
        info = guides.for_key(finding.operation_key)
        if info is None:
            out.append(finding)
            continue
        extra: dict[str, Any] = {}
        if info.migration_guide:
            extra["migration_guide"] = info.migration_guide
        if info.consumer_impact:
            extra["consumer_impact"] = info.consumer_impact
        if info.sunset_date:
            extra["sunset_date"] = info.sunset_date
        updated = finding.model_copy(deep=True)
        updated.metadata = {**updated.metadata, **extra}
        out.append(updated)
    return out


def summarize(findings: list[Finding]) -> list[dict[str, str]]:
    """The distinct guides the findings carry, for a report to list once.

    Deduplicated by operation: eleven findings about one removed operation
    should not print the same link eleven times, which is how a useful line
    becomes noise.
    """
    seen: dict[str, dict[str, str]] = {}
    for finding in findings:
        guide = finding.metadata.get("migration_guide")
        if not guide or not finding.operation_key:
            continue
        entry = seen.setdefault(finding.operation_key, {"operation": finding.operation_key})
        entry["guide"] = str(guide)
        impact = finding.metadata.get("consumer_impact")
        if impact:
            entry["impact"] = str(impact)
    return [seen[key] for key in sorted(seen)]


__all__ = [
    "GUIDE_KEYS",
    "STRUCTURED_KEYS",
    "Guides",
    "attach",
    "collect",
    "deprecation_of",
    "summarize",
]
