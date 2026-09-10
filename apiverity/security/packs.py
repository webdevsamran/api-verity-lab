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


def _no_security_schemes(svc: Service) -> list[Finding]:
    """The contract declares no security schemes at all -- once, not per
    operation.

    This used to be per-operation and duplicated `SEC-AUTH-MISSING`, which
    already says "this operation declares no authentication, and neither does
    the contract". Two rules for one fact is two findings a reader has to
    reconcile, and the catalogue entry for this id has always described the
    contract-level check, not the per-operation one. It now does what it says.
    """
    if svc.security_schemes or svc.global_security:
        return []
    if not svc.operations:
        return []
    return [
        Finding(
            rule_id="SEC-NO-AUTH-DECLARED",
            severity=Severity.WARN,
            message=(
                f"this contract declares no security schemes at all, across "
                f"{len(svc.operations)} operation(s)"
            ),
            location=svc.source_location,
            hint=(
                "Declare the schemes the service uses under `components.securitySchemes`, "
                "or say in the description that it is public. The `SEC-AUTH-MISSING` "
                "findings beside this one are the same fact, once per operation -- this "
                "is the line that says it about the document."
            ),
        )
    ]


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


#: The header a wildcard origin is declared under.
_CORS_ORIGIN = "access-control-allow-origin"


def _declared_wildcard(schema: object) -> bool:
    """Does this header's schema pin the value to `*`?

    A header schema says what the service returns in the three ways a schema
    can pin a value: `example`, `default`, and `const`. A single-member `enum`
    is a fourth, and means the same thing.
    """
    for attribute in ("example", "default", "const"):
        if getattr(schema, attribute, None) == "*":
            return True
    enum = getattr(schema, "enum", None)
    return isinstance(enum, list) and enum == ["*"]


def _cors_wildcards(svc: Service) -> list[Finding]:
    out: list[Finding] = []
    # The declared response header. This is where a wildcard origin actually
    # appears in an OpenAPI document, and the check below reads `op.examples`,
    # which this parser populates from an operation-level `examples` key that
    # no version of OpenAPI defines -- so on a standard document the rule was
    # reachable in principle and not in practice.
    for op in svc.operations:
        for response in op.responses:
            for name, schema in response.headers.items():
                if name.lower() != _CORS_ORIGIN or not _declared_wildcard(schema):
                    continue
                out.append(
                    Finding(
                        rule_id="SEC-CORS-WILDCARD",
                        severity=Severity.WARN,
                        message=(
                            f"operation '{op.key}' declares "
                            f"`Access-Control-Allow-Origin: *` on response {response.status}"
                        ),
                        operation_key=op.key,
                        location=response.source_location or op.source_location,
                        hint=(
                            "Name the origins the service allows. A wildcard cannot be used "
                            "with credentialed requests at all, so a contract that documents "
                            "one is either wrong or describing an endpoint that must stay "
                            "anonymous."
                        ),
                    )
                )
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
            remediation="Declare the security schemes the service uses.",
            protocols=frozenset({Protocol.OPENAPI}),
            check=_no_security_schemes,
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
