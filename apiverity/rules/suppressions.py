"""Baseline-specific finding suppressions with ownership and expiry.

Suppressions are scoped (rule id + optional operation key), must carry an
owner and reason, and expire automatically so permanent ignore-lists do not
accumulate silently. Expired suppressions are surfaced as findings.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from apiverity.core.model import Finding, Severity


@dataclass(frozen=True)
class Suppression:
    rule_id: str
    operation_key: str | None = None  # None = all operations for this rule
    owner: str = ""
    reason: str = ""
    expires: str | None = None  # ISO date; None means review at next audit

    def is_expired(self, today: date) -> bool:
        if self.expires is None:
            return False
        try:
            return date.fromisoformat(self.expires) < today
        except ValueError:
            return True  # malformed expiry fails closed


def load_suppressions(path: str | Path) -> list[Suppression]:
    """Load suppressions from a JSON file: ``{"suppressions": [...]}``."""
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
                )
            )
    return out


@dataclass(frozen=True)
class SuppressionResult:
    active: list[Finding]
    suppressed: list[tuple[Finding, Suppression]]
    expired: list[Suppression]


def apply_suppressions(
    findings: list[Finding],
    suppressions: list[Suppression],
    *,
    today: date | None = None,
) -> SuppressionResult:
    """Split findings into active vs suppressed; flag expired suppressions."""
    today = today or date.today()
    active: list[Finding] = []
    suppressed: list[tuple[Finding, Suppression]] = []
    expired: list[Suppression] = []
    live = [s for s in suppressions if not s.is_expired(today)]
    expired = [s for s in suppressions if s.is_expired(today)]

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

    return SuppressionResult(active=active, suppressed=suppressed, expired=expired)


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
