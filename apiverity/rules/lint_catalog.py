"""The lint rules, in the catalogue that makes them explainable.

`LintEngine` was written, tested, and called by no command -- while
`PROTOCOL_SUPPORT.md` published "Lint / governance packs -- VERIFIED" for four
protocols and `docs/capability-status.md` listed "Contract lint" as EXISTING.
It exists, and it was not running.

Rules that run need entries here: a finding whose id `apiverity explain` does
not know is a finding somebody suppresses rather than reads.

`LINT-DUP-OPID` and `LINT-NO-RESPONSES` are deliberately absent: the loader
already emits `SPEC-OPID-DUPLICATE` and `SPEC-RESPONSE-MISSING` for those
facts, and two rules for one fact is two findings a reader has to reconcile.

Every one of these is about a single revision of a contract, not about a
change between two -- which is the line that separates them from `BRK-*` and
is why they are a family rather than more of the security one.
"""

from __future__ import annotations

from apiverity.core.model import Severity
from apiverity.rules.check_catalog import CheckRuleSpec, spec


def _spec(
    rule_id: str, severity: Severity, description: str, instead: str
) -> tuple[str, CheckRuleSpec]:
    return spec(rule_id, severity, description, instead, "validate", "Lint")


LINT_CATALOG: dict[str, CheckRuleSpec] = dict(
    [
        _spec(
            "LINT-EMPTY-RESPONSE",
            Severity.INFO,
            "A 2xx response declares neither content nor headers.",
            "Nothing, if the operation really returns an empty body -- a 204 usually "
            "does. Otherwise describe what comes back: a consumer reading the contract "
            "sees an endpoint that returns nothing.",
        ),
        _spec(
            "LINT-INVALID-EXAMPLE",
            Severity.WARN,
            "An example does not validate against the schema it illustrates.",
            "Fix the example, or the schema -- one of them is wrong. An example is the "
            "part of a contract people copy, so a wrong one is a wrong request in "
            "somebody's client.",
        ),
        _spec(
            "LINT-CONTRADICTORY-REQUIRED",
            Severity.ERROR,
            "A schema requires a property it does not declare.",
            "Declare the property, or drop it from `required`. As written the schema "
            "cannot be satisfied by any document, and a validator will reject every "
            "payload including the service's own.",
        ),
        _spec(
            "LINT-AMBIGUOUS-COMPOSITION",
            Severity.WARN,
            "A composition lists several branches with nothing to tell them apart.",
            "Give the branches titles, or a discriminator. A reader -- and a code "
            "generator -- has to name these somehow, and without a hint the names come "
            "out as `Variant1`, `Variant2`.",
        ),
    ]
)


__all__ = ["LINT_CATALOG"]
