"""Static security-hygiene checks over a normalized contract.

Two things in here were wrong for the whole life of the module, and they were
the same mistake twice: an empty list was read as a statement when it was
really an absence.

``_effective_security`` fell back to ``service.global_security``, which is a
``list`` with ``default_factory=list`` -- so a contract that declares no global
security produced ``[]``, not ``None``. Every branch downstream tested ``sec ==
[]`` first, which meant:

* ``SEC-AUTH-MISSING`` (WARN) and ``SEC-UNAUTH-WRITE`` (ERROR) were
  **unreachable**. An OpenAPI document with an unauthenticated ``POST /orders``
  and no security anywhere reported one INFO and nothing else, in a tool whose
  job is to say so.
* the INFO it did report -- "explicitly declares anonymous access" -- was a
  claim the document never made. ``security: []`` written on an operation *is*
  an explicit anonymity declaration and OpenAPI defines it as one; the model
  default that looks identical is not.

The second half is protocol coverage. Only the OpenAPI and Swagger 2.0
adapters read authentication out of a document, so on a GraphQL schema, a proto
or an MCP manifest every operation drew the same per-operation finding about
authentication the format has nowhere to declare -- one line per tool, none of
them fixable by any edit to the file. Those protocols now get one service-level
note that says which of the two situations they are in, because "this format
cannot express it" and "this adapter does not read it" are different facts and
only one of them is about the contract.
"""

from __future__ import annotations

from apiverity.core.model import (
    Finding,
    Operation,
    Protocol,
    SecurityRequirement,
    Service,
    Severity,
)
from apiverity.security.mcp_poisoning import scan_mcp_manifest

_MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
_SENSITIVE_RESPONSE_HEADERS = {
    "set-cookie",
    "authorization",
    "proxy-authenticate",
    "www-authenticate",
}

#: Protocols whose adapter in this repository reads a security requirement out
#: of the document. Only these can be asked whether an operation declares one.
_AUTH_BEARING = {Protocol.OPENAPI}

#: Protocols whose contract format has no field for an authentication
#: requirement at all. Authentication exists, but it is a property of the
#: transport or the deployment, and the document is not where it is written.
_AUTH_NOT_EXPRESSIBLE = {
    Protocol.GRAPHQL: "a GraphQL schema declares types and fields, not authentication",
    Protocol.GRPC: "a protobuf service definition declares methods, not authentication",
    Protocol.MCP: (
        "an MCP tools/list manifest declares tools, not authentication; MCP carries "
        "authorization at the transport, which `apiverity drift --base-url` can probe"
    ),
}


def _effective_security(op: Operation, service: Service) -> list[SecurityRequirement] | None:
    """The security requirement in force, or None if nothing declares one.

    ``[]`` is returned only when the *operation* wrote ``security: []``, which
    OpenAPI defines as explicit anonymous access. An empty
    ``service.global_security`` is the model's default for "the document said
    nothing" and must not be mistaken for the document saying it.
    """
    if op.security is not None:
        return op.security
    return service.global_security or None


def _authentication_findings(service: Service) -> list[Finding]:
    """Whether each operation declares an authentication requirement.

    Runs per operation only for a protocol whose adapter reads authentication
    out of the document. For everything else the answer would be "no" for every
    operation in every contract of that protocol forever, which is not a
    finding about the contract -- it is a fact about the format or about this
    loader, and it is reported once, as one of those two facts.
    """
    findings: list[Finding] = []

    if service.protocol not in _AUTH_BEARING:
        reason = _AUTH_NOT_EXPRESSIBLE.get(service.protocol)
        if reason is not None:
            findings.append(
                Finding(
                    rule_id="SEC-AUTH-NOT-EXPRESSIBLE",
                    severity=Severity.INFO,
                    message=(
                        f"authentication was not assessed: {reason}. Absence of an "
                        "authentication finding here is not evidence that this service is open"
                    ),
                    location=service.source_location,
                )
            )
        else:
            findings.append(
                Finding(
                    rule_id="SEC-AUTH-NOT-READ",
                    severity=Severity.INFO,
                    message=(
                        f"authentication was not assessed: the {service.protocol.value} adapter "
                        "in this build does not read security requirements out of the document, "
                        "so no per-operation authentication finding was computed"
                    ),
                    location=service.source_location,
                )
            )
        return findings

    for op in service.operations:
        sec = _effective_security(op, service)
        if sec == []:
            findings.append(
                Finding(
                    rule_id="SEC-AUTH-ANONYMOUS",
                    severity=Severity.INFO,
                    message=(
                        f"operation '{op.key}' declares `security: []`, which is an explicit "
                        "statement that it is open to anonymous callers"
                    ),
                    operation_key=op.key,
                    location=op.source_location,
                )
            )
        elif sec is None:
            findings.append(
                Finding(
                    rule_id="SEC-AUTH-MISSING",
                    severity=Severity.WARN,
                    message=(
                        f"operation '{op.key}' declares no authentication, and neither does the "
                        "contract globally; a reader cannot tell whether it is open or "
                        "undocumented"
                    ),
                    operation_key=op.key,
                    location=op.source_location,
                )
            )
            if op.method in _MUTATING:
                findings.append(
                    Finding(
                        # WARN, not ERROR. This rule was written as ERROR and
                        # has never fired, so nothing depends on that grade,
                        # and ERROR would be wrong: the finding is about the
                        # document, not the deployment. A gateway in front of
                        # the service may well require a token the spec never
                        # mentions. An undocumented requirement and an absent
                        # one look identical from here, and a gate that blocks
                        # a merge on a fact it cannot establish gets turned off.
                        rule_id="SEC-UNAUTH-WRITE",
                        severity=Severity.WARN,
                        message=(
                            f"mutating operation '{op.key}' has no authentication declaration; "
                            "if it is protected, say so in the contract, and if it is not, "
                            "declare `security: []` so the choice is visible"
                        ),
                        operation_key=op.key,
                        location=op.source_location,
                    )
                )
    return findings


def run_security_checks(
    service: Service,
    *,
    require_https: bool = True,
    forbid_additional_properties: bool = False,
) -> list[Finding]:
    from apiverity.security.hardening import run_hardening_checks

    # What the document *declares* that is a problem on its own -- a credential
    # in a query string, an unbounded request array, an OAuth requirement with
    # no scope. The checks below cover what it omits; these cover what it says.
    findings: list[Finding] = list(run_hardening_checks(service))

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

    findings.extend(_authentication_findings(service))

    if service.protocol is Protocol.MCP:
        # A tool description is the agent's routing input, so it gets read
        # by software rather than only by people. Nothing else in this
        # module has a subject like that.
        findings.extend(scan_mcp_manifest(service))

    for op in service.operations:
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
