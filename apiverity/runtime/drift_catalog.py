"""Catalogue entries for the runtime rules.

`drift` and `ghosts` are the commands that go and look. Their findings are the
ones a reader is least able to reason about from the rule id alone — a
`GHOST-PATH-ALIVE` means something quite specific and nothing obvious — and
they were the ones `explain` could say least about: *"no rule with id ..."*.

## What these rules can and cannot establish

Half of this family exists to report the **absence** of an observation rather
than a fault, and the distinction is the whole reason they are separate rules:

* `DRIFT-UNREACHABLE` and `GHOST-UNREACHABLE` mean the probe did not complete.
  That is not evidence the service is wrong, and it is not evidence it is
  right. Reporting it as either would be the tool claiming a measurement it
  did not make.
* `GHOST-NOT-PROBED` means a write method was skipped on purpose. A route
  auditor that issued a `DELETE` to find out whether it still exists would find
  out, and so would the data.

So their remediation is not "fix this" — it is "here is how to get an answer",
which is a different sentence and the honest one.
"""

from __future__ import annotations

from apiverity.core.model import Severity
from apiverity.rules.check_catalog import CheckRuleSpec, spec

_DRIFT = "Runtime drift"
_GHOSTS = "Ghost routes"

DRIFT_CATALOG: dict[str, CheckRuleSpec] = dict(
    [
        spec(
            "DRIFT-STATUS",
            Severity.ERROR,
            "The service returned a status code the contract does not declare for that operation.",
            "Declare it, or stop returning it. A status nobody documented is one every "
            "client handles by accident.",
            produced_by="drift",
            family=_DRIFT,
        ),
        spec(
            "DRIFT-CONTENT-TYPE",
            Severity.ERROR,
            "The service returned a media type the contract does not declare.",
            "Declare it, or fix the handler. A client that negotiated on the contract will "
            "parse this with the wrong reader.",
            produced_by="drift",
            family=_DRIFT,
        ),
        spec(
            "DRIFT-SCHEMA",
            Severity.ERROR,
            "The response body does not satisfy the declared schema.",
            "The message names the position. Either the schema is out of date or the "
            "handler is, and the contract is what consumers built against.",
            produced_by="drift",
            family=_DRIFT,
        ),
        spec(
            "DRIFT-MISSING-FIELD",
            Severity.ERROR,
            "A field the contract declares required was absent from a real response.",
            "Return it, or stop declaring it required. A consumer generated from this "
            "contract has a non-optional type where the service sends nothing.",
            produced_by="drift",
            family=_DRIFT,
        ),
        spec(
            "DRIFT-UNDECLARED-FIELD",
            Severity.WARN,
            "A real response carried a field the contract does not declare.",
            "Declare it, or stop sending it. An undeclared field is one nobody reviewed, "
            "which is how personal data reaches a payload without a decision.",
            produced_by="drift",
            family=_DRIFT,
        ),
        spec(
            "DRIFT-HEADER",
            Severity.WARN,
            "A response header the contract declares was missing from a real response.",
            "Send it, or remove it from the contract. Headers carry pagination cursors and "
            "rate-limit budgets, which clients read rather than guess.",
            produced_by="drift",
            family=_DRIFT,
        ),
        spec(
            "DRIFT-RESPONSE-PII",
            Severity.WARN,
            "A response carried something shaped like personal data.",
            "Confirm the field is meant to be there and is declared as such. A shape match "
            "is a reason to look, not a finding of fact.",
            produced_by="drift",
            family=_DRIFT,
        ),
        spec(
            "DRIFT-RESPONSE-CREDENTIAL",
            Severity.ERROR,
            "A response carried something shaped like a credential.",
            "Rotate it if it is one, and stop returning it. This is the finding worth "
            "acting on before confirming, because the cost of being wrong is asymmetric.",
            produced_by="drift",
            family=_DRIFT,
        ),
        spec(
            "DRIFT-UNREACHABLE",
            Severity.ERROR,
            "The probe did not complete, so nothing was observed for this operation.",
            "Check the base URL, the network and the authentication. This is the absence "
            "of a measurement, not a fault in the service -- and not evidence the service "
            "is fine either.",
            produced_by="drift",
            family=_DRIFT,
        ),
    ]
)

GHOST_CATALOG: dict[str, CheckRuleSpec] = dict(
    [
        spec(
            "GHOST-ROUTE",
            Severity.ERROR,
            "A route answered and no contract declares it.",
            "Remove the handler, or declare the route. An endpoint nobody documented is an "
            "endpoint nobody reviewed, versioned or rate-limited on purpose.",
            produced_by="ghosts",
            family=_GHOSTS,
        ),
        spec(
            "GHOST-PATH-ALIVE",
            Severity.WARN,
            "The path answers, for a method other than the one probed.",
            "Check what is still mounted there. The route is alive even though the specific "
            "operation is not, which usually means a framework catch-all rather than a "
            "deliberate handler.",
            produced_by="ghosts",
            family=_GHOSTS,
        ),
        spec(
            "GHOST-GONE",
            Severity.INFO,
            "A route that was removed from the contract is also gone from the deployment.",
            "Nothing, this is the good outcome, and it is reported so that a clean run "
            "still shows what was checked.",
            produced_by="ghosts",
            family=_GHOSTS,
        ),
        spec(
            "GHOST-NOT-PROBED",
            Severity.INFO,
            "A candidate was skipped because its method writes.",
            "Nothing automatic. A route auditor that issued a DELETE to find out whether a "
            "route still exists would find out, and so would the data. Check it by hand if "
            "it matters.",
            produced_by="ghosts",
            family=_GHOSTS,
        ),
        spec(
            "GHOST-UNREACHABLE",
            Severity.INFO,
            "A candidate could not be probed, so this run establishes nothing about it.",
            "Check the base URL and the network, then re-run. Recorded rather than dropped "
            "because a route nobody could reach is not a route anybody confirmed gone.",
            produced_by="ghosts",
            family=_GHOSTS,
        ),
    ]
)

__all__ = ["DRIFT_CATALOG", "GHOST_CATALOG"]
