"""Whether a live MCP server asks anyone who they are.

Roughly seven thousand internet-exposed MCP servers had been catalogued by
early 2026 and about half required no authentication at all. The check that
matters is not "did my credential work" -- an authenticated probe can never
answer that -- but "what does this server hand someone with no credential at
all", which takes one extra request with the headers stripped.

Runs against the real mock over HTTP so the 401 path is a real 401 with a real
unparseable body, which is what a gateway in front of a server produces.
"""

from __future__ import annotations

from typing import Any

import pytest

from apiverity.mock.mcp_server import McpMockServer
from apiverity.runtime.mcp_auth import assess_auth_posture, presents_credentials
from apiverity.runtime.mcp_drift import detect_mcp_drift
from apiverity.specs.mcp import load_manifest

pytestmark = pytest.mark.integration

_TOKEN = "s3cret-token"  # secret-scan: allow -- a literal for the mock server
_AUTH = {"Authorization": f"Bearer {_TOKEN}"}


def _tool(name: str) -> dict[str, Any]:
    return {
        "name": name,
        "description": "Find things.",
        "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}},
    }


def _declared(*names: str):
    service, _ = load_manifest({"tools": [_tool(n) for n in names]}, label="declared")
    return service


def _by_id(findings: list[Any]) -> dict[str, Any]:
    return {f.rule_id: f for f in findings}


# ------------------------------------------------------- no credentials given


def test_an_anonymous_run_needs_no_second_request_to_prove_the_point() -> None:
    """The run already demonstrated it. Probing again would be theatre."""
    findings, posture = assess_auth_posture("http://127.0.0.1:9/mcp", tools_served=7)
    assert _by_id(findings)["MCP-AUTH-ANONYMOUS-LIST"].message.startswith(
        "the server returned all 7 tools"
    )
    assert posture["credentials_presented"] is False
    assert posture["anonymous_tool_count"] == 7


def test_the_same_fact_is_graded_by_what_the_target_is() -> None:
    """A laptop and a public host are not the same finding.

    Grading them alike is how a security check becomes noise, and noise is how
    it gets ignored on the one host where it mattered.
    """
    grades = {}
    for endpoint in (
        "http://127.0.0.1:8931/mcp",
        "https://mcp-staging.internal/mcp",
        "https://api.example.com/mcp",
    ):
        findings, _ = assess_auth_posture(endpoint, tools_served=3)
        grades[endpoint] = _by_id(findings)["MCP-AUTH-ANONYMOUS-LIST"].severity
    assert list(grades.values()) == ["INFO", "WARN", "ERROR"]


def test_every_finding_names_the_classification_it_applied() -> None:
    """So a reader who disagrees with the heuristic can see what it decided."""
    findings, _ = assess_auth_posture("https://api.example.com/mcp", tools_served=1)
    assert "production" in _by_id(findings)["MCP-AUTH-ANONYMOUS-LIST"].message


def test_plaintext_to_a_non_local_target_is_reported() -> None:
    findings, _ = assess_auth_posture("http://api.example.com/mcp", tools_served=1)
    assert "MCP-AUTH-PLAINTEXT-TRANSPORT" in _by_id(findings)


def test_plaintext_to_localhost_is_not() -> None:
    findings, _ = assess_auth_posture("http://127.0.0.1:8931/mcp", tools_served=1)
    assert "MCP-AUTH-PLAINTEXT-TRANSPORT" not in _by_id(findings)


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        ({"Authorization": "Bearer x"}, True),
        ({"x-api-key": "x"}, True),
        ({"accept-language": "en"}, False),
        (None, False),
    ],
)
def test_what_counts_as_presenting_a_credential(
    headers: dict[str, str] | None, expected: bool
) -> None:
    assert presents_credentials(headers) is expected


# ---------------------------------------------------------- credentials given


def test_a_server_that_gates_its_inventory_says_so() -> None:
    with McpMockServer([_tool("alpha")], require_auth=_TOKEN) as server:
        findings, posture = assess_auth_posture(
            server.endpoint, tools_served=1, headers=dict(_AUTH)
        )
    ids = _by_id(findings)
    assert "MCP-AUTH-ENFORCED" in ids
    assert "MCP-AUTH-ANONYMOUS-LIST" not in ids
    assert posture["anonymous_access"] == "refused-401"
    assert posture["challenge_header_present"] is True


def test_a_401_with_no_challenge_leaves_a_client_nowhere_to_go() -> None:
    with McpMockServer([_tool("alpha")], require_auth=_TOKEN, challenge=False) as server:
        findings, posture = assess_auth_posture(
            server.endpoint, tools_served=1, headers=dict(_AUTH)
        )
    assert _by_id(findings)["MCP-AUTH-NO-CHALLENGE"].severity == "WARN"
    assert posture["challenge_header_present"] is False


def test_a_credential_that_changes_nothing_is_the_finding() -> None:
    """The case an authenticated-only probe cannot see.

    The server accepts the token, so every authenticated check passes; it also
    serves the identical list to nobody at all.
    """
    tools = [_tool("alpha"), _tool("beta")]
    with McpMockServer(tools, require_auth=_TOKEN, anonymous_tools=tools) as server:
        findings, posture = assess_auth_posture(
            server.endpoint, tools_served=2, headers=dict(_AUTH)
        )
    message = _by_id(findings)["MCP-AUTH-ANONYMOUS-LIST"].message
    assert "same 2 tools with and without a credential" in message
    assert posture["anonymous_tool_count"] == 2


def test_partial_exposure_is_reported_with_both_counts() -> None:
    tools = [_tool("alpha"), _tool("beta"), _tool("gamma")]
    with McpMockServer(tools, require_auth=_TOKEN, anonymous_tools=[tools[0]]) as server:
        findings, _ = assess_auth_posture(server.endpoint, tools_served=3, headers=dict(_AUTH))
    assert "1 of 3 tools" in _by_id(findings)["MCP-AUTH-ANONYMOUS-LIST"].message


def test_an_unreachable_anonymous_probe_establishes_nothing() -> None:
    """A failed connection is not evidence of enforcement."""
    findings, posture = assess_auth_posture(
        "http://127.0.0.1:1/mcp", tools_served=1, headers=dict(_AUTH), timeout=0.5
    )
    assert "MCP-AUTH-INDETERMINATE" in _by_id(findings)
    assert posture["anonymous_access"] == "indeterminate"
    assert "not established by this run" in _by_id(findings)["MCP-AUTH-INDETERMINATE"].message


# --------------------------------------------------------------- through drift


def test_the_posture_reaches_the_drift_report() -> None:
    with McpMockServer([_tool("alpha")]) as server:
        report = detect_mcp_drift(_declared("alpha"), server.endpoint)
    assert report.auth_posture["anonymous_access"] == "served"
    assert "MCP-AUTH-ANONYMOUS-LIST" in {f.rule_id for f in report.findings}


def test_a_conformant_server_still_exits_zero_despite_the_note() -> None:
    """An INFO observation must not fail a gate, or people stop reading them."""
    from apiverity.cli.commands.runtime import _gate

    with McpMockServer([_tool("alpha")]) as server:
        report = detect_mcp_drift(_declared("alpha"), server.endpoint)
    assert {f.severity for f in report.findings} == {"INFO"}
    assert _gate(report.findings) == 0


def test_the_probe_can_be_skipped() -> None:
    with McpMockServer([_tool("alpha")]) as server:
        report = detect_mcp_drift(_declared("alpha"), server.endpoint, check_auth=False)
    assert report.auth_posture == {}
    assert not [f for f in report.findings if f.rule_id.startswith("MCP-AUTH-")]
