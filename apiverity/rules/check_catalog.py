"""Every rule that is not a breaking-change rule, in one lookup.

The breaking rules have had `CATALOG` since the beginning, which is why
`apiverity explain BRK-RESP-FIELD-REMOVED` has always worked. Everything else
had nothing: twenty-two security rules were reachable, documented nowhere, and
answered by `explain` with *"no rule with id ..."*.

They were given a catalogue of their own, and then the lifecycle checks arrived
and needed the same thing. Two catalogues with two generators and two
documents would drift; one is the whole point.

`CHECK_CATALOG` merges the families. A family registers by module, so adding a
new one is a table and an import rather than an edit to a shared list -- and
`tests/unit/test_check_catalog.py` fails when a rule is emitted without an
entry, or carries an entry nothing emits.
"""

from __future__ import annotations

from dataclasses import dataclass

from apiverity.core.model import Severity


@dataclass(frozen=True)
class CheckRuleSpec:
    """One rule: what it means, and what to do about it."""

    rule_id: str
    severity: Severity
    #: What the finding says, in one line.
    description: str
    #: What to do. Not "consider reviewing" -- the specific edit, where there is
    #: one, and an honest "nothing, this is a note" where there is not.
    instead: str
    #: Which command produces it.
    produced_by: str = "validate"
    #: The section this rule appears under in `docs/check-rules.md`, for any
    #: rule the generator's prefix table does not claim.
    #:
    #: The prefix table exists because the security family is 27 rules doing
    #: five distinct jobs and one heading over all of them helps nobody. This
    #: field covers everything else -- and it had no reader at all until the
    #: generator was changed to use it, which is why two SEC rules added after
    #: that table was written sat under a heading called "Other".
    family: str = "Security"


def spec(
    rule_id: str,
    severity: Severity,
    description: str,
    instead: str,
    produced_by: str = "validate",
    family: str = "Security",
) -> tuple[str, CheckRuleSpec]:
    return rule_id, CheckRuleSpec(rule_id, severity, description, instead, produced_by, family)


def catalog() -> dict[str, CheckRuleSpec]:
    """Every family, merged.

    Imported inside the function so a family module can import this one for
    `spec` without a cycle.
    """
    from apiverity.diff.compat_catalog import (
        COMPAT_CATALOG,
        GRAPHQL_COMPAT_CATALOG,
        PROTO_CATALOG,
    )
    from apiverity.diff.sdk_catalog import SDK_CATALOG
    from apiverity.performance.slo_catalog import SLO_CATALOG
    from apiverity.rules.gate_catalog import GATE_CATALOG
    from apiverity.rules.lifecycle_catalog import LIFECYCLE_CATALOG
    from apiverity.rules.lint_catalog import LINT_CATALOG
    from apiverity.rules.policy_catalog import GOVERNANCE_CATALOG
    from apiverity.rules.workflow_catalog import (
        BUDGET_CATALOG,
        GOVERNANCE_EXTRA_CATALOG,
        SEMVER_CATALOG,
        WORKFLOW_CATALOG,
    )
    from apiverity.runtime.drift_catalog import DRIFT_CATALOG, GHOST_CATALOG
    from apiverity.runtime.mcp_catalog import merged as mcp_catalog
    from apiverity.runtime.semantic_catalog import SEMANTIC_CATALOG
    from apiverity.security.authz_catalog import AUTHZ_CATALOG
    from apiverity.security.catalog import SECURITY_CATALOG
    from apiverity.security.guardrail_catalog import GUARDRAIL_CATALOG
    from apiverity.specs.graphql.federation_catalog import FEDERATION_CATALOG
    from apiverity.specs.spec_catalog import (
        ASYNCAPI_CATALOG,
        SPEC_CATALOG,
        SWAGGER2_CATALOG,
    )

    merged: dict[str, CheckRuleSpec] = {}
    merged.update(SECURITY_CATALOG)
    merged.update(LIFECYCLE_CATALOG)
    merged.update(SEMANTIC_CATALOG)
    merged.update(SLO_CATALOG)
    merged.update(GOVERNANCE_CATALOG)
    merged.update(LINT_CATALOG)
    merged.update(GATE_CATALOG)
    merged.update(AUTHZ_CATALOG)
    merged.update(SDK_CATALOG)
    merged.update(GUARDRAIL_CATALOG)
    merged.update(FEDERATION_CATALOG)
    merged.update(COMPAT_CATALOG)
    merged.update(GRAPHQL_COMPAT_CATALOG)
    merged.update(PROTO_CATALOG)
    merged.update(SPEC_CATALOG)
    merged.update(SWAGGER2_CATALOG)
    merged.update(ASYNCAPI_CATALOG)
    merged.update(DRIFT_CATALOG)
    merged.update(GHOST_CATALOG)
    merged.update(mcp_catalog())
    merged.update(BUDGET_CATALOG)
    merged.update(WORKFLOW_CATALOG)
    merged.update(SEMVER_CATALOG)
    merged.update(GOVERNANCE_EXTRA_CATALOG)
    return merged


__all__ = ["CheckRuleSpec", "catalog", "spec"]
