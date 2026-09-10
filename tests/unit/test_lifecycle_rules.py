"""Deprecation with a date attached, or without one.

`deprecated: true` is the whole of what OpenAPI says about retiring an
operation: no date, no migration target, no obligation. A contract can be
deprecating something for six years and look identical on the day it is
switched off, which is why the flag alone is not a plan.

The two RFCs, read 2026-09-10, and the trap between them:

- **RFC 9745** (Standards Track, March 2025) — `Deprecation` is a
  structured-field Date: `@1688169599`.
- **RFC 8594** (Informational, May 2019) — `Sunset` is an HTTP-date:
  `Sat, 31 Dec 2018 23:59:59 GMT`.

Two headers about the same subject, in two different formats, neither of them
`format: date-time`. That is the mistake worth a rule.

Every date test injects `today`. A check that reads the clock is a test that
passes until one particular morning.
"""

from __future__ import annotations

from datetime import date

from apiverity.core.model import (
    Operation,
    Protocol,
    Response,
    SchemaNode,
    Service,
)
from apiverity.rules.lifecycle import run_lifecycle_checks
from apiverity.security import run_security_checks

TODAY = date(2026, 9, 10)


def _service(*operations: Operation) -> Service:
    return Service(
        title="fixture",
        version="1.0.0",
        protocol=Protocol.OPENAPI,
        operations=list(operations),
    )


def _op(**kwargs: object) -> Operation:
    base: dict[str, object] = {
        "operation_id": "getThing",
        "method": "GET",
        "path": "/things/{id}",
    }
    base.update(kwargs)
    return Operation(**base)  # type: ignore[arg-type]


def _with_headers(headers: dict[str, SchemaNode], **kwargs: object) -> Operation:
    return _op(responses=[Response(status="200", headers=headers)], **kwargs)


def _rules(*operations: Operation) -> dict[str, str]:
    return {f.rule_id: f.message for f in run_lifecycle_checks(_service(*operations), today=TODAY)}


# ------------------------------------------------------- a deprecation plan


def test_a_deprecation_with_no_date_is_reported() -> None:
    fired = _rules(_op(deprecated=True))
    assert "LIFECYCLE-DEPRECATED-NO-SUNSET" in fired
    assert "six years" in fired["LIFECYCLE-DEPRECATED-NO-SUNSET"]


def test_a_declared_sunset_header_satisfies_it() -> None:
    """The header is where the date lives at runtime.

    Declaring it is the contract saying a date exists, which is the thing a
    caller can act on even before they know what it is.
    """
    op = _with_headers({"Sunset": SchemaNode(type="string")}, deprecated=True)
    assert "LIFECYCLE-DEPRECATED-NO-SUNSET" not in _rules(op)


def test_the_header_name_is_matched_case_insensitively() -> None:
    """HTTP header names are case-insensitive, and contracts spell them every way."""
    op = _with_headers({"sunset": SchemaNode(type="string")}, deprecated=True)
    assert "LIFECYCLE-DEPRECATED-NO-SUNSET" not in _rules(op)


def test_an_x_sunset_extension_satisfies_it() -> None:
    op = _op(deprecated=True, extensions={"x-sunset": "2027-01-01"})
    assert "LIFECYCLE-DEPRECATED-NO-SUNSET" not in _rules(op)


def test_an_operation_that_is_not_deprecated_draws_nothing() -> None:
    assert _rules(_op()) == {}


# ------------------------------------------------------------- the dates


def test_a_sunset_date_that_has_passed_is_an_error() -> None:
    op = _op(deprecated=True, extensions={"x-sunset": "2020-01-01"})
    fired = _rules(op)
    assert "LIFECYCLE-SUNSET-PASSED" in fired
    assert "2020-01-01" in fired["LIFECYCLE-SUNSET-PASSED"]


def test_a_future_sunset_date_is_not_an_error() -> None:
    assert "LIFECYCLE-SUNSET-PASSED" not in _rules(
        _op(deprecated=True, extensions={"x-sunset": "2099-01-01"})
    )


def test_a_sunset_before_its_deprecation_is_an_error() -> None:
    """RFC 9745: a `Sunset` timestamp MUST NOT be earlier than the
    `Deprecation` one. A resource cannot be withdrawn before it was
    deprecated."""
    op = _op(
        deprecated=True,
        extensions={"x-sunset": "2027-01-01", "x-deprecation": "2028-01-01"},
    )
    fired = _rules(op)
    assert "LIFECYCLE-SUNSET-BEFORE-DEPRECATION" in fired
    assert "RFC 9745" in fired["LIFECYCLE-SUNSET-BEFORE-DEPRECATION"]


def test_a_sunset_after_its_deprecation_is_fine() -> None:
    op = _op(
        deprecated=True,
        extensions={"x-deprecation": "2027-01-01", "x-sunset": "2028-01-01"},
    )
    assert "LIFECYCLE-SUNSET-BEFORE-DEPRECATION" not in _rules(op)


def test_a_retirement_date_without_a_deprecation_is_reported() -> None:
    """The contract is retiring something it never told anyone to stop using."""
    op = _op(extensions={"x-sunset": "2099-01-01"})
    assert "LIFECYCLE-SUNSET-WITHOUT-DEPRECATION" in _rules(op)


# ---------------------------------------------------------- date formats


def test_every_format_a_contract_might_write_the_date_in_is_read() -> None:
    """Three formats are in use, and refusing two would make the date checks
    fire on correct contracts -- which is worse than not checking."""
    for value in (
        "2020-01-01",  # ISO 8601, what people reach for
        "Sat, 31 Dec 2018 23:59:59 GMT",  # HTTP-date, what RFC 8594 specifies
        "@1546300799",  # structured-field Date, what RFC 9745 specifies
        1546300799,  # the same, as a number
    ):
        op = _op(deprecated=True, extensions={"x-sunset": value})
        assert "LIFECYCLE-SUNSET-PASSED" in _rules(op), value


def test_an_unparseable_date_is_not_treated_as_passed() -> None:
    """Reporting "your sunset date has passed" about `soon` would be inventing
    a fact, and the operation still draws the no-date finding it deserves."""
    op = _op(deprecated=True, extensions={"x-sunset": "soon"})
    fired = _rules(op)
    assert "LIFECYCLE-SUNSET-PASSED" not in fired
    assert "LIFECYCLE-DEPRECATED-NO-SUNSET" in fired


def test_a_header_example_counts_as_a_declared_date() -> None:
    op = _with_headers(
        {"Sunset": SchemaNode(type="string", example="2020-01-01")},
        deprecated=True,
    )
    assert "LIFECYCLE-SUNSET-PASSED" in _rules(op)


# --------------------------------------------------------- header shapes


def test_a_sunset_header_declared_as_date_time_is_reported() -> None:
    """RFC 8594 specifies an HTTP-date. `format: date-time` is ISO 8601, and a
    client generated from it parses a shape the server does not send."""
    op = _with_headers(
        {"Sunset": SchemaNode(type="string", format="date-time")},
        deprecated=True,
    )
    fired = _rules(op)
    assert "LIFECYCLE-HEADER-SHAPE" in fired
    assert "RFC 8594" in fired["LIFECYCLE-HEADER-SHAPE"]


def test_a_deprecation_header_declared_as_date_time_names_its_own_rfc() -> None:
    """The two headers are wrong in different ways, and a message naming the
    wrong RFC sends the reader to the wrong page."""
    op = _with_headers(
        {
            "Sunset": SchemaNode(type="string"),
            "Deprecation": SchemaNode(type="string", format="date-time"),
        },
        deprecated=True,
    )
    assert "RFC 9745" in _rules(op)["LIFECYCLE-HEADER-SHAPE"]


def test_a_plain_string_header_is_not_reported() -> None:
    op = _with_headers({"Sunset": SchemaNode(type="string")}, deprecated=True)
    assert "LIFECYCLE-HEADER-SHAPE" not in _rules(op)


def test_a_numeric_sunset_header_is_reported() -> None:
    op = _with_headers({"Sunset": SchemaNode(type="integer")}, deprecated=True)
    assert "LIFECYCLE-HEADER-SHAPE" in _rules(op)


# -------------------------------------------------------------- guidance


def test_a_deprecation_that_points_nowhere_is_a_note() -> None:
    fired = _rules(_op(deprecated=True))
    assert "LIFECYCLE-DEPRECATED-NO-GUIDANCE" in fired


def test_a_description_naming_the_replacement_satisfies_it() -> None:
    op = _op(deprecated=True, description="Use `GET /v2/things` instead.")
    assert "LIFECYCLE-DEPRECATED-NO-GUIDANCE" not in _rules(op)


def test_the_word_deprecated_alone_is_not_guidance() -> None:
    """It is the fact, not the answer. Matching it would silence this check on
    every operation it applies to."""
    op = _op(deprecated=True, description="This endpoint is deprecated.")
    assert "LIFECYCLE-DEPRECATED-NO-GUIDANCE" in _rules(op)


def test_a_migration_link_satisfies_it() -> None:
    op = _op(deprecated=True, extensions={"x-deprecation-link": "https://docs.test/migrate"})
    assert "LIFECYCLE-DEPRECATED-NO-GUIDANCE" not in _rules(op)


# ------------------------------------------------------------ integration


def test_the_checks_run_as_part_of_validate() -> None:
    """A check nobody invokes is a check nobody has."""
    fired = {f.rule_id for f in run_security_checks(_service(_op(deprecated=True)))}
    assert "LIFECYCLE-DEPRECATED-NO-SUNSET" in fired


def test_the_clock_is_injectable() -> None:
    """Otherwise this suite passes until one particular morning."""
    op = _op(deprecated=True, extensions={"x-sunset": "2026-09-11"})
    tomorrow = {f.rule_id for f in run_lifecycle_checks(_service(op), today=date(2026, 9, 12))}
    today = {f.rule_id for f in run_lifecycle_checks(_service(op), today=TODAY)}
    assert "LIFECYCLE-SUNSET-PASSED" in tomorrow
    assert "LIFECYCLE-SUNSET-PASSED" not in today
