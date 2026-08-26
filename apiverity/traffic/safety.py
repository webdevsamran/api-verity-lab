"""Replay/load safety gating.

Centralizes the protections required before any traffic is sent to a target:
- explicit host allowlists;
- target safety classification (local/dev/staging/production);
- dry-run plans that show exactly which requests would be sent;
- destructive-method protection requiring an allowlist AND a confirmation token.
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urljoin, urlparse

from pydantic import BaseModel, Field

DESTRUCTIVE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class ReplayLike(Protocol):
    """Minimal shape safety functions need from replay entries."""

    method: str
    path: str


class TargetClassification(BaseModel):
    base_url: str
    classification: str  # local | dev | staging | production | unknown
    allowed_modes: list[str] = Field(default_factory=list)  # e.g. ["read-only", "replay", "load"]


def classify_target(base_url: str) -> TargetClassification:
    """Heuristic classification; production requires explicit override."""
    host = urlparse(base_url).hostname or ""
    lowered = host.lower()
    if (
        lowered in {"localhost", "127.0.0.1", "::1"}
        or lowered.endswith(".local")
        or lowered.startswith("192.168.")
        or lowered.startswith("10.")
    ):
        return TargetClassification(
            base_url=base_url,
            classification="local",
            allowed_modes=["read-only", "replay", "load"],
        )
    if any(tag in lowered for tag in ("staging", "stage", "preprod")):
        return TargetClassification(
            base_url=base_url,
            classification="staging",
            allowed_modes=["read-only", "replay", "load"],
        )
    if any(tag in lowered for tag in ("dev.", "-dev", ".dev")):
        return TargetClassification(
            base_url=base_url,
            classification="dev",
            allowed_modes=["read-only", "replay", "load"],
        )
    if any(tag in lowered for tag in ("prod", "api.", ".com", ".io", ".net", ".org")):
        return TargetClassification(
            base_url=base_url,
            classification="production",
            allowed_modes=["read-only"],
        )
    return TargetClassification(
        base_url=base_url, classification="unknown", allowed_modes=["read-only"]
    )


@dataclass(frozen=True)
class PlannedRequest:
    method: str
    url: str


@dataclass(frozen=True)
class SafetyDecision:
    approved: bool
    reason: str


def build_dry_run_plan(entries: Sequence[ReplayLike], base_url: str) -> list[PlannedRequest]:
    """Exactly which requests would be sent — nothing is transmitted."""
    plan = []
    for entry in entries:
        url = urljoin(base_url.rstrip("/") + "/", entry.path.lstrip("/"))
        plan.append(PlannedRequest(method=entry.method.upper(), url=url))
    return plan


def confirmation_token(base_url: str, methods: set[str], entries_count: int) -> str:
    """Deterministic token the operator must echo to unlock destructive replay."""
    basis = "|".join(sorted(methods)) + f"|{base_url}|{entries_count}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:12]


def check_replay_safety(
    *,
    base_url: str,
    allowed_hosts: list[str],
    entries: Sequence[ReplayLike],
    destructive_allowlist: set[str] | None = None,
    confirmation: str | None = None,
) -> SafetyDecision:
    """Full gate: allowlist, classification and destructive-method protection."""
    parsed = urlparse(base_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    if origin not in {h.rstrip("/") for h in allowed_hosts}:
        return SafetyDecision(False, f"target '{origin}' is not in the allowlist")

    classification = classify_target(base_url)
    if classification.classification == "production":
        return SafetyDecision(
            False,
            "target classified as production; replay/load against production is refused by design",
        )

    used_methods = {e.method.upper() for e in entries}
    destructive_used = used_methods & DESTRUCTIVE_METHODS
    if destructive_used:
        allow = destructive_allowlist or set()
        unapproved = destructive_used - allow
        if unapproved:
            return SafetyDecision(
                False,
                f"destructive methods {sorted(unapproved)} are not in the destructive allowlist",
            )
        expected = confirmation_token(base_url, destructive_used, len(entries))
        if not confirmation or not hmac.compare_digest(expected, confirmation):
            return SafetyDecision(
                False,
                f"destructive replay requires confirmation token '{expected}' "
                "(printed by --dry-run)",
            )
    return SafetyDecision(True, f"approved ({classification.classification} target)")
