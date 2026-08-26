"""Style/policy rules engine — governance findings, not breaking changes.

A :class:`RulePack` bundles versioned rule definitions (rationale,
remediation, protocol applicability). The :class:`PolicyEngine` executes
packs against a contract revision. Policy findings are a separate category
from compatibility findings and must never be reported as breaking changes.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from apiverity.core.model import Finding, Protocol, Service, Severity


@dataclass(frozen=True)
class RuleDefinition:
    """A single governance rule inside a pack."""

    rule_id: str  # globally unique, versioned by the pack
    severity: Severity
    rationale: str
    remediation: str
    protocols: frozenset[Protocol] = field(default_factory=lambda: frozenset(Protocol))
    check: Callable[[Service], list[Finding]] = lambda svc: []


@dataclass(frozen=True)
class RulePack:
    """A versioned bundle of governance rules."""

    name: str
    version: str  # semver of the pack itself
    description: str
    rules: tuple[RuleDefinition, ...]

    def rule_ids(self) -> list[str]:
        return [r.rule_id for r in self.rules]


# -- built-in governance rules -------------------------------------------------


def _deprecated_without_sunset(svc: Service) -> list[Finding]:
    out: list[Finding] = []
    for op in svc.operations:
        if op.deprecated and op.deprecation is None:
            out.append(
                Finding(
                    rule_id="GOV-DEPRECATION-METADATA",
                    severity=Severity.WARN,
                    message=(
                        f"operation '{op.key}' is deprecated without deprecation "
                        "metadata (announced/sunset dates)"
                    ),
                    operation_key=op.key,
                    location=op.source_location,
                    hint="add x-deprecation with announcedDate and sunsetDate",
                )
            )
        elif op.deprecation is not None and not op.deprecation.sunset_date:
            out.append(
                Finding(
                    rule_id="GOV-SUNSET-MISSING",
                    severity=Severity.WARN,
                    message=f"deprecation on '{op.key}' has no sunset date",
                    operation_key=op.key,
                    location=op.source_location,
                )
            )
    return out


def _insecure_server_urls(svc: Service) -> list[Finding]:
    out: list[Finding] = []
    for server in svc.servers:
        if server.url.startswith("http://"):
            out.append(
                Finding(
                    rule_id="GOV-INSECURE-SERVER",
                    severity=Severity.WARN,
                    message=f"server URL '{server.url}' uses plaintext HTTP",
                    hint="use https:// for any non-local environment",
                )
            )
    return out


def _unused_security_schemes(svc: Service) -> list[Finding]:
    used: set[str] = set()
    for req in svc.global_security:
        used.add(req.scheme_name)
    for op in svc.operations:
        for req in op.security or []:
            used.add(req.scheme_name)
    out: list[Finding] = []
    for name in sorted(set(svc.security_schemes) - used):
        out.append(
            Finding(
                rule_id="GOV-UNUSED-SECURITY-SCHEME",
                severity=Severity.INFO,
                message=f"security scheme '{name}' is declared but never required by any operation",
            )
        )
    return out


def _missing_operation_ids(svc: Service) -> list[Finding]:
    out: list[Finding] = []
    for op in svc.operations:
        if op.kind == "http" and not op.operation_id:
            out.append(
                Finding(
                    rule_id="GOV-MISSING-OPERATION-ID",
                    severity=Severity.INFO,
                    message=f"operation '{op.key}' has no operationId; stable entity "
                    "IDs and SDK generation degrade",
                    operation_key=op.key,
                    location=op.source_location,
                )
            )
    return out


#: The default governance pack shipped with the core.
DEFAULT_PACK = RulePack(
    name="apiverity-governance",
    version="1.0.0",
    description="Baseline API governance rules (lifecycle, security hygiene, metadata)",
    rules=(
        RuleDefinition(
            rule_id="GOV-DEPRECATION-METADATA",
            severity=Severity.WARN,
            rationale="Consumers need announced/sunset dates to plan migrations.",
            remediation="Add deprecation metadata with announced and sunset dates.",
            check=_deprecated_without_sunset,
        ),
        RuleDefinition(
            rule_id="GOV-INSECURE-SERVER",
            severity=Severity.WARN,
            rationale="Plaintext HTTP exposes credentials and payloads in transit.",
            remediation="Serve non-local environments over HTTPS.",
            check=_insecure_server_urls,
        ),
        RuleDefinition(
            rule_id="GOV-UNUSED-SECURITY-SCHEME",
            severity=Severity.INFO,
            rationale="Dead security schemes mislead consumers about the auth model.",
            remediation="Remove the scheme or require it on the relevant operations.",
            check=_unused_security_schemes,
        ),
        RuleDefinition(
            rule_id="GOV-MISSING-OPERATION-ID",
            severity=Severity.INFO,
            rationale="Stable operation IDs anchor entity IDs, diffs and SDKs.",
            remediation="Set a unique operationId per operation.",
            protocols=frozenset({Protocol.OPENAPI}),
            check=_missing_operation_ids,
        ),
    ),
)


class PolicyEngine:
    """Executes rule packs against contracts."""

    def __init__(self, packs: list[RulePack] | None = None) -> None:
        self.packs = packs if packs is not None else [DEFAULT_PACK]
        self._ids: dict[str, str] = {}
        for pack in self.packs:
            for rule in pack.rules:
                prev = self._ids.setdefault(rule.rule_id, f"{pack.name}@{pack.version}")
                if prev != f"{pack.name}@{pack.version}":
                    raise ValueError(f"duplicate rule id across packs: {rule.rule_id}")

    def evaluate(self, service: Service) -> list[Finding]:
        findings: list[Finding] = []
        for pack in self.packs:
            for rule in pack.rules:
                if service.protocol not in rule.protocols:
                    continue
                try:
                    findings.extend(rule.check(service))
                except Exception as exc:  # failure isolation: one bad rule never kills the run
                    findings.append(
                        Finding(
                            rule_id="POLICY-RULE-CRASHED",
                            severity=Severity.WARN,
                            message=f"rule {rule.rule_id} raised {type(exc).__name__}: {exc}",
                        )
                    )
        return findings
