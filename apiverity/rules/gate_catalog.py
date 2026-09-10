"""The `SUPPRESSION-*` and `CONFIG-*` rules -- the gate talking about itself.

Every other family in `CHECK_CATALOG` describes a contract. These describe the
run: the project config that decides which findings count, and the suppressions
file that decides which of those are allowed through anyway.

They were emitted, published in `docs/ci.md`, and catalogued nowhere. So
`apiverity explain SUPPRESSION-EXPIRED` answered *"no rule with id
'SUPPRESSION-EXPIRED'"*, and `apiverity explain CONFIG-UNKNOWN-KEY` offered
`SLO-UNKNOWN-OBJECTIVE` as a near match. A reader who hit either finding and
did the documented thing got told the rule does not exist.

That matters more here than for most families, because these are the findings
that appear when somebody is *setting the gate up* -- the moment where an
unexplained error is most likely to end with the gate being removed.
"""

from __future__ import annotations

from apiverity.core.model import Severity
from apiverity.rules.check_catalog import CheckRuleSpec, spec

#: Two families rather than one: `explain` groups them separately, and a
#: reader looking up a suppression rule is doing a different job from one
#: looking up a config rule.
_SUPPRESSION = "The gate's escape hatch"
_CONFIG = "Project configuration"

GATE_CATALOG: dict[str, CheckRuleSpec] = dict(
    [
        spec(
            "SUPPRESSION-EXPIRED",
            Severity.WARN,
            "A suppression's expiry date has passed; it no longer silences anything.",
            "Fix the finding, or write a new entry with a fresh `expires` date and a "
            "reason that says what changed. An expiry is the mechanism that makes "
            "somebody look again -- extending it without a new reason is the same as "
            "never having set one.",
            produced_by="breaking",
            family=_SUPPRESSION,
        ),
        spec(
            "SUPPRESSION-INCOMPLETE",
            Severity.WARN,
            "A suppression is missing a field it needs, so it suppressed nothing.",
            "Add the fields the message names: `owner`, `reason`, and an `expires` "
            "date within the project's maximum. The entry fails closed, so the finding "
            "it named is still in the run -- this is not a second failure, it is the "
            "reason the first one is still there.",
            produced_by="breaking",
            family=_SUPPRESSION,
        ),
        spec(
            "SUPPRESSION-UNSCOPED",
            Severity.INFO,
            "A suppression silences its rule across every operation.",
            "Nothing, if that is what you meant -- an API with no pagination does not "
            "need the pagination rule on forty operations. Add an `operation_key` if it "
            "is not: a rule silenced contract-wide will not fire on the operation added "
            "next month either.",
            produced_by="breaking",
            family=_SUPPRESSION,
        ),
        spec(
            "CONFIG-UNKNOWN-KEY",
            Severity.ERROR,
            "`.apiverity.yaml` contains a key this build does not read.",
            "Fix the spelling the message suggests, or delete the key. It is an error "
            "rather than a warning because `severity_overides` (one 'r') is a typo "
            "somebody will make, and a tool that ignored it would report that nothing "
            "is wrong while the override the reader believes is active does nothing.",
            produced_by="config validate",
            family=_CONFIG,
        ),
        spec(
            "CONFIG-VERSION-MISSING",
            Severity.ERROR,
            "`.apiverity.yaml` declares no `version`.",
            "Add `version: 1`. The version is what lets a later build tell a file "
            "written for an older format from one with a mistake in it.",
            produced_by="config validate",
            family=_CONFIG,
        ),
        spec(
            "CONFIG-VERSION-UNSUPPORTED",
            Severity.ERROR,
            "The config's `version` is not one this build understands.",
            "Upgrade apiverity, or write the version this build supports. Reading a "
            "future config on a guess would apply settings whose meaning has changed.",
            produced_by="config validate",
            family=_CONFIG,
        ),
        spec(
            "CONFIG-TYPE",
            Severity.ERROR,
            "A config key holds the wrong kind of value.",
            "Give the key the shape the message names -- `severity_overrides` is a "
            "mapping of rule id to severity, not a list.",
            produced_by="config validate",
            family=_CONFIG,
        ),
        spec(
            "CONFIG-SEVERITY-INVALID",
            Severity.ERROR,
            "A severity override names something that is not a severity.",
            "Use ERROR, WARN or INFO. There is no `OFF`: a rule you do not want is a "
            "suppression with an owner and an expiry, not a severity nobody defined.",
            produced_by="config validate",
            family=_CONFIG,
        ),
        spec(
            "CONFIG-RULE-UNKNOWN",
            Severity.WARN,
            "A severity override names a rule id that is not in the catalogue.",
            "Check the id against `apiverity rules`. A typo here is silent by nature: "
            "the override applies to nothing and the rule keeps its shipped severity.",
            produced_by="config validate",
            family=_CONFIG,
        ),
        spec(
            "CONFIG-FAIL-ON-INVALID",
            Severity.ERROR,
            "`fail_on` is not one of error, warn or never.",
            "Use one of the three. There is no `off`: a gate that never fails is "
            "`never`, which reports everything and is how you adopt the gate on an API "
            "that already has history.",
            produced_by="config validate",
            family=_CONFIG,
        ),
        spec(
            "CONFIG-PROFILE-INVALID",
            Severity.ERROR,
            "`profile` names a severity profile that does not exist.",
            "Use strict, balanced or advisory. `profile` was checked for type and not "
            "for value, so `profile: strikt` validated clean and then failed the run "
            "later with `internal error: unknown severity profile`.",
            produced_by="config validate",
            family=_CONFIG,
        ),
        spec(
            "CONFIG-VALUE-INVALID",
            Severity.ERROR,
            "A config key holds a value outside the range it accepts.",
            "Use a value in range -- `suppression_max_days` is a count of days and must "
            "be at least 1, since a maximum of zero would mean no suppression could "
            "ever be written.",
            produced_by="config validate",
            family=_CONFIG,
        ),
    ]
)

__all__ = ["GATE_CATALOG"]
