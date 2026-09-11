"""Deprecation with a date attached, or without one.

`deprecated: true` is the whole of what OpenAPI says about retiring an
operation. It carries no date, no migration target and no obligation, so a
contract can be deprecating something for six years and look identical on the
day it is switched off. The checks here are about the difference between a
deprecation that is a *plan* and one that is an intention.

The two RFCs, read 2026-09-10
-----------------------------
**RFC 9745**, "The Deprecation HTTP Response Header Field" (Standards Track,
March 2025). `Deprecation` is an Item Structured Header whose value is a Date:
`Deprecation: @1688169599`. It defines the `deprecation` link relation, for
documentation aimed at people.

**RFC 8594**, "The Sunset HTTP Header Field" (Informational, May 2019).
`Sunset = HTTP-date`, in the RFC 7231 format:
`Sunset: Sat, 31 Dec 2018 23:59:59 GMT`. It defines the `sunset` link relation.

The two use **different date formats**, which is the trap worth checking for:
one is a structured-field Date carrying Unix seconds, the other is an
HTTP-date. A contract declaring either as `format: date-time` has described a
third thing that neither RFC defines, and a client generated from it will parse
the wrong shape.

RFC 9745 also states that a `Sunset` timestamp MUST NOT be earlier than the
`Deprecation` one -- a resource cannot be withdrawn before it was deprecated.

What is checked, and from where
-------------------------------
A contract has nowhere standard to write the *dates*; those live in the headers
at runtime. So a date is read from whatever the document actually carries: an
`x-sunset` / `x-deprecation` extension on the operation, or an `example` or
`default` on the declared header. Both are things people really write, and
neither is invented here.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from typing import Any

from apiverity.core.model import Finding, Operation, SchemaNode, Service, Severity

#: Response header names, matched case-insensitively as HTTP requires.
SUNSET_HEADER = "sunset"
DEPRECATION_HEADER = "deprecation"

#: Extensions carrying the dates. `x-sunset` is in wide use; `x-deprecation`
#: is its counterpart. Read rather than required: a contract that says nothing
#: is reported as saying nothing, not corrected.
_SUNSET_KEYS = ("x-sunset", "x-sunset-date")
_DEPRECATION_KEYS = ("x-deprecation", "x-deprecated-at", "x-deprecation-date")

#: Words that make a description count as migration guidance. Deliberately
#: narrow: "deprecated" alone is the fact, not the guidance, and matching it
#: would silence the check on every operation it applies to.
_GUIDANCE_MARKERS = ("http://", "https://", "migrat", "instead", "replaced by", "use `")


def _headers(op: Operation) -> dict[str, SchemaNode]:
    """Every declared response header, lower-cased, across all responses."""
    out: dict[str, SchemaNode] = {}
    for response in op.responses:
        for name, schema in response.headers.items():
            out.setdefault(name.lower(), schema)
    return out


def _parse_date(value: Any) -> date | None:
    """A date from any of the shapes a contract might write it in.

    Three formats are accepted because three are in use: the HTTP-date RFC 8594
    specifies, the ISO 8601 people reach for, and the Unix seconds RFC 9745's
    structured-field Date carries. Refusing two of them would make the date
    checks fire on correct contracts, which is worse than not checking.
    """
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return datetime.fromtimestamp(float(value), tz=UTC).date()
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.startswith("@"):  # structured-field Date
        try:
            return datetime.fromtimestamp(float(text[1:]), tz=UTC).date()
        except ValueError:
            return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(text).date()
    except (TypeError, ValueError):
        return None


def _declared_date(op: Operation, keys: tuple[str, ...], header: str) -> date | None:
    """The date this operation states, from an extension or a header example.

    The structured block first. `x-deprecation` is read here as a flat date
    *and* published in the wild as an object with `sunset` and `guide` inside
    it -- and reading only the flat form reported "names no retirement date"
    about a contract that names one, which is the kind of false positive that
    gets a governance rule switched off.
    """
    from apiverity.rules.migration import deprecation_of

    info = deprecation_of(op)
    if info is not None:
        structured = info.sunset_date if header == SUNSET_HEADER else info.announced_date
        found = _parse_date(structured)
        if found is not None:
            return found

    for key in keys:
        found = _parse_date(op.extensions.get(key))
        if found is not None:
            return found
    schema = _headers(op).get(header)
    if schema is not None:
        for candidate in (schema.example, schema.default):
            found = _parse_date(candidate)
            if found is not None:
                return found
    return None


def _has_guidance(op: Operation) -> bool:
    from apiverity.rules.migration import deprecation_of

    text = f"{op.description or ''} {op.summary or ''}".lower()
    if any(marker in text for marker in _GUIDANCE_MARKERS):
        return True
    # A `deprecation` or `sunset` link relation is the RFCs' own answer, and a
    # `guide` inside a structured `x-deprecation` block is the same answer
    # written the other common way. Reading only the flat keys reported
    # "points nowhere" about contracts that point somewhere.
    info = deprecation_of(op)
    if info is not None and (info.migration_guide or info.consumer_impact):
        return True
    return any(
        key in op.extensions for key in ("x-deprecation-link", "x-sunset-link", "x-migration")
    )


def _bad_header_shape(schema: SchemaNode, header: str) -> str | None:
    """Why this declared header cannot carry what its RFC defines."""
    if schema.type in {"integer", "number"} and header == SUNSET_HEADER:
        return "an HTTP-date is a string, not a number"
    if schema.type not in (None, "string", "integer", "number"):
        return f"declared as {schema.type!r}"
    fmt = (schema.format or "").lower()
    if header == SUNSET_HEADER and fmt in {"date-time", "date"}:
        return (
            "declared as `format: date-time`, which is ISO 8601; RFC 8594 specifies an "
            "HTTP-date (`Sat, 31 Dec 2018 23:59:59 GMT`)"
        )
    if header == DEPRECATION_HEADER and fmt in {"date-time", "date"}:
        return (
            "declared as `format: date-time`, which is ISO 8601; RFC 9745 specifies a "
            "structured-field Date (`@1688169599`)"
        )
    return None


def _operation_findings(op: Operation, today: date) -> list[Finding]:
    findings: list[Finding] = []
    headers = _headers(op)
    has_sunset_header = SUNSET_HEADER in headers
    sunset = _declared_date(op, _SUNSET_KEYS, SUNSET_HEADER)
    deprecated_at = _declared_date(op, _DEPRECATION_KEYS, DEPRECATION_HEADER)

    if op.deprecated:
        if not has_sunset_header and sunset is None:
            findings.append(
                Finding(
                    rule_id="LIFECYCLE-DEPRECATED-NO-SUNSET",
                    severity=Severity.WARN,
                    message=(
                        f"operation '{op.key}' is deprecated and names no retirement date. "
                        "`deprecated: true` carries none, so a caller cannot tell a "
                        "deprecation that ends next quarter from one that has been open for "
                        "six years -- declare a `Sunset` response header (RFC 8594) or an "
                        "`x-sunset` date"
                    ),
                    operation_key=op.key,
                    location=op.source_location,
                )
            )
        if not _has_guidance(op):
            findings.append(
                Finding(
                    rule_id="LIFECYCLE-DEPRECATED-NO-GUIDANCE",
                    severity=Severity.INFO,
                    message=(
                        f"operation '{op.key}' is deprecated and points nowhere. A caller who "
                        "reads the flag still has to work out what to call instead; RFC 9745 "
                        "defines a `deprecation` link relation for exactly this"
                    ),
                    operation_key=op.key,
                    location=op.source_location,
                )
            )
    elif has_sunset_header or sunset is not None:
        findings.append(
            Finding(
                rule_id="LIFECYCLE-SUNSET-WITHOUT-DEPRECATION",
                severity=Severity.WARN,
                message=(
                    f"operation '{op.key}' declares a retirement date and is not marked "
                    "`deprecated`. The contract is retiring something it never told anyone "
                    "to stop using"
                ),
                operation_key=op.key,
                location=op.source_location,
            )
        )

    if sunset is not None and sunset < today:
        findings.append(
            Finding(
                rule_id="LIFECYCLE-SUNSET-PASSED",
                severity=Severity.ERROR,
                message=(
                    f"operation '{op.key}' declares a sunset date of {sunset.isoformat()}, "
                    "which has passed. Either the operation should be gone or the date should "
                    "be one the team still means -- a retirement date nobody enforces teaches "
                    "callers to ignore the next one"
                ),
                operation_key=op.key,
                location=op.source_location,
            )
        )

    if sunset is not None and deprecated_at is not None and sunset < deprecated_at:
        findings.append(
            Finding(
                rule_id="LIFECYCLE-SUNSET-BEFORE-DEPRECATION",
                severity=Severity.ERROR,
                message=(
                    f"operation '{op.key}' is retired on {sunset.isoformat()} and deprecated on "
                    f"{deprecated_at.isoformat()}. RFC 9745 states a `Sunset` timestamp MUST "
                    "NOT be earlier than the `Deprecation` one: a resource cannot be withdrawn "
                    "before it was deprecated"
                ),
                operation_key=op.key,
                location=op.source_location,
            )
        )

    for header in (SUNSET_HEADER, DEPRECATION_HEADER):
        schema = headers.get(header)
        if schema is None:
            continue
        problem = _bad_header_shape(schema, header)
        if problem:
            findings.append(
                Finding(
                    rule_id="LIFECYCLE-HEADER-SHAPE",
                    severity=Severity.WARN,
                    message=(
                        f"operation '{op.key}' declares a `{header.title()}` header {problem}. "
                        "A client generated from this parses a shape the server does not send"
                    ),
                    operation_key=op.key,
                    location=op.source_location,
                )
            )

    return findings


def run_lifecycle_checks(service: Service, *, today: date | None = None) -> list[Finding]:
    """Every lifecycle check, in operation order.

    `today` is injectable because a date check that reads the clock is a test
    that passes until one particular morning.
    """
    when = today or datetime.now(UTC).date()
    findings: list[Finding] = []
    for op in service.operations:
        findings.extend(_operation_findings(op, when))
    return findings


__all__ = ["run_lifecycle_checks"]
