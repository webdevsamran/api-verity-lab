"""Six things a contract can say that are a problem on their own.

The existing checks cover what a document *omits* -- no authentication, no
rate-limit metadata, a wildcard CORS header. These cover what it *declares*:
a credential in a query string, an unbounded array on a request, an OAuth
requirement with no scope on it. Each of them is a decision someone wrote down,
and each is fixable by editing the line the finding points at.

The bar for adding a check here
-------------------------------
Every rule below is unambiguous from the model alone. That rules out several
things this project could plausibly check and deliberately does not:

**Unbounded strings.** Most strings in most contracts have no `maxLength` and
should not: a description field bounded at 256 characters is a bug waiting to
happen. Firing on all of them would produce hundreds of findings per contract,
and a check that produces hundreds of findings is a check that gets switched
off, taking the five useful ones with it. Arrays are different -- they are far
rarer, and an unbounded array is a request whose *size* is unbounded, which is
the thing that costs money.

**Mass assignment.** Guessing that a request field named `role` is
server-controlled is guessing. A contract where `role` is a legitimate input is
an ordinary contract, and a finding that is wrong half the time trains people
to ignore the half that is right.

Both are named here so their absence is a decision on the record.

Mapped to the OWASP API Security Top 10 (2023) by
`apiverity/reports/compliance.py`, which reads the rule-id prefixes.
"""

from __future__ import annotations

from apiverity.core.model import (
    Finding,
    Operation,
    ParameterLocation,
    SchemaNode,
    SecurityRequirement,
    Service,
    Severity,
)

#: Parameter names that mean "this response is paginated". Matched
#: case-insensitively against the whole name, not as a substring: `limited` is
#: not `limit`, and a substring match here would quietly excuse an operation
#: that has no pagination at all.
_PAGINATION_PARAMS = frozenset(
    {
        "limit",
        "offset",
        "page",
        "pagesize",
        "page_size",
        "per_page",
        "perpage",
        "cursor",
        "after",
        "before",
        "start",
        "count",
        "top",
        "skip",
        "max_results",
        "maxresults",
        "page_token",
        "pagetoken",
    }
)

#: Scope names that grant everything the token can do. A required scope from
#: this set makes the per-operation scope declaration decorative: every caller
#: holding it can call every operation.
_BROAD_SCOPES = frozenset(
    {
        "*",
        "all",
        "admin",
        "root",
        "superuser",
        "full",
        "full_access",
        "full-access",
        "read_write",
        "read-write",
        "write:all",
        "read:all",
        "api",
        "openid profile email",
    }
)

_READ_METHODS = frozenset({"GET", "HEAD"})


def _effective(op: Operation, service: Service) -> list[SecurityRequirement]:
    """The requirements that apply to this operation."""
    if op.security is not None:
        return op.security
    return list(service.global_security)


def _walk(schema: SchemaNode | None, path: str = "") -> list[tuple[str, SchemaNode]]:
    """Every node in a schema, with a readable path. Cycle-safe by identity."""
    out: list[tuple[str, SchemaNode]] = []
    seen: set[int] = set()

    def visit(node: SchemaNode | None, where: str) -> None:
        if node is None or id(node) in seen:
            return
        seen.add(id(node))
        out.append((where or ".", node))
        for name, child in node.properties.items():
            visit(child, f"{where}.{name}")
        visit(node.items, f"{where}[]")
        for index, child in enumerate(node.prefix_items or []):
            visit(child, f"{where}[{index}]")
        for attr in ("one_of", "any_of", "all_of"):
            for index, child in enumerate(getattr(node, attr) or []):
                visit(child, f"{where}/{attr}[{index}]")

    visit(schema, path)
    return out


# --------------------------------------------------------------- the checks


def _unbounded_request_arrays(op: Operation) -> list[Finding]:
    """Arrays a caller can send with no declared ceiling.

    OWASP API4 (unrestricted resource consumption). The cost is not the array
    itself -- it is what the server does per element, which is where an
    unbounded list becomes an unbounded amount of work paid for by the person
    running the API.
    """
    if op.request_body is None:
        return []
    offenders: list[str] = []
    for media_type, schema in sorted(op.request_body.content.items()):
        for where, node in _walk(schema, media_type):
            if node.type == "array" and node.max_items is None:
                offenders.append(where)
    if not offenders:
        return []
    shown = ", ".join(offenders[:5])
    more = f" (and {len(offenders) - 5} more)" if len(offenders) > 5 else ""
    return [
        Finding(
            rule_id="SEC-ARRAY-UNBOUNDED",
            severity=Severity.WARN,
            message=(
                f"operation '{op.key}' accepts an array with no `maxItems`: {shown}{more}. "
                "The cost is not the array, it is the work done per element -- declare a "
                "ceiling, or say in the description that the server enforces one"
            ),
            operation_key=op.key,
            location=op.source_location,
        )
    ]


def _unpaginated_collections(op: Operation) -> list[Finding]:
    """A read that returns a list and offers no way to ask for less of it."""
    if (op.method or "").upper() not in _READ_METHODS:
        return []
    names = {p.name.lower().replace("-", "_") for p in op.parameters}
    if names & _PAGINATION_PARAMS:
        return []
    if {n.replace("_", "") for n in names} & _PAGINATION_PARAMS:
        return []

    for response in op.responses:
        if not str(response.status).startswith("2"):
            continue
        for schema in response.content.values():
            if schema is not None and schema.type == "array":
                return [
                    Finding(
                        rule_id="SEC-COLLECTION-UNPAGINATED",
                        severity=Severity.WARN,
                        message=(
                            f"operation '{op.key}' returns an array and declares no "
                            "pagination parameter. The response size is then a function of "
                            "the data, which is the one input the caller does not control "
                            "and the operator cannot bound"
                        ),
                        operation_key=op.key,
                        location=op.source_location,
                    )
                ]
    return []


def _credential_placement(service: Service) -> list[Finding]:
    """Where the contract says to put the credential."""
    findings: list[Finding] = []
    for name, scheme in sorted(service.security_schemes.items()):
        if scheme.type == "apiKey" and scheme.location == ParameterLocation.QUERY:
            findings.append(
                Finding(
                    rule_id="SEC-APIKEY-IN-QUERY",
                    severity=Severity.ERROR,
                    message=(
                        f"security scheme '{name}' carries the API key in the query string. "
                        "URLs are written to access logs, proxy logs, browser history and "
                        "`Referer` headers by default -- a credential there is a credential "
                        "in a dozen places nobody is guarding. Move it to a header"
                    ),
                    location=service.source_location,
                )
            )
        if scheme.type == "http" and (scheme.scheme or "").lower() == "basic":
            findings.append(
                Finding(
                    rule_id="SEC-BASIC-AUTH",
                    severity=Severity.WARN,
                    message=(
                        f"security scheme '{name}' is HTTP Basic, so every request carries a "
                        "reusable password that cannot be scoped, rotated per client, or "
                        "revoked without changing it for everyone"
                    ),
                    location=service.source_location,
                )
            )
    return findings


def _scope_findings(service: Service) -> list[Finding]:
    """Whether the scopes an operation requires narrow anything."""
    findings: list[Finding] = []
    unscoped: list[str] = []
    broad: dict[str, list[str]] = {}

    for op in service.operations:
        for requirement in _effective(op, service):
            scheme = service.security_schemes.get(requirement.scheme_name)
            if scheme is None or scheme.type != "oauth2":
                continue
            if not requirement.scopes:
                # Only when the scheme declares scopes: a scheme with none has
                # nothing to narrow, and reporting that would be reporting the
                # absence of a feature the document never used.
                if scheme.scopes:
                    unscoped.append(op.key)
                continue
            for scope in requirement.scopes:
                if scope.strip().lower() in _BROAD_SCOPES:
                    broad.setdefault(scope, []).append(op.key)

    if unscoped:
        shown = ", ".join(sorted(unscoped)[:5])
        more = f" (and {len(unscoped) - 5} more)" if len(unscoped) > 5 else ""
        findings.append(
            Finding(
                rule_id="SEC-SCOPE-UNSCOPED",
                severity=Severity.WARN,
                message=(
                    f"{len(unscoped)} operation(s) require OAuth 2.0 but name no scope, on a "
                    f"scheme that declares some: {shown}{more}. Any valid token then opens "
                    "them, whatever it was issued for"
                ),
                location=service.source_location,
            )
        )

    for scope, operations in sorted(broad.items()):
        shown = ", ".join(sorted(operations)[:5])
        more = f" (and {len(operations) - 5} more)" if len(operations) > 5 else ""
        findings.append(
            Finding(
                rule_id="SEC-SCOPE-BROAD",
                severity=Severity.WARN,
                message=(
                    f"scope '{scope}' grants everything, so requiring it on {shown}{more} "
                    "makes the per-operation scope declaration decorative: one token opens "
                    "the whole surface"
                ),
                location=service.source_location,
            )
        )
    return findings


def run_hardening_checks(service: Service) -> list[Finding]:
    """Every check in this module, in a stable order."""
    findings: list[Finding] = []
    findings.extend(_credential_placement(service))
    findings.extend(_scope_findings(service))
    for op in service.operations:
        findings.extend(_unbounded_request_arrays(op))
        findings.extend(_unpaginated_collections(op))
    return findings


__all__ = ["run_hardening_checks"]
