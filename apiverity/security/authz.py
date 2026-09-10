"""Authorization checked between two identities, not inside one.

Every other check in this project reads a contract or watches one identity talk
to a service. Neither can see the two failures that matter most in practice,
because both are about what happens when a *different* caller asks:

- **BOLA** (OWASP API1): a resource one tenant created, read by another. The
  request is well-formed, the schema is satisfied, the status is 200, and the
  data belongs to somebody else.
- **BFLA** (OWASP API5): an operation the contract says needs a scope, answered
  for a caller who does not hold it.

Both need two credentials. `--auth-profiles` supplies them.

## What this asks the operator to state

A scope check has to know what each identity holds, and no service will tell
you truthfully -- that is the thing under test. So a profile declares its
scopes, and this compares the service's behaviour against **what the operator
says**. A finding is therefore always of the form "you told me this identity
does not hold `orders:write`, and the service accepted the call anyway".

An identity that declares no scopes is not assumed to hold none: `scopes: []`
and "not stated" are different, and only the first is a basis for a finding.
`AUTHZ-SCOPES-UNDECLARED` says so rather than silently skipping.

## What it does to the target

It creates one resource per collection as the first identity, then asks the
second identity to read, update and delete it. The create is a write, and the
probe is a deliberate unauthorized-access attempt against a service the
operator has named -- so it is gated behind `--include-mutations` and the
production acknowledgement, like every other write in this project.

It does not attempt to escalate, chain, or exploit anything it finds. A finding
records the operation, the status, and which identity made the call. There is
no payload here and there is not meant to be: the question is whether the
service enforces its own contract, and the answer is a status code.

## What a pass does not mean

A 403 from every probe means these two identities could not reach each other's
data in this run. It is not a proof about every tenant, every object, or the
identities you did not test with -- and `AUTHZ-NOT-PROBED` records every
operation the run could not reach, so a clean report is readable as what it is.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from apiverity.core.model import Finding, Operation, Service, Severity

#: A call: `(identity, method, path, body) -> (status, json body)`.
Transport = Callable[[str, str, str, Any], tuple[int, Any]]

#: Statuses that mean the service refused. 404 counts: hiding the existence of
#: another tenant's object is a legitimate and common way to deny.
DENIED = frozenset({401, 403, 404, 405, 410})


@dataclass
class Identity:
    """One caller, and what the operator says it is allowed to do."""

    name: str
    #: Scopes this identity holds. `None` means the operator did not say, which
    #: is not the same as holding none.
    scopes: list[str] | None = None


@dataclass
class AuthzReport:
    findings: list[Finding] = field(default_factory=list)
    #: `(operation_key, reason)` for everything the run could not check.
    not_probed: list[tuple[str, str]] = field(default_factory=list)
    #: How many cross-identity calls were made, so a clean report is readable
    #: as "twelve attempts, all refused" rather than as "nothing happened".
    attempts: int = 0

    @property
    def ok(self) -> bool:
        return not any(f.severity is Severity.ERROR for f in self.findings)


def probe_object_authorization(
    transport: Transport,
    collection_path: str,
    item_path: str,
    owner: Identity,
    other: Identity,
    *,
    create_payload: dict[str, Any],
    update_payload: dict[str, Any] | None = None,
    deletable: bool = True,
    report: AuthzReport | None = None,
) -> AuthzReport:
    """Create as `owner`, then try to reach it as `other`.

    The order matters: read, then update, then delete. A service that leaks on
    read and refuses the write is a different -- and much more common -- defect
    from one that lets a stranger delete, and stopping at the first finding
    would hide the second.
    """
    out = report or AuthzReport()

    status, body = transport(owner.name, "POST", collection_path, create_payload)
    if status >= 400 or not isinstance(body, dict) or body.get("id") is None:
        out.not_probed.append(
            (
                f"POST {collection_path}",
                f"nothing to probe: creating a resource as '{owner.name}' answered "
                f"{status}, so no object exists for '{other.name}' to be refused",
            )
        )
        return out

    resource = item_path.replace("{id}", str(body["id"]))
    for method, payload, rule in (
        ("GET", None, "AUTHZ-BOLA-READ"),
        ("PATCH", update_payload or create_payload, "AUTHZ-BOLA-WRITE"),
        ("DELETE", None, "AUTHZ-BOLA-DELETE"),
    ):
        if method == "DELETE" and not deletable:
            out.not_probed.append(
                (f"DELETE {item_path}", "the contract declares no DELETE on this path")
            )
            continue
        out.attempts += 1
        status, _body = transport(other.name, method, resource, payload)
        if status in DENIED:
            continue
        out.findings.append(
            Finding(
                rule_id=rule,
                severity=Severity.ERROR,
                message=(
                    f"'{other.name}' {method} {item_path} on an object created by "
                    f"'{owner.name}' and the service answered {status}"
                ),
                operation_key=f"{method} {item_path}",
                hint=(
                    "Check the handler resolves the object against the caller's tenant "
                    "rather than against the id alone. This is the shape of OWASP API1: "
                    "the request is well-formed, the schema is satisfied, and the data "
                    "belongs to somebody else."
                ),
            )
        )
    return out


def probe_function_authorization(
    transport: Transport,
    service: Service,
    identity: Identity,
    *,
    report: AuthzReport | None = None,
) -> AuthzReport:
    """Call operations this identity is not supposed to be able to call.

    Only operations whose declared security requires a scope the identity does
    not hold, and only safe methods: a BFLA probe that issued the DELETE it was
    testing for would be indistinguishable from the attack.
    """
    out = report or AuthzReport()
    if identity.scopes is None:
        out.findings.append(
            Finding(
                rule_id="AUTHZ-SCOPES-UNDECLARED",
                severity=Severity.INFO,
                message=(
                    f"identity '{identity.name}' declares no scopes, so nothing was "
                    "checked against what it is allowed to call"
                ),
                hint=(
                    "Add `scopes: []` to the profile if it genuinely holds none -- that "
                    "is a basis for a finding, and an unstated list is not."
                ),
            )
        )
        return out

    held = set(identity.scopes)
    for operation in service.operations:
        required = _required_scopes(operation, service)
        if not required:
            continue
        missing = required - held
        if not missing:
            continue
        if (operation.method or "").upper() not in ("GET", "HEAD", "OPTIONS"):
            out.not_probed.append(
                (
                    operation.key,
                    f"{operation.method} changes state; a BFLA probe that issued it "
                    "would be indistinguishable from the attack",
                )
            )
            continue
        if not operation.path or "{" in operation.path:
            out.not_probed.append(
                (operation.key, "the path is a template and this probe has no id to fill it")
            )
            continue

        out.attempts += 1
        status, _body = transport(identity.name, operation.method or "GET", operation.path, None)
        if status in DENIED:
            continue
        out.findings.append(
            Finding(
                rule_id="AUTHZ-BFLA",
                severity=Severity.ERROR,
                message=(
                    f"'{identity.name}' does not hold {sorted(missing)} and the service "
                    f"answered {status} for {operation.key}, which the contract says "
                    f"requires {sorted(required)}"
                ),
                operation_key=operation.key,
                hint=(
                    "Either the handler does not check the scope, or the profile is "
                    "wrong about what this identity holds. Both are worth knowing, and "
                    "only one of them is a defect in the service."
                ),
            )
        )
    return out


def _required_scopes(operation: Operation, service: Service) -> set[str]:
    """Scopes the contract says this operation needs.

    Operation-level security replaces the global default rather than adding to
    it, which is what `None` means on `Operation.security` -- inherit -- and
    what `[]` means: this operation is public.
    """
    requirements = operation.security if operation.security is not None else service.global_security
    return {scope for requirement in requirements or [] for scope in requirement.scopes}


__all__ = [
    "DENIED",
    "AuthzReport",
    "Identity",
    "Transport",
    "probe_function_authorization",
    "probe_object_authorization",
]
