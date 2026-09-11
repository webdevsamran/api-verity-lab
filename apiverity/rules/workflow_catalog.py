"""Catalogue entries for the last families: budgets, workflows, semver, policy.

What remained after the diff lane, the parsers, the runtime probes and MCP.
They have little in common except that each was emitted by a real run and
answered by `explain` with *"no rule with id ..."*.

## Semantic versioning was half-answered, which was worse

`SEMVER-MAJOR-REQUIRED` did get an answer, through `rules/alternatives.py`:
the remediation was right and the description was the same sentence for all
five — *"The declared version does not match the changes."* True of every one
of them and useful for none, because the five differ precisely in **how** it
does not match: a version that went backwards is not the same problem as one
that did not move.

`explain` consults this catalogue before that fallback, so each now answers for
itself — and the five entries take their **remediation** from `ALTERNATIVES`
rather than restating it, because two wordings for one question drift apart at
their own pace.
"""

from __future__ import annotations

from apiverity.core.model import Severity
from apiverity.rules.check_catalog import CheckRuleSpec, spec

_BUDGET = "Agent call budgets"
_WORKFLOW = "Workflows"
_SEMVER = "Semantic versioning"
_GOVERNANCE = "Governance"
_CONSUMERS = "Consumers"

BUDGET_CATALOG: dict[str, CheckRuleSpec] = dict(
    [
        spec(
            "BUDGET-EXCEEDED",
            Severity.ERROR,
            "An operation was called more times in the window than its budget allows.",
            "Raise the limit if the traffic is expected, or find what is calling it. The "
            "single most-cited security worry about agent traffic is exactly this: too many "
            "calls, not wrong ones.",
            produced_by="budget",
            family=_BUDGET,
        ),
        spec(
            "BUDGET-FORBIDDEN",
            Severity.ERROR,
            "An operation budgeted at zero calls was called.",
            "A zero budget is a prohibition. Either the caller should not have it or the "
            "budget is wrong, and both are decisions rather than tuning.",
            produced_by="budget",
            family=_BUDGET,
        ),
        spec(
            "BUDGET-OPERATION-UNKNOWN",
            Severity.ERROR,
            "The budget names an operation the contract does not declare.",
            "Fix the key. A limit on an operation that does not exist constrains nothing "
            "and reads as though it does.",
            produced_by="budget",
            family=_BUDGET,
        ),
        spec(
            "BUDGET-UNBUDGETED",
            Severity.ERROR,
            "An operation was called and no limit covers it.",
            "Add a limit, or set the budget to allow uncovered operations. Whether this is "
            "an error depends on the budget's own mode -- an allow-list is only an "
            "allow-list if the gaps fail.",
            produced_by="budget",
            family=_BUDGET,
        ),
        spec(
            "BUDGET-UNDATED-CALLS",
            Severity.WARN,
            "Some calls carried no timestamp, so they could not be placed in a window.",
            "Capture timestamps. A per-minute limit checked against undated calls is "
            "arithmetic on an unknown denominator.",
            produced_by="budget",
            family=_BUDGET,
        ),
        spec(
            "BUDGET-UNUSED",
            Severity.INFO,
            "A limit covered nothing in this traffic.",
            "Nothing, unless the operation was expected to be called. A budget nothing "
            "exercised is a budget nothing has tested.",
            produced_by="budget",
            family=_BUDGET,
        ),
    ]
)

WORKFLOW_CATALOG: dict[str, CheckRuleSpec] = dict(
    [
        spec(
            "WF-DUP-STEP",
            Severity.ERROR,
            "Two steps in a workflow share a name.",
            "Rename one. Steps refer to each other's outputs by name, so a duplicate makes "
            "every later reference ambiguous.",
            produced_by="workflow",
            family=_WORKFLOW,
        ),
        spec(
            "WF-MISSING-VAR",
            Severity.ERROR,
            "A step uses a variable no earlier step defines.",
            "Define it, or fix the name. The step will run with an unsubstituted "
            "placeholder, which usually reaches the service as a literal.",
            produced_by="workflow",
            family=_WORKFLOW,
        ),
        spec(
            "WF-INCOMPLETE-CLEANUP",
            Severity.WARN,
            "A resource a workflow creates is never deleted in cleanup.",
            "Delete it, or say why not. A workflow run against a real environment that "
            "leaves resources behind gets run once.",
            produced_by="workflow",
            family=_WORKFLOW,
        ),
        spec(
            "WF-CLEANUP-UNKNOWN-VAR",
            Severity.ERROR,
            "Cleanup deletes a variable no step defines.",
            "Fix the name. Cleanup that names nothing deletes nothing, and the run looks "
            "tidy while the resources remain.",
            produced_by="workflow",
            family=_WORKFLOW,
        ),
    ]
)

#: What to ship instead, per semver rule. Not written here: `rules/alternatives.py`
#: already holds it, `breaking --suggest-fix` already attaches it, and a second
#: wording would be two answers to one question that drift apart at their own
#: pace.
_SEMVER_DESCRIPTIONS = {
    "SEMVER-MAJOR-REQUIRED": (
        "Breaking changes were found and the version did not move to a new major."
    ),
    "SEMVER-MINOR-REQUIRED": "Risky but non-breaking changes were found without a minor bump.",
    "SEMVER-NO-BUMP": "The contract changed materially and the version did not change at all.",
    "SEMVER-DECREASE": "The declared version went backwards.",
    "SEMVER-UNPARSEABLE": "A version is not semver, so no policy could be applied to it.",
}

_SEMVER_SEVERITIES = {
    "SEMVER-MAJOR-REQUIRED": Severity.ERROR,
    "SEMVER-MINOR-REQUIRED": Severity.WARN,
    "SEMVER-NO-BUMP": Severity.WARN,
    "SEMVER-DECREASE": Severity.ERROR,
    "SEMVER-UNPARSEABLE": Severity.WARN,
}


def _semver_catalog() -> dict[str, CheckRuleSpec]:
    """The five semver rules, taking their remediation from `ALTERNATIVES`.

    They were half-answered before, which was worse than not at all: `explain`
    found them through `rules/alternatives.py` and gave all five the same
    description -- *"The declared version does not match the changes."* True of
    every one and useful for none, because the five differ precisely in **how**
    it does not match.

    The description is written here; the remediation is imported, so there
    stays exactly one of it.
    """
    from apiverity.rules.alternatives import ALTERNATIVES

    return dict(
        spec(
            rule_id,
            _SEMVER_SEVERITIES[rule_id],
            description,
            ALTERNATIVES[rule_id],
            produced_by="breaking",
            family=_SEMVER,
        )
        for rule_id, description in _SEMVER_DESCRIPTIONS.items()
    )


SEMVER_CATALOG: dict[str, CheckRuleSpec] = _semver_catalog()

GOVERNANCE_EXTRA_CATALOG: dict[str, CheckRuleSpec] = dict(
    [
        spec(
            "POLICY-RULE-CRASHED",
            Severity.ERROR,
            "A policy rule raised while evaluating a contract.",
            "Fix the rule. Reported rather than swallowed: a pack whose rule crashes is a "
            "gate a team believes is running, and silence would be the worst available "
            "answer.",
            produced_by="rules",
            family=_GOVERNANCE,
        ),
        spec(
            "CONSUMER-UNKNOWN-OPERATION",
            Severity.ERROR,
            "A registered consumer declares it uses an operation the contract does not declare.",
            "Fix the registry or the contract. Blast-radius reporting is only as good as "
            "the registry, and an operation key that matches nothing silently drops that "
            "consumer out of every impact answer.",
            produced_by="breaking",
            family=_CONSUMERS,
        ),
    ]
)

__all__ = [
    "BUDGET_CATALOG",
    "GOVERNANCE_EXTRA_CATALOG",
    "SEMVER_CATALOG",
    "WORKFLOW_CATALOG",
]
