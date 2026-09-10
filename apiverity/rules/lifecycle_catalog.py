"""The `LIFECYCLE-*` rules, with what to do about each.

Kept beside the checks rather than inside them so `apiverity rules` and the
generated document can enumerate the family without importing the engine that
produces it -- the same arrangement the breaking catalogue has had since the
beginning, and the reason `explain` works for those and did not for these.
"""

from __future__ import annotations

from apiverity.core.model import Severity
from apiverity.rules.check_catalog import CheckRuleSpec, spec

_FAMILY = "Lifecycle"

LIFECYCLE_CATALOG: dict[str, CheckRuleSpec] = dict(
    [
        spec(
            "LIFECYCLE-DEPRECATED-NO-SUNSET",
            Severity.WARN,
            "An operation is deprecated and names no retirement date.",
            "Declare a `Sunset` response header (RFC 8594) or an `x-sunset` date. "
            "`deprecated: true` carries no date, so a caller cannot tell a deprecation "
            "that ends next quarter from one that has been open for six years.",
            family=_FAMILY,
        ),
        spec(
            "LIFECYCLE-DEPRECATED-NO-GUIDANCE",
            Severity.INFO,
            "A deprecated operation points nowhere.",
            "Say what to call instead, in the description or through the `deprecation` "
            "link relation RFC 9745 defines. A caller who reads the flag still has to "
            "work out the replacement, and will guess.",
            family=_FAMILY,
        ),
        spec(
            "LIFECYCLE-SUNSET-WITHOUT-DEPRECATION",
            Severity.WARN,
            "An operation declares a retirement date and is not marked deprecated.",
            "Mark it `deprecated: true`. The contract is currently retiring something it "
            "never told anyone to stop using.",
            family=_FAMILY,
        ),
        spec(
            "LIFECYCLE-SUNSET-PASSED",
            Severity.ERROR,
            "A declared sunset date has passed and the operation is still here.",
            "Remove the operation, or move the date to one the team still means. A "
            "retirement date nobody enforces teaches callers to ignore the next one.",
            family=_FAMILY,
        ),
        spec(
            "LIFECYCLE-SUNSET-BEFORE-DEPRECATION",
            Severity.ERROR,
            "The retirement date is earlier than the deprecation date.",
            "Fix the dates. RFC 9745 states a `Sunset` timestamp MUST NOT be earlier than "
            "the `Deprecation` one: a resource cannot be withdrawn before it was "
            "deprecated.",
            family=_FAMILY,
        ),
        spec(
            "LIFECYCLE-HEADER-SHAPE",
            Severity.WARN,
            "A `Sunset` or `Deprecation` header is declared in a shape its RFC does not define.",
            "`Sunset` is an HTTP-date (`Sat, 31 Dec 2018 23:59:59 GMT`, RFC 8594); "
            "`Deprecation` is a structured-field Date (`@1688169599`, RFC 9745). Neither "
            "is `format: date-time`, and a client generated from that parses a shape the "
            "server does not send.",
            family=_FAMILY,
        ),
    ]
)

__all__ = ["LIFECYCLE_CATALOG"]
