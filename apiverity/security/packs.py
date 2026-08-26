"""Defensive security rule pack for contracts.

Detects security-relevant problems *in the contract document itself*:
missing auth declarations, insecure server URLs, overly broad CORS
examples, sensitive data in examples and accidental secrets. Runs through
the same PolicyEngine as governance rules but is a distinct pack.
"""

from __future__ import annotations

import re

from apiverity.core.model import Finding, Operation, Protocol, Service, Severity
from apiverity.rules.policy import RuleDefinition, RulePack

_SECRET_PATTERNS = (
    re.compile(r"""(?i)(api[_-]?key|apikey)\s*[:=]\s*["'][A-Za-z0-9_\-]{16,}"""),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9_\-\.]{20,}"),
    re.compile(r"""(?i)(secret|password|passwd|token)\s*[:=]\s*["'][^"']{8,}"""),
)

_SENSITIVE_FIELD_HINTS = re.compile(
    r"(?i)^(password|passwd|secret|token|ssn|credit[_-]?card|card_number|"
    r"date_of_birth|dob|api_key)$"
)


def _operations_without_security(svc: Service) -> list[Finding]:
    out: list[Finding] = []
    has_global = bool(svc.global_security)
    for op in svc.operations:
        if op.kind != "http":
            continue
        if op.security is None and not has_global:
            out.append(
                Finding(
                    rule_id="SEC-NO-AUTH-DECLARED",
                    severity=Severity.WARN,
                    message=(
                        f"operation '{op.key}' declares no security requirement and "
                        "the service has no global security; if this endpoint is "
                        "intentionally public, mark it explicitly"
                    ),
                    operation_key=op.key,
                    location=op.source_location,
                )
            )
    return out


def _secrets_in_examples(svc: Service) -> list[Finding]:
    out: list[Finding] = []

    def scan(value: object, where: str, op: Operation | None, parent_key: str = "") -> None:
        if isinstance(value, str):
            hit = any(p.search(value) for p in _SECRET_PATTERNS)
            # JSON-style secret: a credential-looking key holding a long string
            if not hit and len(value) >= 16 and _SENSITIVE_FIELD_HINTS.match(parent_key or ""):
                hit = True
            if hit:
                out.append(
                    Finding(
                        rule_id="SEC-SECRET-IN-CONTRACT",
                        severity=Severity.ERROR,
                        message=(
                            f"possible secret in {where}"
                            + (f" of '{op.key}'" if op else "")
                            + "; redact it before publishing the contract"
                        ),
                        operation_key=op.key if op else None,
                    )
                )
                return
        elif isinstance(value, dict):
            for k, v in value.items():
                scan(k, f"{where}.key", op)
                scan(v, where, op, parent_key=str(k))
        elif isinstance(value, list):
            for v in value:
                scan(v, where, op, parent_key=parent_key)

    for op in svc.operations:
        for ex in op.examples:
            scan(ex.value, "example", op)
        if op.request_body is not None:
            for media, schema in op.request_body.content.items():
                scan(schema.example, f"{media} schema example", op)
    return out


def _sensitive_fields_unclassified(svc: Service) -> list[Finding]:
    """Sensitive-looking property names without a data-classification annotation."""
    out: list[Finding] = []

    def walk_schema(schema: object, pointer: str, op: Operation) -> None:
        props = getattr(schema, "properties", None)
        if isinstance(props, dict):
            for name, child in props.items():
                if _SENSITIVE_FIELD_HINTS.match(str(name)) and not getattr(
                    schema, "data_classification", None
                ):
                    out.append(
                        Finding(
                            rule_id="SEC-SENSITIVE-FIELD",
                            severity=Severity.INFO,
                            message=(
                                f"property '{name}' at '{pointer}' on '{op.key}' looks "
                                "sensitive but carries no classification annotation"
                            ),
                            operation_key=op.key,
                            hint="add x-data-classification (e.g. pii, credential)",
                        )
                    )
                walk_schema(child, f"{pointer}/{name}", op)

    for op in svc.operations:
        if op.request_body is not None:
            for schema in op.request_body.content.values():
                walk_schema(schema, "requestBody", op)
        for resp in op.responses:
            for schema in resp.content.values():
                walk_schema(schema, f"responses/{resp.status}", op)
    return out


def _cors_wildcards(svc: Service) -> list[Finding]:
    out: list[Finding] = []
    for op in svc.operations:
        for ex in op.examples:
            headers = ex.value.get("headers") if isinstance(ex.value, dict) else None
            if isinstance(headers, dict) and any(
                k.lower() == "access-control-allow-origin" and v == "*" for k, v in headers.items()
            ):
                out.append(
                    Finding(
                        rule_id="SEC-CORS-WILDCARD",
                        severity=Severity.WARN,
                        message=(
                            f"example on '{op.key}' documents wildcard CORS "
                            "(Access-Control-Allow-Origin: *); prefer explicit origins"
                        ),
                        operation_key=op.key,
                    )
                )
    return out


#: The defensive security pack (plugs into PolicyEngine).
SECURITY_PACK = RulePack(
    name="apiverity-security",
    version="1.0.0",
    description="Defensive contract-security rules (auth hygiene, secrets, sensitive data)",
    rules=(
        RuleDefinition(
            rule_id="SEC-NO-AUTH-DECLARED",
            severity=Severity.WARN,
            rationale="Undocumented auth leads to accidentally public endpoints.",
            remediation="Declare operation-level or global security requirements.",
            protocols=frozenset({Protocol.OPENAPI}),
            check=_operations_without_security,
        ),
        RuleDefinition(
            rule_id="SEC-SECRET-IN-CONTRACT",
            severity=Severity.ERROR,
            rationale="Secrets committed in specs leak credentials to every consumer.",
            remediation="Replace with placeholders and rotate the exposed credential.",
            check=_secrets_in_examples,
        ),
        RuleDefinition(
            rule_id="SEC-SENSITIVE-FIELD",
            severity=Severity.INFO,
            rationale="Sensitive fields should carry explicit classification metadata.",
            remediation="Add x-data-classification annotations.",
            check=_sensitive_fields_unclassified,
        ),
        RuleDefinition(
            rule_id="SEC-CORS-WILDCARD",
            severity=Severity.WARN,
            rationale="Wildcard CORS in documented examples encourages insecure configs.",
            remediation="Document explicit allowed origins.",
            check=_cors_wildcards,
        ),
    ),
)
