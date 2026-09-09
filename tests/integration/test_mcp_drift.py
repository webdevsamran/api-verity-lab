"""Declared MCP manifest vs a live server, over a real Streamable HTTP round trip.

Runs against `apiverity.mock.mcp_server.McpMockServer` on 127.0.0.1 rather
than a stub, so JSON-RPC framing, pagination and `server/discover` are actually
exercised. A mocked transport would pass while the client spoke a protocol no
server understands.

The cases that matter here are the ones where the *honest* answer is silence:
a page cap that was hit, a server that refused our protocol revision, a legacy
server with no `server/discover`. In each of those the run did not establish
what it would need to report drift, and reporting it anyway would be the
fabrication this project treats as its worst defect.
"""

from __future__ import annotations

from typing import Any

import pytest

from apiverity.mock.mcp_server import McpMockServer
from apiverity.runtime.mcp_drift import detect_mcp_drift
from apiverity.specs.mcp import load_manifest

pytestmark = pytest.mark.integration


def _tool(name: str = "search", **overrides: Any) -> dict[str, Any]:
    tool: dict[str, Any] = {
        "name": name,
        "description": "Find things.",
        "inputSchema": {
            "type": "object",
            "required": ["query"],
            "properties": {"query": {"type": "string"}},
        },
    }
    tool.update(overrides)
    return tool


def _declared(*tools: dict[str, Any]):
    service, _ = load_manifest({"tools": list(tools)}, label="declared")
    return service


def _ids(report: Any) -> set[str]:
    return {f.rule_id for f in report.findings}


# ------------------------------------------------------------- happy path


def test_a_server_that_matches_its_manifest_reports_nothing() -> None:
    """The floor under every other assertion here."""
    tools = [_tool("alpha"), _tool("beta")]
    with McpMockServer(tools) as server:
        report = detect_mcp_drift(_declared(*tools), server.endpoint)
    assert report.findings == []
    assert report.tools_declared == report.tools_served == 2
    assert report.observation["discover_status"] == "ok"
    assert report.observation["protocol_revision"] == "2026-07-28"


# ------------------------------------------------------------------ drift


def test_a_declared_tool_that_is_not_served_is_an_error() -> None:
    with McpMockServer([_tool("alpha")]) as server:
        report = detect_mcp_drift(_declared(_tool("alpha"), _tool("beta")), server.endpoint)
    missing = [f for f in report.findings if f.rule_id == "MCP-DRIFT-TOOL-MISSING"]
    assert [f.tool for f in missing] == ["beta"]
    assert missing[0].severity == "ERROR"


def test_a_served_tool_nobody_declared_is_reported() -> None:
    """The shadow-tool case: agents discover and may call it."""
    with McpMockServer([_tool("alpha"), _tool("exfiltrate")]) as server:
        report = detect_mcp_drift(_declared(_tool("alpha")), server.endpoint)
    undeclared = [f for f in report.findings if f.rule_id == "MCP-DRIFT-TOOL-UNDECLARED"]
    assert [f.tool for f in undeclared] == ["exfiltrate"]


def test_schema_drift_carries_the_rule_that_classified_it() -> None:
    """Traceability, not just a verdict.

    The comparison runs through `diff_services` and the shared catalogue, so a
    reader can follow a drift finding back to the same rule id an OpenAPI diff
    would have produced.
    """
    declared = _declared(
        _tool(
            "alpha",
            inputSchema={
                "type": "object",
                "properties": {"mode": {"type": "string", "enum": ["a", "b"]}},
            },
        )
    )
    served = _tool(
        "alpha",
        inputSchema={"type": "object", "properties": {"mode": {"type": "string", "enum": ["a"]}}},
    )
    with McpMockServer([served]) as server:
        report = detect_mcp_drift(declared, server.endpoint)

    schema = [f for f in report.findings if f.rule_id == "MCP-DRIFT-SCHEMA"]
    assert schema, "a narrowed enum between declared and served is drift"
    assert schema[0].source_rule_id == "BRK-ENUM-NARROWED-REQUEST"
    assert schema[0].change_id and schema[0].change_id.startswith("CHG-")


def test_an_annotation_the_server_contradicts_is_reported() -> None:
    declared = _declared(_tool("alpha", annotations={"readOnlyHint": True}))
    with McpMockServer([_tool("alpha", annotations={"readOnlyHint": False})]) as server:
        report = detect_mcp_drift(declared, server.endpoint)
    assert "MCP-DRIFT-ANNOTATION" in _ids(report)


def test_presence_and_schema_do_not_report_the_same_fact_twice() -> None:
    """A missing tool is one finding, not two.

    `diff_services` calls it BRK-RPC-REMOVED and the presence check calls it
    MCP-DRIFT-TOOL-MISSING. Both are true; only one is phrased for a live
    server, and a report that says everything twice is how a tool earns
    "it found four hundred things and none of them mattered".
    """
    with McpMockServer([_tool("alpha")]) as server:
        report = detect_mcp_drift(_declared(_tool("alpha"), _tool("beta")), server.endpoint)
    for finding in report.findings:
        assert finding.source_rule_id != "BRK-RPC-REMOVED"
    assert sum(1 for f in report.findings if f.tool == "beta") == 1


# ---------------------------------------------------------- conformance


def test_a_list_result_missing_required_cache_fields_is_reported() -> None:
    with McpMockServer([_tool()], omit_cache_fields=True) as server:
        report = detect_mcp_drift(None, server.endpoint)
    assert "MCP-CONF-LIST-RESULT-INCOMPLETE" in _ids(report)


def test_conformance_runs_without_a_manifest_at_all() -> None:
    """The half that needs nothing declared: is this server well-formed?"""
    with McpMockServer([{"name": "broken", "inputSchema": {"type": "string"}}]) as server:
        report = detect_mcp_drift(None, server.endpoint)
    assert "MCP-CONF-INPUT-SCHEMA-NOT-OBJECT" in _ids(report)
    assert report.tools_declared == 0


def test_a_tool_set_that_varies_per_connection_is_an_error() -> None:
    """The specification says it MUST NOT. Only a second connection can see it."""
    with McpMockServer(
        per_connection_tools=[[_tool("alpha")], [_tool("alpha"), _tool("surprise")]]
    ) as server:
        report = detect_mcp_drift(None, server.endpoint)
    unstable = [f for f in report.findings if f.rule_id == "MCP-CONF-LIST-UNSTABLE"]
    assert unstable and unstable[0].severity == "ERROR"


def test_a_reordered_tool_list_is_information_not_an_error() -> None:
    """Deterministic order is a SHOULD, so it cannot be graded like a MUST."""
    first = [_tool("alpha"), _tool("beta")]
    with McpMockServer(per_connection_tools=[first, list(reversed(first))]) as server:
        report = detect_mcp_drift(None, server.endpoint)
    order = [f for f in report.findings if f.rule_id == "MCP-CONF-LIST-ORDER-NONDETERMINISTIC"]
    assert order and order[0].severity == "INFO"
    assert "MCP-CONF-LIST-UNSTABLE" not in _ids(report)


# ------------------------------------------------- when silence is correct


def test_hitting_the_page_cap_suppresses_every_missing_tool_finding() -> None:
    """A tool on page fifty-one is not a tool that was removed."""
    tools = [_tool(f"tool_{i}") for i in range(10)]
    declared = _declared(*tools)
    with McpMockServer(tools, page_size=2) as server:
        report = detect_mcp_drift(declared, server.endpoint, max_pages=2)

    assert report.observation["pagination_exhausted"] is False
    assert "MCP-DRIFT-PAGINATION-CAPPED" in _ids(report)
    assert "MCP-DRIFT-TOOL-MISSING" not in _ids(report), (
        "eight tools were never read, so calling them missing would be a fabrication"
    )


def test_pagination_is_followed_to_exhaustion_when_it_fits() -> None:
    tools = [_tool(f"tool_{i}") for i in range(7)]
    with McpMockServer(tools, page_size=3) as server:
        report = detect_mcp_drift(_declared(*tools), server.endpoint)
    assert report.observation["pagination_exhausted"] is True
    assert report.observation["pages_read"] == 3
    assert report.tools_served == 7
    assert report.findings == []


def test_a_refused_protocol_version_stops_before_any_tool_comparison() -> None:
    """Reporting every declared tool as missing would be a confident lie.

    The server told us it does not speak our revision. We never obtained a tool
    list, so we have established nothing about its tools.
    """
    with McpMockServer([_tool("alpha")], supported_versions=["2025-06-18"]) as server:
        report = detect_mcp_drift(_declared(_tool("alpha"), _tool("beta")), server.endpoint)

    assert _ids(report) == {"MCP-DRIFT-PROTOCOL-UNSUPPORTED"}
    assert report.tools_served == 0
    assert report.observation["server_supported_versions"] == ["2025-06-18"]


def test_a_legacy_server_is_reported_and_still_compared() -> None:
    """`tools/list` has the same shape in both eras, so the comparison holds.

    What is *not* claimed is a protocol revision: the absence of
    `server/discover` is evidence about that method, not about a version.
    """
    with McpMockServer([_tool("alpha")], implement_discover=False) as server:
        report = detect_mcp_drift(_declared(_tool("alpha")), server.endpoint)

    assert "MCP-DRIFT-LEGACY-SERVER" in _ids(report)
    assert report.observation["protocol_revision"] == "unknown"
    assert report.observation["discover_status"] == "method-not-found"
    assert report.tools_served == 1


def test_the_report_records_whether_authorization_was_presented() -> None:
    """The spec lets the tool set vary by authorization.

    A report claiming a tool is missing, from an unauthenticated probe, has to
    say it was unauthenticated -- and the header values must not reach the
    artifact.
    """
    with McpMockServer([_tool("alpha")]) as server:
        anonymous = detect_mcp_drift(_declared(_tool("alpha")), server.endpoint)
        authorised = detect_mcp_drift(
            _declared(_tool("alpha")),
            server.endpoint,
            headers={"Authorization": "Bearer sh-secret-value"},
        )

    assert anonymous.observation["authorization_presented"] is False
    assert authorised.observation["authorization_presented"] is True
    assert authorised.observation["header_names"] == ["Authorization"]
    assert "sh-secret-value" not in authorised.model_dump_json()


def test_an_unreachable_endpoint_raises_rather_than_reporting_clean() -> None:
    from apiverity.runtime.mcp_drift import McpTransportError

    with pytest.raises(McpTransportError):
        detect_mcp_drift(_declared(_tool()), "http://127.0.0.1:1/mcp", timeout=1.0)
