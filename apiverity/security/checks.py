"""Static security-hygiene checks over a normalized contract."""

from __future__ import annotations

from apiverity.core.model import (
    Finding,
    Operation,
    Protocol,
    SecurityRequirement,
    Service,
    Severity,
)

_MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
_SENSITIVE_RESPONSE_HEADERS = {
    "set-cookie",
    "authorization",
    "proxy-authenticate",
    "www-authenticate",
}


def _effective_security(op: Operation, service: Service) -> list[SecurityRequirement] | None:
    """Operation-level security; None means inherit global; [] means anonymous."""
    if op.security is not None:
        return op.security
    return service.global_security


def run_security_checks(
    service: Service,
    *,
    require_https: bool = True,
    forbid_additional_properties: bool = False,
) -> list[Finding]:
    findings: list[Finding] = []

    for url in service.servers:
        if (
            require_https
            and url.url.startswith("http://")
            and "localhost" not in url.url
            and "127.0.0.1" not in url.url
        ):
            findings.append(
                Finding(
                    rule_id="SEC-HTTPS-POLICY",
                    severity=Severity.WARN,
                    message=f"server URL '{url.url}' uses plain HTTP; "
                    "credentials may be exposed in transit",
                    location=service.source_location,
                )
            )

    # unknown schemes referenced by requirements
    known = set(service.security_schemes)
    for op in service.operations:
        sec = _effective_security(op, service)
        if sec is None:
            continue
        for req in sec:
            if req.scheme_name and req.scheme_name not in known:
                findings.append(
                    Finding(
                        rule_id="SEC-SCHEME-UNKNOWN",
                        severity=Severity.ERROR,
                        message=f"operation '{op.key}' references undeclared "
                        f"security scheme '{req.scheme_name}'",
                        operation_key=op.key,
                        location=op.source_location,
                    )
                )

    for op in service.operations:
        sec = _effective_security(op, service)

        if sec == []:
            findings.append(
                Finding(
                    rule_id="SEC-AUTH-ANONYMOUS",
                    severity=Severity.INFO,
                    message=f"operation '{op.key}' explicitly declares anonymous access",
                    operation_key=op.key,
                    location=op.source_location,
                )
            )
        elif sec is None and not service.global_security:
            findings.append(
                Finding(
                    rule_id="SEC-AUTH-MISSING",
                    severity=Severity.WARN,
                    message=f"operation '{op.key}' declares no authentication "
                    "(neither operation-level nor global)",
                    operation_key=op.key,
                    location=op.source_location,
                )
            )
            if op.method in _MUTATING:
                findings.append(
                    Finding(
                        rule_id="SEC-UNAUTH-WRITE",
                        severity=Severity.ERROR,
                        message=f"mutating operation '{op.key}' has no authentication declaration",
                        operation_key=op.key,
                        location=op.source_location,
                    )
                )

        for resp in op.responses:
            for header in resp.headers:
                if header.lower() in _SENSITIVE_RESPONSE_HEADERS:
                    findings.append(
                        Finding(
                            rule_id="SEC-SENSITIVE-HEADER",
                            severity=Severity.INFO,
                            message=f"operation '{op.key}' response {resp.status} "
                            f"declares sensitive header '{header}'; ensure it is "
                            "intended to be documented",
                            operation_key=op.key,
                            location=resp.source_location,
                        )
                    )

    # inconsistent scheme usage across operations
    used: dict[str, set[str]] = {}
    for op in service.operations:
        sec = _effective_security(op, service)
        if sec:
            for req in sec:
                scheme = service.security_schemes.get(req.scheme_name)
                if scheme is not None:
                    used.setdefault(scheme.type, set()).add(req.scheme_name)
    if len(used) > 1:
        summary = ", ".join(f"{t}: {sorted(s)}" for t, s in sorted(used.items()))
        findings.append(
            Finding(
                rule_id="SEC-SCHEME-INCONSISTENT",
                severity=Severity.WARN,
                message=f"inconsistent security scheme types across operations ({summary})",
                location=service.source_location,
            )
        )

    # rate-limit metadata hint
    if service.protocol == Protocol.OPENAPI and service.operations:
        has_rate_limit_docs = any(
            "x-rate-limit" in (op.description or "").lower()
            or any("ratelimit" in h.lower() for r in op.responses for h in r.headers)
            for op in service.operations
        )
        if not has_rate_limit_docs:
            findings.append(
                Finding(
                    rule_id="SEC-RATE-LIMIT-METADATA",
                    severity=Severity.INFO,
                    message="no rate-limit metadata (headers or description hints) "
                    "declared anywhere in the contract",
                    location=service.source_location,
                )
            )

    # additionalProperties policy
    if forbid_additional_properties:

        def walk(schema_node: object, op_key: str) -> None:
            from apiverity.core.model import SchemaNode

            if not isinstance(schema_node, SchemaNode):
                return
            if schema_node.additional_properties is True:
                findings.append(
                    Finding(
                        rule_id="SEC-ADDL-PROPERTIES",
                        severity=Severity.WARN,
                        message=f"schema in '{op_key}' allows additionalProperties; "
                        "policy forbids open objects",
                        operation_key=op_key,
                        location=schema_node.source_location,
                    )
                )
            for child in schema_node.properties.values():
                walk(child, op_key)
            if schema_node.items is not None:
                walk(schema_node.items, op_key)

        for op in service.operations:
            if op.request_body is not None:
                for s in op.request_body.content.values():
                    walk(s, op.key)
            for r in op.responses:
                for s in r.content.values():
                    walk(s, op.key)

    return findings
