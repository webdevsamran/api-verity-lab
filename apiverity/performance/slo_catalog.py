"""What each `SLO-*` finding means, and what to do about it.

A family registers by module, so this is a table and an import rather than an
edit to a shared list. Two of these say to do nothing, and both say so
outright: an INFO with empty guidance reads as a rule nobody finished, and a
reader cannot tell that apart from a rule that wants action.
"""

from __future__ import annotations

from apiverity.core.model import Severity
from apiverity.rules.check_catalog import CheckRuleSpec, spec


def _spec(
    rule_id: str, severity: Severity, description: str, instead: str, produced_by: str
) -> tuple[str, CheckRuleSpec]:
    return spec(rule_id, severity, description, instead, produced_by, "Objectives")


SLO_CATALOG: dict[str, CheckRuleSpec] = dict(
    [
        _spec(
            "SLO-MALFORMED",
            Severity.WARN,
            "A declared objective is not a number, so nothing can be compared against it.",
            "Write it as a bare number: `p95_ms: 250`, not `p95_ms: 250ms`. This is worse "
            "than a missing objective, because it looks declared and reads as declared in "
            "a review.",
            "validate",
        ),
        _spec(
            "SLO-UNKNOWN-OBJECTIVE",
            Severity.WARN,
            "An operation declares an objective this tool does not measure.",
            "Rename it to one of the measured objectives, or accept that nothing checks "
            "it. An objective nothing compares against is a promise nobody checks.",
            "validate",
        ),
        _spec(
            "SLO-NOT-MEASURABLE",
            Severity.INFO,
            "An objective is understood and deliberately not evaluated by any run.",
            "Nothing. `availability` and `uptime_pct` are promises over a window, and a "
            "run measures the requests it made and cannot see the ones it did not -- a "
            "figure computed here would be a fabrication with a decimal point on it. "
            "Reported so silence about it is not mistaken for a pass.",
            "validate",
        ),
        _spec(
            "SLO-UNDECLARED",
            Severity.INFO,
            "An operation states no objective, in a contract where others do.",
            "Nothing, unless you meant to. An operation with no stated objective is not a "
            "defect -- it is an operation nobody promised anything about.",
            "validate",
        ),
        _spec(
            "SLO-NOT-MEASURED",
            Severity.WARN,
            "An operation declares an objective and the run measured nothing for it.",
            "Check the operation is reachable at the target. A declared objective with no "
            "measurement beside it reads as a pass, and a p95 of a connection timeout is "
            "not a latency.",
            "regression",
        ),
        _spec(
            "SLO-RUN-EXCEEDS-OBJECTIVE",
            Severity.ERROR,
            "This run measured a value past the objective the contract declares.",
            "Look at the operation -- and read the sample count first. An objective is a "
            "promise over a window and a run is a sample of it, so this is a reason to "
            "investigate rather than a judgement that the objective was missed.",
            "regression",
        ),
    ]
)


__all__ = ["SLO_CATALOG"]
