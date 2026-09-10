"""Style/policy rules engine -- governance findings, not breaking changes.

A :class:`RulePack` bundles versioned rule definitions (rationale,
remediation, protocol applicability). The :class:`PolicyEngine` executes
packs against a contract revision. Policy findings are a separate category
from compatibility findings and must never be reported as breaking changes.

## Two rules were removed from the default pack, not renamed

`GOV-DEPRECATION-METADATA` and `GOV-SUNSET-MISSING` said what
`LIFECYCLE-DEPRECATED-NO-SUNSET` says, and `GOV-INSECURE-SERVER` said what
`SEC-HTTPS-POLICY` says. Both live rules are catalogued, explainable and
reachable; the pack's versions were neither, because nothing ran this engine
at all. Wiring the pack up without removing them would have made every
plaintext server URL produce two findings for one fact.

`GOV-SUNSET-MISSING` is worth naming separately: it was emitted by the check
attached to the `GOV-DEPRECATION-METADATA` definition, so the pack emitted a
rule id it never declared, and `RulePack.rule_ids()` did not list it. A pack
whose declared ids and emitted ids differ cannot be checked against a
catalogue by either one.
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
    description="Baseline API governance rules the other families do not cover",
    rules=(
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
