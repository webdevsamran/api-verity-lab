"""The governance rules, in the catalogue that makes them explainable.

The pack these describe existed, was tested, and was executed by nothing --
along with four `SEC-*` rules that *were* published and could not fire. Rules
that run now need entries here, because a finding whose id `apiverity explain`
does not know is a finding somebody suppresses rather than reads.
"""

from __future__ import annotations

from apiverity.core.model import Severity
from apiverity.rules.check_catalog import CheckRuleSpec, spec


def _spec(
    rule_id: str, severity: Severity, description: str, instead: str
) -> tuple[str, CheckRuleSpec]:
    return spec(rule_id, severity, description, instead, "validate", "Governance")


GOVERNANCE_CATALOG: dict[str, CheckRuleSpec] = dict(
    [
        _spec(
            "GOV-UNUSED-SECURITY-SCHEME",
            Severity.INFO,
            "A security scheme is declared and required by no operation.",
            "Remove it, or require it where it applies. A scheme in the document that "
            "nothing uses tells a reader the API supports an authentication method it "
            "does not, and that reader is often the one writing a client.",
        ),
        _spec(
            "GOV-MISSING-OPERATION-ID",
            Severity.INFO,
            "An operation has no `operationId`.",
            "Give it one, unique across the document. Generated SDKs name methods from "
            "it, and without one the name is derived from the path -- so it changes "
            "whenever the path does.",
        ),
    ]
)


__all__ = ["GOVERNANCE_CATALOG"]
