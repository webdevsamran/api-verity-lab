"""Versioned result artifacts.

Every command emits an artifact conforming to ``schemas/result-v1.schema.json``:
tool version, protocol, contract hash, target metadata, seed, timing,
findings and redaction state.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from apiverity import __version__
from apiverity.core.hash import contract_hash
from apiverity.core.model import Finding, Protocol, Service

ARTIFACT_VERSION = "1"

EXIT_OK = 0
EXIT_FINDINGS = 1  # findings present at/above threshold
EXIT_USAGE = 2
EXIT_TARGET_ERROR = 3  # could not reach/parse target
EXIT_INTERNAL = 4


class TargetInfo(BaseModel):
    base_url: Optional[str] = None
    environment: Optional[str] = None
    marked_production: bool = False


class Timing(BaseModel):
    started_at: str = ""
    duration_ms: int = 0


class RedactionState(BaseModel):
    enabled: bool = True
    rules_applied: list[str] = Field(default_factory=list)


class RunReport(BaseModel):
    """Base artifact for every engine's output."""

    artifact: str
    artifact_version: str = ARTIFACT_VERSION
    tool_version: str = __version__
    protocol: Protocol = Protocol.OPENAPI
    contract_hash: str = ""
    old_contract_hash: Optional[str] = None
    target: TargetInfo = Field(default_factory=TargetInfo)
    seed: int = 0
    timing: Timing = Field(default_factory=Timing)
    redaction: RedactionState = Field(default_factory=RedactionState)
    findings: list[Finding] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def create(
        cls,
        artifact: str,
        service: Optional[Service],
        *,
        old_service: Optional[Service] = None,
        target: Optional[TargetInfo] = None,
        seed: int = 0,
    ) -> "RunReport":
        now = datetime.now(UTC)
        report = cls(
            artifact=artifact,
            protocol=service.protocol if service else Protocol.OPENAPI,
            contract_hash=contract_hash(service) if service else "",
            old_contract_hash=(
                contract_hash(old_service) if old_service is not None else None
            ),
            target=target or TargetInfo(),
            seed=seed,
            timing=Timing(started_at=now.isoformat()),
        )
        return report

    def finish(self) -> None:
        from datetime import datetime as _dt

        try:
            start = _dt.fromisoformat(self.timing.started_at)
            self.timing.duration_ms = int(
                (_dt.now(UTC) - start).total_seconds() * 1000
            )
        except ValueError:
            self.timing.duration_ms = 0

    def counts_by_severity(self) -> dict[str, int]:
        counts = {"ERROR": 0, "WARN": 0, "INFO": 0}
        for finding in self.findings:
            counts[finding.severity.value] += 1
        return counts

    def exit_code(self, fail_on: str = "ERROR") -> int:
        """Stable CI exit code given a failure threshold severity."""
        order = {"INFO": 0, "WARN": 1, "ERROR": 2}
        threshold = order.get(fail_on.upper(), 2)
        for finding in self.findings:
            if order.get(finding.severity.value, 0) >= threshold:
                return EXIT_FINDINGS
        return EXIT_OK