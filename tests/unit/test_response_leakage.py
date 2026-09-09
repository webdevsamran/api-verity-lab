"""Credentials in a live response, reported without ever recording one.

Two secret checks already exist here and neither looks at a running service.
`scripts/secret_scan.py` reads the repository; `security/packs.py` reads a
contract. Neither can see a token echoed into an error message by the API
itself, which is the one that is live.

The constraint that shapes every test below: the finding has to be actionable
without the value. A scanner that prints the token it found to prove it found
one has copied a live credential into a file, a log and a CI annotation.
"""

from __future__ import annotations

import pytest

from apiverity.core.model import Severity
from apiverity.security.leakage import scan_body, scan_headers, scan_response, scan_text

# Assembled rather than written out, so `scripts/secret_scan.py` -- which
# reads this repository's own files -- does not have to be told to ignore a
# line. An exemption marker is a thing someone later copies onto a real one.
_AWS = "AKIA" + "IOSFODNN7EXAMPLE"[:16]
_GITHUB = "ghp_" + "a" * 36
_STRIPE = "sk_live_" + "0123456789abcdefgh"
_JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dBjftJeZ4CVPmB92K27uhbUJU1p1r_wW1g"


@pytest.mark.parametrize(
    ("value", "kind"),
    [
        (_AWS, "AWS access key id"),
        (_GITHUB, "GitHub token"),
        ("xoxb" + "-1234567890-abcdefghij", "Slack token"),
        (_STRIPE, "Stripe secret key"),
        ("AIza" + "b" * 35, "Google API key"),
        ("sk-" + "c" * 40, "OpenAI-style API key"),
        ("sk-ant-" + "d" * 30, "Anthropic API key"),
        ("-----BEGIN RSA " + "PRIVATE KEY-----", "private key block"),
        (_JWT, "JSON Web Token"),
    ],
)
def test_each_known_credential_shape_is_recognised(value: str, kind: str) -> None:
    leaks = scan_text(f"the value is {value} ok")
    assert kind in {leak.kind for leak in leaks}


def test_a_finding_never_contains_the_credential() -> None:
    """The single requirement this module exists to satisfy."""
    findings = scan_response({"debug": {"aws_key": _AWS}})
    assert findings
    for finding in findings:
        assert _AWS not in finding.message


def test_a_finding_says_where_and_how_long_instead() -> None:
    (finding,) = scan_response({"debug": {"aws_key": _AWS}})
    assert "/debug/aws_key" in finding.message
    assert f"({len(_AWS)} characters)" in finding.message
    assert finding.severity is Severity.ERROR


def test_a_finding_tells_the_reader_to_rotate_it() -> None:
    (finding,) = scan_response({"k": _GITHUB})
    assert "rotate it" in finding.message


def test_a_pointer_escapes_the_way_json_pointer_says_to() -> None:
    leaks = scan_body({"a/b": {"c~d": _AWS}})
    assert [leak.pointer for leak in leaks] == ["/a~1b/c~0d"]


def test_a_credential_inside_an_array_is_found_by_index() -> None:
    leaks = scan_body({"items": ["fine", {"token": _GITHUB}]})
    assert [leak.pointer for leak in leaks] == ["/items/1/token"]


def test_ordinary_data_is_not_a_credential() -> None:
    body = {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "sha": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "note": "Bearer with me, this is prose.",
        "count": 12,
    }
    assert scan_body(body) == []


def test_there_is_no_entropy_rule_on_purpose() -> None:
    """A thumbnail, a UUID, a content hash and a session token look alike.

    A check that fires on all four is a check nobody keeps switched on.
    """
    assert scan_text("Zm9vYmFyYmF6cXV4cXV1eGNvcmdlZ3JhdWx0Z2FycGx5") == []


def test_the_same_credential_twice_is_one_finding_per_place() -> None:
    leaks = scan_text(f"{_AWS} and again {_AWS}")
    assert len(leaks) == 1


def test_an_authorization_header_coming_back_is_a_leak() -> None:
    leaks = scan_headers({"Authorization": "Bearer abc123", "content-type": "application/json"})
    assert [leak.kind for leak in leaks] == ["authorization response header"]


def test_a_set_cookie_header_is_not_flagged() -> None:
    """That is how sessions work; flagging it makes the rule useless."""
    assert scan_headers({"set-cookie": "session=abc; HttpOnly"}) == []


def test_a_credential_in_any_header_value_is_found() -> None:
    leaks = scan_headers({"x-debug-context": f"key={_STRIPE}"})
    assert [leak.kind for leak in leaks] == ["Stripe secret key"]


def test_a_deeply_nested_body_does_not_run_away() -> None:
    body: dict[str, object] = {"leaf": _AWS}
    for _ in range(60):
        body = {"next": body}
    assert scan_body(body) == []


def test_findings_are_ordered_deterministically() -> None:
    body = {"b": _GITHUB, "a": _AWS}
    assert [f.message.split(" at ")[1].split(" ")[0] for f in scan_response(body)] == ["/a", "/b"]


# ------------------------------------------------------------------- wiring


def test_the_corpus_analyser_reports_a_credential_in_a_recorded_response() -> None:
    """A HAR is real production traffic, and redaction ran before this."""
    from apiverity.core.model import (
        Operation,
        OperationKind,
        Protocol,
        Response,
        SchemaNode,
        Service,
    )
    from apiverity.runtime.corpus_drift import analyze_corpus

    service = Service(
        title="t",
        version="1",
        protocol=Protocol.OPENAPI,
        operations=[
            Operation(
                kind=OperationKind.HTTP,
                method="GET",
                path="/me",
                operation_id="me",
                responses=[
                    Response(
                        status="200",
                        content={"application/json": SchemaNode(type="object")},
                    )
                ],
            )
        ],
    )
    entries = [
        {
            "method": "GET",
            "url": "https://api.example.com/me",
            "status": 200,
            "response_mime": "application/json",
            "response_body": {"debug_token": _GITHUB},
        }
    ]
    report = analyze_corpus(service, entries, source="t.har")
    credential = [f for f in report.findings if f.rule_id == "DRIFT-RESPONSE-CREDENTIAL"]
    assert credential and credential[0].severity == "ERROR"
    assert _GITHUB not in report.model_dump_json()


def test_an_mcp_tool_result_carrying_a_credential_is_reported() -> None:
    """It would enter the agent's context on every call."""
    from apiverity.runtime.mcp_invoke import InvokePlan, _check_result

    step = InvokePlan(tool="lookup", arguments={}, declares_output_schema=False)
    findings = _check_result(step, {"content": [{"type": "text", "text": _STRIPE}]}, None)
    assert [f.rule_id for f in findings] == ["MCP-CALL-RESULT-CREDENTIAL"]
    assert _STRIPE not in findings[0].message
