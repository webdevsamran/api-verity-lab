"""The gate's escape hatch, and the rules that keep it from becoming the exit.

A contract gate that cannot be quietened gets removed. A contract gate that can
be quietened without saying who, why, or until when *is* removed -- it stays in
CI, reports nothing, and everybody believes it is working. The suppressions
file exists for the first problem and this module's job is the second.

## What was here, and what it did

The docstring on this module said suppressions "must carry an owner and reason,
and expire automatically so permanent ignore-lists do not accumulate silently".
`docs/ci.md` said "each one needs an owner, a reason and an expiry".

Neither was enforced. `load_suppressions` defaulted `owner` and `reason` to the
empty string and `expires` to `None`, and `is_expired` returns False for
`None`. So this:

    {"suppressions": [{"rule_id": "BRK-FIELD-REMOVED"}]}

was accepted, and silenced every removed field in every operation, permanently,
with nobody's name on it. The one-line file that turns the gate off was the
documented format's happy path.

## What it does now

An entry that is not *justified* and *bounded* does not suppress. It fails
closed: the finding it named stays active, and a `SUPPRESSION-INCOMPLETE`
finding says which requirement it missed. Refusing to load the whole file would
be worse -- one bad entry would take out the entries that are fine, and the
gate would be quietened by a syntax error.

Justified means an `owner` and a `reason`. Bounded means an `expires` date, and
one within `DEFAULT_MAX_LIFETIME_DAYS` of today, because "expires 2099-01-01"
is a permanent ignore with a date on it. Both the maximum and whether an
`approved_by` name is required are project settings, because a review model is
a fact about a team rather than about a contract.

`SUPPRESSION-UNSCOPED` is deliberately INFO and deliberately still suppresses.
An entry with no `operation_key` silences its rule across the whole contract,
which is sometimes exactly right and is always worth a reader knowing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from apiverity.core.model import Finding, Severity

#: How far ahead an expiry may sit before the suppression stops being bounded.
#:
#: Ninety days is one quarter: long enough to survive a release train, short
#: enough that a suppression written today is reviewed by someone who remembers
#: writing it. Projects override it with `suppression_max_days`.
DEFAULT_MAX_LIFETIME_DAYS = 90


@dataclass(frozen=True)
class Suppression:
    rule_id: str
    operation_key: str | None = None  # None = all operations for this rule
    owner: str = ""
    reason: str = ""
    expires: str | None = None  # ISO date
    #: Who agreed to it, if the project asks for a second name. Distinct from
    #: `owner`: the owner is who carries the work, the approver is who accepted
    #: the risk of not doing it yet.
    approved_by: str = ""

    def is_expired(self, today: date) -> bool:
        if self.expires is None:
            return False
        try:
            return date.fromisoformat(self.expires) < today
        except ValueError:
            return True  # malformed expiry fails closed

    def problems(
        self,
        today: date,
        *,
        max_days: int = DEFAULT_MAX_LIFETIME_DAYS,
        require_approver: bool = False,
    ) -> list[str]:
        """Why this entry is not a justified, bounded suppression.

        Empty means it is one. Every string is a complete sentence naming the
        missing field, because the reader is looking at a JSON file and needs
        to know which key to add.
        """
        out: list[str] = []
        if not self.rule_id.strip():
            out.append("it names no `rule_id`, so there is nothing for it to suppress")
        if not self.owner.strip():
            out.append("it has no `owner`; a suppression nobody owns is nobody's to revisit")
        if not self.reason.strip():
            out.append(
                "it has no `reason`; the next reader cannot tell a decision from an oversight"
            )
        if require_approver and not self.approved_by.strip():
            out.append(
                "it has no `approved_by`, and this project sets "
                "`suppression_require_approver: true`"
            )
        if self.expires is None:
            out.append(
                "it has no `expires` date, so it is permanent -- which is the thing this "
                "format exists to prevent"
            )
            return out
        try:
            expiry = date.fromisoformat(self.expires)
        except ValueError:
            out.append(f"its `expires` value {self.expires!r} is not an ISO date (YYYY-MM-DD)")
            return out
        if expiry > today + timedelta(days=max_days):
            out.append(
                f"it expires on {self.expires}, more than {max_days} days out; an expiry "
                "far enough away is a permanent ignore with a date on it"
            )
        return out


def load_suppressions(path: str | Path) -> list[Suppression]:
    """Load suppressions from a JSON file: ``{"suppressions": [...]}``.

    Loading does not judge. A malformed entry becomes a `Suppression` with
    empty fields, `apply_suppressions` reports exactly what is wrong with it,
    and the finding it named stays active. Rejecting here would take the whole
    file out over one entry.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    items = data.get("suppressions", data) if isinstance(data, dict) else data
    out: list[Suppression] = []
    for item in items or []:
        if isinstance(item, dict):
            out.append(
                Suppression(
                    rule_id=str(item.get("rule_id", "")),
                    operation_key=item.get("operation_key"),
                    owner=str(item.get("owner", "")),
                    reason=str(item.get("reason", "")),
                    expires=item.get("expires"),
                    approved_by=str(item.get("approved_by", "")),
                )
            )
    return out


@dataclass(frozen=True)
class SuppressionResult:
    active: list[Finding]
    suppressed: list[tuple[Finding, Suppression]]
    expired: list[Suppression]
    #: Entries that did not suppress, each with every requirement it missed.
    incomplete: list[tuple[Suppression, list[str]]]
    #: Entries that suppress a rule across every operation.
    unscoped: list[Suppression]


def apply_suppressions(
    findings: list[Finding],
    suppressions: list[Suppression],
    *,
    today: date | None = None,
    max_days: int = DEFAULT_MAX_LIFETIME_DAYS,
    require_approver: bool = False,
) -> SuppressionResult:
    """Split findings into active vs suppressed, and say what did not qualify.

    Three ways an entry fails to suppress, in order of what a reader should do
    about it: it expired (re-justify or fix), it was never justified or bounded
    (write the missing field), or it matched nothing (delete it).
    """
    today = today or date.today()
    active: list[Finding] = []
    suppressed: list[tuple[Finding, Suppression]] = []

    # Order matters. `is_expired` treats an unparseable date as expired, which
    # fails closed correctly and then reports "expired on 'next quarter'" -- a
    # sentence that sends the reader looking for a date that has passed. So
    # completeness is judged first, and it is where a malformed date is named.
    expired: list[Suppression] = []
    incomplete: list[tuple[Suppression, list[str]]] = []
    live: list[Suppression] = []
    for suppression in suppressions:
        problems = suppression.problems(today, max_days=max_days, require_approver=require_approver)
        if problems:
            incomplete.append((suppression, problems))
        elif suppression.is_expired(today):
            expired.append(suppression)
        else:
            live.append(suppression)

    for f in findings:
        match = next(
            (
                s
                for s in live
                if s.rule_id == f.rule_id
                and (s.operation_key is None or s.operation_key == f.operation_key)
            ),
            None,
        )
        if match is not None:
            suppressed.append((f, match))
        else:
            active.append(f)

    return SuppressionResult(
        active=active,
        suppressed=suppressed,
        expired=expired,
        incomplete=incomplete,
        unscoped=[s for s in live if s.operation_key is None],
    )


def expired_suppression_findings(expired: list[Suppression]) -> list[Finding]:
    """Convert expired suppressions into actionable findings."""
    return [
        Finding(
            rule_id="SUPPRESSION-EXPIRED",
            severity=Severity.WARN,
            message=(
                f"suppression for '{s.rule_id}'"
                + (f" on '{s.operation_key}'" if s.operation_key else "")
                + f" owned by '{s.owner or 'unknown'}' expired on {s.expires}; "
                "re-justify it with an owner, reason and new expiry, or fix the issue"
            ),
            operation_key=s.operation_key,
        )
        for s in expired
    ]


def incomplete_suppression_findings(
    incomplete: list[tuple[Suppression, list[str]]],
) -> list[Finding]:
    """One finding per entry that did not qualify, naming every missing field.

    WARN rather than ERROR on purpose. The finding this entry failed to
    suppress is still in the run at its own severity and will fail the gate on
    its own if it is an error; raising this one to ERROR would fail a build
    twice for one problem, and would fail it at all on a file whose bad entry
    happened to match nothing.
    """
    return [
        Finding(
            rule_id="SUPPRESSION-INCOMPLETE",
            severity=Severity.WARN,
            message=(
                f"the suppression for '{s.rule_id or '(no rule id)'}'"
                + (f" on '{s.operation_key}'" if s.operation_key else "")
                + " did not suppress anything, because "
                + "; and ".join(problems)
            ),
            operation_key=s.operation_key,
        )
        for s, problems in incomplete
    ]


def unscoped_suppression_findings(unscoped: list[Suppression]) -> list[Finding]:
    """One note per entry that silences its rule everywhere.

    INFO, and these entries do suppress. Silencing a rule across a whole
    contract is sometimes the right call -- an API that genuinely has no
    pagination does not need the pagination rule on forty operations -- and it
    is never a thing a reader should have to reconstruct from the file.
    """
    return [
        Finding(
            rule_id="SUPPRESSION-UNSCOPED",
            severity=Severity.INFO,
            message=(
                f"'{s.rule_id}' is suppressed across every operation until {s.expires} "
                f"by '{s.owner}'; naming an `operation_key` would keep the rule live "
                "everywhere else"
            ),
        )
        for s in unscoped
    ]
