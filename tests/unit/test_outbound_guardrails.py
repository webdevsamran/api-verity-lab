"""What this tool is not allowed to send to the target.

`security/leakage.py` reads what comes back. This is the other direction, and
it is the one nobody checks because synthetic data feels safe by construction.

It is not. A generated payload is built from the contract, and a contract is a
document somebody wrote. If an `example` carries a credential -- and
`security/packs.py` exists because they do -- then a fuzz run reads it out of
the repository and posts it wherever `--base-url` points. That is not a leak
the tool found; it is one the tool performed.
"""

from __future__ import annotations

from typing import Any

import pytest

from apiverity.core.model import Severity
from apiverity.fuzz.models import TestCase
from apiverity.fuzz.runner import run_cases
from apiverity.security.guardrails import DEFAULT_MAX_BYTES, Guardrails, inspect
from apiverity.specs.loader import detect_and_load

# A shape the leakage scanner identifies by its prefix, not by entropy. Not a
# real key: `AKIA` plus sixteen uppercase characters is the documented format.
_SHAPED_LIKE_A_KEY = "AKIA" + "TESTONLYTESTONLY"


def _ids(verdict: Any) -> set[str]:
    return {f.rule_id for f in verdict.findings}


# ------------------------------------------------------------- credentials


def test_a_payload_carrying_a_credential_is_not_sent() -> None:
    verdict = inspect({"api_key": _SHAPED_LIKE_A_KEY}, operation_key="POST /keys")
    assert verdict.allowed is False
    assert _ids(verdict) == {"GUARD-PAYLOAD-CREDENTIAL"}
    assert verdict.findings[0].severity is Severity.ERROR


def test_the_finding_names_the_kind_and_the_place_but_not_the_value() -> None:
    """A guardrail that printed the credential to prove it stopped it has
    copied it into a log, a CI annotation and an artifact."""
    verdict = inspect({"nested": {"api_key": _SHAPED_LIKE_A_KEY}})
    message = verdict.findings[0].message
    assert "AWS access key id" in message
    assert "api_key" in message
    assert _SHAPED_LIKE_A_KEY not in message
    assert _SHAPED_LIKE_A_KEY not in (verdict.findings[0].hint or "")


def test_the_hint_points_at_the_document_the_value_came_from() -> None:
    hint = inspect({"k": _SHAPED_LIKE_A_KEY}).findings[0].hint or ""
    assert "contract" in hint and "validate" in hint


def test_it_can_be_allowed_deliberately_and_is_still_reported() -> None:
    """A contract may legitimately declare a token field with a realistic example."""
    verdict = inspect({"k": _SHAPED_LIKE_A_KEY}, config=Guardrails(allow_credentials=True))
    assert verdict.allowed is True
    assert _ids(verdict) == {"GUARD-PAYLOAD-CREDENTIAL"}
    assert verdict.findings[0].severity is Severity.WARN
    assert "was sent" in verdict.findings[0].message


def test_an_ordinary_payload_produces_nothing() -> None:
    assert inspect({"name": "Ada", "id": "u-1"}).findings == []
    assert inspect({"name": "Ada"}).allowed is True


# -------------------------------------------------------------------- size


def test_a_payload_over_the_guardrail_is_not_sent() -> None:
    """`maxLength: 10000000` is a legal schema, and a boundary case obeys it."""
    verdict = inspect({"blob": "x" * (DEFAULT_MAX_BYTES + 10)})
    assert verdict.allowed is False
    assert _ids(verdict) == {"GUARD-PAYLOAD-SIZE"}
    assert str(DEFAULT_MAX_BYTES) in verdict.findings[0].message


def test_the_finding_says_how_big_it_was() -> None:
    verdict = inspect({"blob": "x" * 2048}, config=Guardrails(max_bytes=1024))
    assert str(verdict.size_bytes) in verdict.findings[0].message
    assert verdict.size_bytes > 2048


def test_it_is_refused_rather_than_truncated() -> None:
    """A shortened case is a case that did not test what it says it tested."""
    assert "Truncating" in (
        inspect({"b": "x" * 2048}, config=Guardrails(max_bytes=16)).findings[0].hint or ""
    )


def test_the_limit_can_be_raised() -> None:
    body = {"blob": "x" * 2048}
    assert inspect(body, config=Guardrails(max_bytes=16)).allowed is False
    assert inspect(body, config=Guardrails(max_bytes=1_000_000)).allowed is True


def test_an_unserializable_body_is_not_reported_as_enormous() -> None:
    """The send will fail on its own terms, and that belongs to the case."""
    verdict = inspect({"f": object()}, config=Guardrails(max_bytes=1))
    assert verdict.size_bytes >= 0
    assert "GUARD-PAYLOAD-SIZE" not in _ids(verdict) or verdict.size_bytes > 1


def test_no_body_is_no_finding() -> None:
    assert inspect(None).findings == []
    assert inspect(None).size_bytes == 0


def test_with_limit_leaves_the_rest_of_the_configuration_alone() -> None:
    base = Guardrails(allow_credentials=True)
    assert base.with_limit(99).allow_credentials is True
    assert base.with_limit(99).max_bytes == 99
    assert base.with_limit(None) is base


# ---------------------------------------------------------------- the run


def _case(body: Any, case_id: str = "c1") -> TestCase:
    return TestCase(
        id=case_id,
        operation_key="POST /users",
        method="POST",
        url_path="/users",
        kind="positive",
        description="a generated case",
        body=body,
        media="application/json",
        expected="2xx",
    )


def test_a_refused_case_never_reaches_the_network(tmp_path: Any) -> None:
    """No server here on purpose: reaching one would fail the test by succeeding."""
    service, _, _ = detect_and_load("fixtures/apis/crud/openapi.yaml")
    results = run_cases(
        service,
        # A port nothing listens on. If the guardrail lets the request through,
        # the result is `request failed`, not the guardrail's message.
        "http://127.0.0.1:9",
        [_case({"api_key": _SHAPED_LIKE_A_KEY})],
        timeout=1.0,
    )
    assert len(results) == 1
    assert results[0].status == "error"
    assert any("not sent" in v for v in results[0].violations)
    assert not any("request failed" in v for v in results[0].violations)
    assert results[0].duration_ms == 0


def test_one_refused_case_does_not_end_the_run() -> None:
    """A run of four hundred should lose one, not the other three hundred and
    ninety-nine."""
    service, _, _ = detect_and_load("fixtures/apis/crud/openapi.yaml")
    blocked = _case({"api_key": _SHAPED_LIKE_A_KEY})
    ordinary = _case({"name": "Ada"}, case_id="c2")
    results = run_cases(service, "http://127.0.0.1:9", [blocked, ordinary], timeout=1.0)
    assert [r.case_id for r in results] == ["c1", "c2"]
    # The second one was attempted: it failed at the socket, which is the
    # guardrail letting it through.
    assert any("request failed" in v for v in results[1].violations)


def test_the_run_carries_the_reproduction_so_it_can_be_looked_at() -> None:
    service, _, _ = detect_and_load("fixtures/apis/crud/openapi.yaml")
    results = run_cases(
        service, "http://127.0.0.1:9", [_case({"api_key": _SHAPED_LIKE_A_KEY})], timeout=1.0
    )
    assert results[0].reproduction


@pytest.mark.parametrize("allowed", [True, False])
def test_the_runner_honours_the_configuration(allowed: bool) -> None:
    service, _, _ = detect_and_load("fixtures/apis/crud/openapi.yaml")
    results = run_cases(
        service,
        "http://127.0.0.1:9",
        [_case({"api_key": _SHAPED_LIKE_A_KEY})],
        timeout=1.0,
        guardrails=Guardrails(allow_credentials=allowed),
    )
    sent = any("request failed" in v for v in results[0].violations)
    assert sent is allowed
