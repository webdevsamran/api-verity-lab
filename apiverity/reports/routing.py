"""Send a finding to the people it is about, not to a channel nobody reads.

A gate that posts every finding to one #api-alerts channel produces a channel
that is muted within a month, and after that the gate is decorative. The
information needed to route already exists in two places this project reads:
CODEOWNERS says who owns the contract file, and the consumer registry says who
calls the operation. Neither had ever been used to decide where a message goes.

Two audiences, and they are not the same people
-----------------------------------------------
The **owner** of a contract needs to know what they changed. The **consumers**
of an operation need to know what is about to break for them. A single message
serves neither well: the owner does not need a list of the teams they are about
to break in order to fix their own file, and a consumer does not need the
owner's rule catalogue.

So a finding is routed to both, with a different message for each, and the
report says which findings could not be routed at all -- an unroutable finding
is the one that ends up nowhere, and silently dropping it is exactly how a
routing layer makes things worse than the shared channel it replaced.

Nothing is sent
---------------
This module builds messages and returns them. Delivery is the caller's, behind
the same kind of explicit gate `replay` and `--invoke-tool` use: a tool that
posts to a team's channel as a side effect of a dry run has done something the
person running it did not ask for.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "Message",
    "Route",
    "RoutingPlan",
    "load_routes",
    "plan_notifications",
]


@dataclass(frozen=True)
class Route:
    """Where one team's messages go."""

    team: str
    #: An incoming-webhook URL, or any endpoint that takes a JSON POST.
    url: str
    #: `slack` / `teams` / `raw`. Decides the payload shape, nothing else.
    kind: str = "slack"


@dataclass
class Message:
    """One rendered notification, and who it is for."""

    team: str
    url: str
    kind: str
    subject: str
    body: str
    #: Rule ids included, so a caller can log what was sent without the text.
    rule_ids: tuple[str, ...] = ()
    #: `owner` or `consumer` -- the two audiences read for different reasons.
    audience: str = "owner"

    def payload(self) -> dict[str, Any]:
        """The JSON body for this destination's shape.

        Slack and Teams both accept a plain `text` field, and both render
        Markdown-ish content in it. Anything richer is a per-vendor block
        format that would have to be maintained against two moving targets for
        no gain a reader would notice.
        """
        if self.kind == "teams":
            return {"title": self.subject, "text": self.body}
        if self.kind == "raw":
            return {"subject": self.subject, "body": self.body, "team": self.team}
        return {"text": f"*{self.subject}*\n{self.body}"}


@dataclass
class RoutingPlan:
    messages: list[Message] = field(default_factory=list)
    #: Findings that reached nobody, with why. Never dropped silently: an
    #: unroutable finding is the one that ends up nowhere.
    unrouted: list[dict[str, str]] = field(default_factory=list)
    #: Teams named by ownership or a consumer registry with no route
    #: configured. Distinct from a finding nobody owns.
    unknown_teams: list[str] = field(default_factory=list)


def load_routes(raw: Any) -> dict[str, Route]:
    """Routes from `{"team": {"url": ..., "kind": ...}}` or `{"team": url}`.

    Both shapes are accepted because both get written. The short one is what
    someone types first, and refusing it would mean the feature's first
    five minutes are spent reading a schema.
    """
    routes: dict[str, Route] = {}
    if not isinstance(raw, dict):
        raise ValueError("routes must be a mapping of team to destination")
    for team, value in raw.items():
        name = str(team)
        if isinstance(value, str):
            routes[name] = Route(team=name, url=value)
        elif isinstance(value, dict) and value.get("url"):
            routes[name] = Route(
                team=name,
                url=str(value["url"]),
                kind=str(value.get("kind", "slack")).lower(),
            )
        else:
            raise ValueError(f"route for {name!r} has no url")
    return routes


def _severity(finding: Any) -> str:
    value = (
        finding.get("severity") if isinstance(finding, dict) else getattr(finding, "severity", "")
    )
    return str(getattr(value, "value", value) or "INFO").upper()


def _field(finding: Any, name: str) -> Any:
    return finding.get(name) if isinstance(finding, dict) else getattr(finding, name, None)


def _summarise(findings: list[Any]) -> str:
    counts: dict[str, int] = {}
    for finding in findings:
        severity = _severity(finding)
        counts[severity] = counts.get(severity, 0) + 1
    return ", ".join(f"{count} {sev.lower()}" for sev, count in sorted(counts.items()))


def _lines(findings: list[Any], limit: int = 10) -> str:
    shown = [
        f"• `{_field(f, 'rule_id')}` {_field(f, 'operation_key') or ''} — {_field(f, 'message')}"
        for f in findings[:limit]
    ]
    if len(findings) > limit:
        shown.append(f"…and {len(findings) - limit} more.")
    return "\n".join(shown)


def plan_notifications(
    findings: list[Any],
    routes: dict[str, Route],
    *,
    contract_path: str = "",
    owners: tuple[str, ...] = (),
    consumers_by_operation: dict[str, list[str]] | None = None,
    teams_by_consumer: dict[str, str] | None = None,
    subject_prefix: str = "apiverity",
) -> RoutingPlan:
    """Group findings by who needs to see them, and render one message each.

    `owners` comes from CODEOWNERS, `consumers_by_operation` from the consumer
    registry. Both are optional, and the plan is explicit about what it could
    not route rather than quietly producing fewer messages.
    """
    plan = RoutingPlan()
    if not findings:
        return plan

    gating = [f for f in findings if _severity(f) in {"ERROR", "WARN"}]
    if not gating:
        return plan

    consumers_by_operation = consumers_by_operation or {}
    teams_by_consumer = teams_by_consumer or {}
    unknown: set[str] = set()

    # --- the owners: what you changed --------------------------------------
    for owner in owners:
        route = routes.get(owner)
        if route is None:
            unknown.add(owner)
            continue
        plan.messages.append(
            Message(
                team=owner,
                url=route.url,
                kind=route.kind,
                subject=f"{subject_prefix}: {len(gating)} finding(s) on {contract_path or 'a contract you own'}",
                body=(
                    f"{_summarise(gating)}.\n{_lines(gating)}\n\n"
                    "`apiverity explain <RULE-ID>` prints what each one means and the "
                    "non-breaking route to the same change."
                ),
                rule_ids=tuple(str(_field(f, "rule_id")) for f in gating),
                audience="owner",
            )
        )

    # --- the consumers: what is about to break for you ---------------------
    #
    # Only ERROR findings reach a consumer. A warning is a conversation the
    # owning team has with itself; forwarding every one of them to five other
    # teams is how a routing layer recreates the muted channel it replaced.
    errors = [f for f in gating if _severity(f) == "ERROR"]
    per_team: dict[str, list[Any]] = {}
    for finding in errors:
        operation = str(_field(finding, "operation_key") or "")
        for consumer in consumers_by_operation.get(operation, []):
            team = teams_by_consumer.get(consumer) or consumer
            per_team.setdefault(team, []).append(finding)

    for team, team_findings in sorted(per_team.items()):
        route = routes.get(team)
        if route is None:
            unknown.add(team)
            continue
        plan.messages.append(
            Message(
                team=team,
                url=route.url,
                kind=route.kind,
                subject=f"{subject_prefix}: {len(team_findings)} breaking change(s) affect you",
                body=(
                    f"{contract_path or 'A contract'} changed in ways that break operations "
                    f"your services call.\n{_lines(team_findings)}"
                ),
                rule_ids=tuple(str(_field(f, "rule_id")) for f in team_findings),
                audience="consumer",
            )
        )

    routed_rules = {rule for message in plan.messages for rule in message.rule_ids}
    for finding in gating:
        rule = str(_field(finding, "rule_id"))
        if rule in routed_rules:
            continue
        plan.unrouted.append(
            {
                "rule_id": rule,
                "operation_key": str(_field(finding, "operation_key") or ""),
                "reason": (
                    "no CODEOWNERS entry for this contract and no consumer registered for "
                    "this operation"
                    if not owners
                    else "the owning team has no route configured"
                ),
            }
        )

    plan.unknown_teams = sorted(unknown)
    return plan
