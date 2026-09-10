"""The `SEMANTIC-*` rules, with what to do about each.

None of these is a defect on its own, which makes the "instead" column harder
and more important than usual. A field that stopped being populated may be a
feature nobody uses any more; the finding's job is to make that a decision
rather than an accident, so every entry here says what to *check*, not what to
change.
"""

from __future__ import annotations

from apiverity.core.model import Severity
from apiverity.rules.check_catalog import CheckRuleSpec, spec

_FAMILY = "Behaviour"
_BY = "drift --corpus --against-corpus"

SEMANTIC_CATALOG: dict[str, CheckRuleSpec] = dict(
    [
        spec(
            "SEMANTIC-FIELD-ABANDONED",
            Severity.ERROR,
            "An optional field was populated in almost every response and is now populated "
            "in none.",
            "Find out whether the service stopped setting it or the data went away. The "
            "schema still declares it, so nothing else reports this -- and every consumer "
            "reading it now gets nothing. If it is deliberate, remove it from the contract "
            "so the removal is a breaking change somebody reviews.",
            produced_by=_BY,
            family=_FAMILY,
        ),
        spec(
            "SEMANTIC-FIELD-INTERMITTENT",
            Severity.WARN,
            "A field that was almost always present is now present much less often.",
            "Check whether it is now conditional on something. A consumer that treated it "
            "as always-there is reading it sometimes, and will not notice until the branch "
            "that needed it runs.",
            produced_by=_BY,
            family=_FAMILY,
        ),
        spec(
            "SEMANTIC-FIELD-APPEARED",
            Severity.INFO,
            "A field that was never present is now present in almost every response.",
            "Nothing, unless the contract does not declare it -- in which case declare it. "
            "Additive, and recorded because an undeclared field consumers start relying on "
            "is the next breaking change.",
            produced_by=_BY,
            family=_FAMILY,
        ),
        spec(
            "SEMANTIC-VALUE-GONE",
            Severity.WARN,
            "A value the field used to return no longer appears.",
            "Check whether that state is still reachable. The schema still permits the "
            "value, so a consumer with a branch for it has dead code and no way to find "
            "out; if the state is gone for good, narrow the enum so the removal is "
            "reviewed.",
            produced_by=_BY,
            family=_FAMILY,
        ),
        spec(
            "SEMANTIC-VALUE-NEW",
            Severity.WARN,
            "A field started returning a value it never returned before.",
            "Check the contract declares it. A consumer that switched exhaustively on the "
            "old set now falls through, and a value absent from the enum is a contract "
            "violation nobody is validating.",
            produced_by=_BY,
            family=_FAMILY,
        ),
        spec(
            "SEMANTIC-NULL-RATE-ROSE",
            Severity.WARN,
            "A field is null far more often than it used to be.",
            "Find out what stopped populating it. Nullable is nullable, so no schema check "
            "objects -- and the meaning of the response changed anyway.",
            produced_by=_BY,
            family=_FAMILY,
        ),
    ]
)

__all__ = ["SEMANTIC_CATALOG"]
