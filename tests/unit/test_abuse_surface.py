"""Rate limits, and the difference between having one and saying so.

`SEC-RATE-LIMIT-METADATA` reported, once per contract, that nothing anywhere
mentioned a limit. That is the easy half and it is nearly useless on a contract
that *does* mention one: an API with rate limiting documented on four of forty
operations passes it, and the other thirty-six are the ones a client finds out
about in production.

Two things are being guarded here beyond "does it fire".

The first is **noise discipline**. `SEC-RATE-LIMIT-NO-429` is deliberately
silent on a contract that documents no limit anywhere -- a finding on every
operation for one fact is a wall of warnings people filter out, and the
contract-level rule already says it once. It is also silent when every
operation declares 429, because then there is nothing inconsistent.

The second is **not overreaching about a draft**. `RateLimit` and
`RateLimit-Policy` come from draft-ietf-httpapi-ratelimit-headers-11, checked
2026-09-10: an active Internet-Draft, not an RFC. So the vocabulary rules are
INFO and their advice is "nothing" -- telling somebody to migrate to an
unstable target is how a linter gets switched off. `Retry-After` is the
opposite case: RFC 9110 §10.2.3, stable, and a 429 without it is a real defect,
so that one is a WARN with an instruction.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from apiverity.core.model import (
    Operation,
    OperationKind,
    Parameter,
    ParameterLocation,
    Protocol,
    Response,
    SchemaNode,
    Service,
)
from apiverity.security.abuse import run_abuse_checks
from apiverity.security.catalog import spec_for
from apiverity.specs.loader import detect_and_load

_ROOT = Path(__file__).resolve().parents[2]
_FIXTURE = _ROOT / "fixtures" / "apis" / "ratelimit" / "openapi.yaml"


def _fixture_findings() -> list:
    service, _findings, _plugin = detect_and_load(str(_FIXTURE))
    return run_abuse_checks(service)


def _ids(findings) -> list[str]:
    return [f.rule_id for f in findings]


def _service(operations: list[Operation], protocol: Protocol = Protocol.OPENAPI) -> Service:
    return Service(title="t", version="1", protocol=protocol, operations=operations)


def _op(
    method: str,
    path: str,
    *,
    responses: list[Response] | None = None,
    parameters: list[Parameter] | None = None,
) -> Operation:
    return Operation(
        kind=OperationKind.HTTP,
        method=method,
        path=path,
        responses=responses or [],
        parameters=parameters or [],
    )


# --------------------------------------------------------------- the fixture


def test_every_rule_in_this_family_fires_against_the_fixture() -> None:
    """A rule nobody can produce still gets configured, waited for, and
    trusted -- this project has found four of those."""
    fired = set(_ids(_fixture_findings()))
    assert fired == {
        "SEC-RATE-LIMIT-NO-429",
        "SEC-RATE-LIMIT-NO-RETRY-AFTER",
        "SEC-RATE-LIMIT-VENDOR-HEADERS",
        "SEC-RATE-LIMIT-LEGACY-FIELDS",
        "SEC-ABUSE-UNBOUNDED-PAGE-SIZE",
    }


def test_every_rule_in_this_family_is_explainable() -> None:
    for rule_id in set(_ids(_fixture_findings())):
        spec = spec_for(rule_id)
        assert spec is not None, f"{rule_id} is emitted and cannot be explained"
        assert spec.instead.strip()


# ------------------------------------------------------------------- the 429


def test_an_operation_with_no_429_is_named_when_its_neighbours_have_one() -> None:
    findings = [f for f in _fixture_findings() if f.rule_id == "SEC-RATE-LIMIT-NO-429"]
    assert [f.operation_key for f in findings] == ["POST /exports"]


def test_a_contract_that_documents_no_limit_anywhere_gets_no_per_operation_wall() -> None:
    """The contract-level rule already says it once. Repeating it forty times
    is a warning people learn to filter."""
    service = _service([_op("GET", "/a"), _op("GET", "/b")])
    assert "SEC-RATE-LIMIT-NO-429" not in _ids(run_abuse_checks(service))


def test_a_contract_where_every_operation_declares_429_is_silent() -> None:
    limited = [
        _op("GET", "/a", responses=[Response(status="429", headers={"Retry-After": SchemaNode()})]),
        _op("GET", "/b", responses=[Response(status="429", headers={"Retry-After": SchemaNode()})]),
    ]
    assert run_abuse_checks(_service(limited)) == []


# ----------------------------------------------------------- the Retry-After


def test_a_429_without_retry_after_is_a_warning() -> None:
    findings = [f for f in _fixture_findings() if f.rule_id == "SEC-RATE-LIMIT-NO-RETRY-AFTER"]
    keys = sorted(f.operation_key or "" for f in findings)
    assert keys == ["GET /reports", "POST /exports"]


def test_a_503_counts_too() -> None:
    """RFC 9110 defines `Retry-After` for both, and a client that cannot
    compute a backoff retries immediately either way."""
    findings = [
        f
        for f in _fixture_findings()
        if f.rule_id == "SEC-RATE-LIMIT-NO-RETRY-AFTER" and f.operation_key == "POST /exports"
    ]
    assert findings and "503" in findings[0].message


def test_a_429_that_declares_retry_after_is_not_reported() -> None:
    service = _service(
        [
            _op(
                "GET",
                "/a",
                responses=[Response(status="429", headers={"Retry-After": SchemaNode()})],
            )
        ]
    )
    assert "SEC-RATE-LIMIT-NO-RETRY-AFTER" not in _ids(run_abuse_checks(service))


def test_the_header_name_is_matched_case_insensitively() -> None:
    """HTTP field names are case-insensitive and contracts spell them every
    which way; a check that only matched one spelling would report a header
    that is right there."""
    service = _service(
        [
            _op(
                "GET",
                "/a",
                responses=[Response(status="429", headers={"retry-after": SchemaNode()})],
            )
        ]
    )
    assert "SEC-RATE-LIMIT-NO-RETRY-AFTER" not in _ids(run_abuse_checks(service))


def test_the_advice_cites_the_rfc_rather_than_asserting_it() -> None:
    finding = next(f for f in _fixture_findings() if f.rule_id == "SEC-RATE-LIMIT-NO-RETRY-AFTER")
    assert "RFC 9110" in (finding.hint or "")


# ------------------------------------------------------- the three vocabularies


def test_vendor_headers_are_recorded_not_corrected() -> None:
    """`X-RateLimit-*` is defined by nothing at all. That is worth saying and
    is not worth an instruction, because the alternative is a draft."""
    finding = next(f for f in _fixture_findings() if f.rule_id == "SEC-RATE-LIMIT-VENDOR-HEADERS")
    assert finding.severity.value == "INFO"
    assert (finding.hint or "").lower().startswith("nothing")
    assert "Internet-Draft" in (finding.hint or "")


def test_the_legacy_three_field_set_is_recorded_with_its_replacement_dated() -> None:
    finding = next(f for f in _fixture_findings() if f.rule_id == "SEC-RATE-LIMIT-LEGACY-FIELDS")
    assert finding.severity.value == "INFO"
    assert "2026-05-23" in (finding.hint or "")


def test_neither_vocabulary_rule_tells_anyone_to_migrate() -> None:
    """The replacement is an active Internet-Draft. Recommending a move to an
    unstable target is exactly how a linter gets switched off."""
    for rule_id in ("SEC-RATE-LIMIT-VENDOR-HEADERS", "SEC-RATE-LIMIT-LEGACY-FIELDS"):
        spec = spec_for(rule_id)
        assert spec is not None
        assert spec.instead.lower().startswith("nothing")


def test_a_contract_using_the_current_pair_is_not_flagged() -> None:
    """`GET /search` in the fixture declares `RateLimit` and `RateLimit-Policy`
    and draws no vocabulary finding of its own."""
    service, _f, _p = detect_and_load(str(_FIXTURE))
    search = service.find_operation("GET /search")
    assert search is not None
    headers = {name.lower() for r in search.responses for name in r.headers}
    assert {"ratelimit", "ratelimit-policy"} <= headers


# ------------------------------------------------------------- the page size


def test_an_unbounded_page_size_is_reported() -> None:
    findings = [f for f in _fixture_findings() if f.rule_id == "SEC-ABUSE-UNBOUNDED-PAGE-SIZE"]
    assert [f.operation_key for f in findings] == ["GET /search"]


def test_a_maximum_satisfies_it() -> None:
    """`GET /reports` declares `page_size` with `maximum: 200`."""
    keys = [
        f.operation_key for f in _fixture_findings() if f.rule_id == "SEC-ABUSE-UNBOUNDED-PAGE-SIZE"
    ]
    assert "GET /reports" not in keys


def test_an_enum_of_allowed_sizes_is_a_ceiling_written_differently() -> None:
    """`GET /events` takes `per_page` as an enum. A caller cannot ask for a
    million, which is the thing the rule is about."""
    keys = [
        f.operation_key for f in _fixture_findings() if f.rule_id == "SEC-ABUSE-UNBOUNDED-PAGE-SIZE"
    ]
    assert "GET /events" not in keys


@pytest.mark.parametrize("name", ["limit", "page_size", "pageSize", "per_page", "maxResults"])
def test_the_spellings_apis_actually_use_are_matched(name: str) -> None:
    service = _service(
        [
            _op(
                "GET",
                "/a",
                parameters=[
                    Parameter(
                        name=name,
                        location=ParameterLocation.QUERY,
                        schema_node=SchemaNode(type="integer"),
                    )
                ],
            )
        ]
    )
    assert "SEC-ABUSE-UNBOUNDED-PAGE-SIZE" in _ids(run_abuse_checks(service))


def test_a_path_parameter_of_the_same_name_is_not_a_page_size() -> None:
    service = _service(
        [
            _op(
                "GET",
                "/a/{limit}",
                parameters=[
                    Parameter(
                        name="limit",
                        location=ParameterLocation.PATH,
                        required=True,
                        schema_node=SchemaNode(type="integer"),
                    )
                ],
            )
        ]
    )
    assert run_abuse_checks(service) == []


def test_a_non_numeric_parameter_is_left_alone() -> None:
    """A `size` that takes "small" | "large" is not a quantity."""
    service = _service(
        [
            _op(
                "GET",
                "/a",
                parameters=[
                    Parameter(
                        name="size",
                        location=ParameterLocation.QUERY,
                        schema_node=SchemaNode(type="string"),
                    )
                ],
            )
        ]
    )
    assert run_abuse_checks(service) == []


# ----------------------------------------------------------- format applicability


@pytest.mark.parametrize("protocol", [Protocol.GRPC, Protocol.MCP, Protocol.GRAPHQL])
def test_a_format_without_status_codes_gets_no_findings_about_them(protocol: Protocol) -> None:
    """A gRPC contract has no 429 and no response headers. Reporting their
    absence would be a finding about a field the format does not have."""
    service = _service([_op("GET", "/a")], protocol=protocol)
    assert run_abuse_checks(service) == []
