"""An emergency stop, and an honest account of what it stops.

Auditors of agent-era systems now ask for three things by name: activity logs,
permission reviews, and a **kill-switch procedure**. The first two existed here.
The third did not, and "revoke the tokens" is not a procedure -- it is an
outage, it takes the verification runs down with it, and it leaves no record of
who decided or why.

A freeze is the smaller, reversible version: releases stop, everything that
tells you whether it is safe to restart keeps running.

## Who can pull it, and who can release it

Pulling is `request_approval`-level -- any member. Releasing is
`decide_approval`-level -- an admin.

Deliberately asymmetric. An emergency in which only an administrator can stop
deployments, and the administrator is asleep, *is* the emergency. The cost of a
member freezing in error is a paused pipeline and a loud audit entry; the cost
of nobody being able to stop is the thing the switch exists for. Restarting is
the decision that deserves the higher bar, because it is the one that says the
danger has passed.

## No auto-expiry

There is no timer that lifts a freeze. A kill switch that releases itself is
not a kill switch, and the moment it would fire is exactly the moment nobody is
watching.

What a freeze does carry is `review_by`: an advisory timestamp after which the
state is reported as **overdue for review**. That gives the "do not forget this
is on" property without the "turns itself back on" hazard. Nothing acts on it
except the report.

## What it does not stop

Stated here and returned in the state object, because a switch believed to do
more than it does is worse than no switch:

- It does not stop **verification runs, drift checks or the job queue**. Those
  are how you find out whether it is safe to lift, so taking them down with the
  releases would leave you frozen and blind.
- It does not stop anything **outside this server**. A deploy pipeline that
  never calls `can-i-deploy` is not affected by a freeze, and neither is an MCP
  server somebody else operates. This is an interlock on the decisions this
  server makes, not a network kill switch.
- It does not **revoke credentials**. A caller holding a valid token still
  reads, publishes and records runs.
- It does not stop an approval being **denied**. Only granting is refused;
  refusing a denial during an incident would freeze the wrong direction.

Every transition -- on and off -- appends to the hash-chained audit log with the
actor and the reason, so the procedure is evidenced rather than asserted. See
[`docs/audit-export.md`](../../docs/audit-export.md).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: Audit actions, named once so the log and the code cannot drift.
FROZEN = "org.frozen"
LIFTED = "org.freeze_lifted"

#: What a freeze refuses. Enumerated rather than described, so the state object
#: can carry it to a caller who is looking at a `deployable: false` and wants to
#: know what else is off.
BLOCKS = (
    "can-i-deploy returns deployable: false, whatever the verifications say",
    "an approval cannot be granted (it can still be denied)",
)

NOT_BLOCKED = (
    "verification runs, drift checks and the job queue keep working -- they are how you "
    "find out whether it is safe to lift",
    "anything that never calls this server, including a pipeline that does not ask can-i-deploy",
    "credentials: a valid token still reads, publishes and records runs",
)


@dataclass(frozen=True)
class FreezeState:
    """Whether releases are stopped, and everything a caller needs to say so."""

    active: bool
    reason: str | None = None
    actor: str | None = None
    since: str | None = None
    review_by: str | None = None
    #: True when `review_by` has passed. Advisory: nothing lifts on it.
    overdue: bool = False

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "frozen": self.active,
            "reason": self.reason,
            "actor": self.actor,
            "since": self.since,
            "review_by": self.review_by,
            "overdue_for_review": self.overdue,
        }
        if self.active:
            # Carried on every frozen response rather than left to the docs. A
            # caller reading `deployable: false` is mid-incident and is not
            # going to go and find the page.
            payload["blocks"] = list(BLOCKS)
            payload["does_not_block"] = list(NOT_BLOCKED)
        return payload

    def refusal(self) -> str:
        """The sentence a blocked caller gets."""
        who = f" by {self.actor}" if self.actor else ""
        when = f" since {self.since}" if self.since else ""
        why = f": {self.reason}" if self.reason else ""
        return f"deployments are frozen{who}{when}{why}"


__all__ = ["BLOCKS", "FROZEN", "LIFTED", "NOT_BLOCKED", "FreezeState"]
