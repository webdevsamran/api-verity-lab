"""The `AUTHZ-*` rules -- authorization checked between two identities.

Separate from `SECURITY_CATALOG` because these are not statements about a
document. Every other security rule is something `validate` can see by reading
a contract; each of these is the answer a running service gave when a second
identity asked for the first one's data.
"""

from __future__ import annotations

from apiverity.core.model import Severity
from apiverity.rules.check_catalog import CheckRuleSpec, spec

_FAMILY = "Authorization, between identities"

AUTHZ_CATALOG: dict[str, CheckRuleSpec] = dict(
    [
        spec(
            "AUTHZ-BOLA-READ",
            Severity.ERROR,
            "One identity read an object another identity created.",
            "Resolve the object against the caller's tenant, not against the id alone. "
            "This is OWASP API1: the request is well-formed, the schema is satisfied, "
            "the status is 200, and the data belongs to somebody else -- which is why no "
            "schema check and no single-identity run can see it.",
            produced_by="test --authz",
            family=_FAMILY,
        ),
        spec(
            "AUTHZ-BOLA-WRITE",
            Severity.ERROR,
            "One identity updated an object another identity created.",
            "The same fix as the read, and worse if only this one fires: a service that "
            "hides another tenant's object from a GET and accepts a PATCH on it is "
            "checking visibility somewhere that is not the write path.",
            produced_by="test --authz",
            family=_FAMILY,
        ),
        spec(
            "AUTHZ-BOLA-DELETE",
            Severity.ERROR,
            "One identity deleted an object another identity created.",
            "The same fix. Reported separately from the read because stopping at the "
            "first finding would hide this one, and they are not equally bad.",
            produced_by="test --authz",
            family=_FAMILY,
        ),
        spec(
            "AUTHZ-BFLA",
            Severity.ERROR,
            "An operation answered for a caller the contract says lacks its scope.",
            "Either the handler does not check the scope, or the profile is wrong about "
            "what that identity holds. Both are worth knowing and only one of them is a "
            "defect in the service, so check the profile before filing a bug.",
            produced_by="test --authz",
            family=_FAMILY,
        ),
        spec(
            "AUTHZ-SCOPES-UNDECLARED",
            Severity.INFO,
            "An identity states no scopes, so nothing checked what it may call.",
            "Add `scopes: []` to the profile if it genuinely holds none. An unstated "
            "list is not a basis for a finding -- assuming an identity holds nothing "
            "would report every operation it can reach as a defect.",
            produced_by="test --authz",
            family=_FAMILY,
        ),
    ]
)

__all__ = ["AUTHZ_CATALOG"]
