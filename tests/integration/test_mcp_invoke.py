"""Calling MCP tools: the gate first, the check second.

Everything else in the MCP lane reads. This is the one path that makes a server
*do* something, so most of what is asserted here is that it does not.

The inversion tests are the important ones. It is easy to write a test proving
a feature works and never write the one proving it stays off, and the failure
mode of a safety gate is silence -- it does not throw when it lets something
through.
"""

from __future__ import annotations

from typing import Any

import pytest

from apiverity.mock.mcp_server import McpMockServer
from apiverity.runtime.mcp_invoke import (
    InvokeRefused,
    build_plan,
    check_against_schema,
    invoke_tools,
)
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
        "outputSchema": {
            "type": "object",
            "required": ["hits"],
            "properties": {"hits": {"type": "array"}},
        },
    }
    tool.update(overrides)
    return tool


def _declared(*tools: dict[str, Any]):
    service, _ = load_manifest({"tools": list(tools)}, label="declared")
    return service


# ------------------------------------------------------------------- gate


def test_nothing_is_sent_without_execute() -> None:
    """The default is a plan, and a plan sends no traffic."""
    with McpMockServer([_tool()]) as server:
        report = invoke_tools(_declared(_tool()), server.endpoint, ["search"])
        assert server.calls == []
    assert report.executed is False
    assert report.calls_made == 0
    assert [step.tool for step in report.plan] == ["search"]


def test_execute_with_no_named_tool_is_refused() -> None:
    """Otherwise the server's own tool list decides what runs."""
    with pytest.raises(InvokeRefused):
        invoke_tools(_declared(_tool()), "http://127.0.0.1:1/mcp", [], execute=True)


def test_a_tool_the_manifest_does_not_declare_is_refused() -> None:
    """Names are resolved against the *declared* manifest, not the live list.

    Resolving against the server would mean a compromised server could offer a
    name and have it called.
    """
    with pytest.raises(InvokeRefused) as caught:
        build_plan(_declared(_tool("search")), ["drop_everything"])
    assert "drop_everything" in str(caught.value)


def test_a_glob_is_not_expanded_it_is_simply_unknown() -> None:
    """No pattern matching, by design. A glob hands the server the choice."""
    with pytest.raises(InvokeRefused):
        build_plan(_declared(_tool("search"), _tool("delete_all")), ["*"])


def test_a_non_local_target_needs_the_production_token() -> None:
    service = _declared(_tool())
    with pytest.raises(InvokeRefused) as caught:
        invoke_tools(service, "https://api.example.com/mcp", ["search"], execute=True)
    assert "--i-know-this-is-production" in str(caught.value)


def test_read_only_hint_does_not_authorize_a_call() -> None:
    """The inversion test that matters most.

    `readOnlyHint` is attacker-controlled data, and the specification says
    clients MUST treat annotations as untrusted unless the server is trusted.
    A tool claiming to be read-only must be no easier to invoke than any other,
    or the safest-looking tool becomes the easiest to abuse.
    """
    safe = _tool("looks_safe", annotations={"readOnlyHint": True, "destructiveHint": False})
    service = _declared(safe)
    with pytest.raises(InvokeRefused):
        invoke_tools(service, "https://api.example.com/mcp", ["looks_safe"], execute=True)

    with McpMockServer([safe]) as server:
        report = invoke_tools(service, server.endpoint, ["looks_safe"])
        assert server.calls == [], "a read-only hint must not turn a dry run into a call"
    assert report.executed is False


# --------------------------------------------------------------- execution


def test_execute_against_a_local_target_sends_exactly_the_planned_calls() -> None:
    with McpMockServer([_tool()]) as server:
        report = invoke_tools(_declared(_tool()), server.endpoint, ["search"], execute=True)
        assert [name for name, _ in server.calls] == ["search"]
    assert report.executed is True
    assert report.calls_made == 1


def test_arguments_are_generated_from_the_declared_schema_and_are_seeded() -> None:
    """Declared, not served: the question is whether the server honours what
    it published. Seeded, so a report is reproducible."""
    service = _declared(_tool())
    first = build_plan(service, ["search"], seed=7)
    again = build_plan(service, ["search"], seed=7)
    other = build_plan(service, ["search"], seed=8)
    assert first[0].arguments == again[0].arguments
    assert "query" in first[0].arguments
    assert first[0].arguments != other[0].arguments


# ------------------------------------------------------------------ checks


def test_structured_content_violating_the_output_schema_is_an_error() -> None:
    def handler(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return {
            "resultType": "complete",
            "content": [{"type": "text", "text": "ok"}],
            "structuredContent": {"hits": "not-an-array"},
        }

    with McpMockServer([_tool()], call_handler=handler) as server:
        report = invoke_tools(_declared(_tool()), server.endpoint, ["search"], execute=True)

    violations = [f for f in report.findings if f.rule_id == "MCP-DRIFT-CALL-OUTPUT-SCHEMA"]
    assert violations and violations[0].severity == "ERROR"


def test_a_finding_never_quotes_the_value_the_server_returned() -> None:
    """`validate_value` embeds the offending value; this path must not.

    Writing live response data into a committed artifact is exactly what
    docs/privacy.md promises does not happen, and a tool result is arbitrary
    production data.
    """
    # Synthetic, and the whole point of this test is that a value shaped
    # exactly like this never reaches the artifact.
    secret = "ssn-123-45-6789"  # secret-scan: allow

    def handler(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return {
            "resultType": "complete",
            "content": [],
            "structuredContent": {"hits": secret},
        }

    with McpMockServer([_tool()], call_handler=handler) as server:
        report = invoke_tools(_declared(_tool()), server.endpoint, ["search"], execute=True)

    assert report.findings, "a string where an array was declared is a violation"
    serialised = report.model_dump_json()
    assert secret not in serialised, "the server's data reached the artifact"
    assert "expected array, got string" in serialised, "the shape must still be reported"


def test_a_declared_output_schema_with_no_structured_content_is_reported() -> None:
    def handler(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return {"resultType": "complete", "content": [{"type": "text", "text": "ok"}]}

    with McpMockServer([_tool()], call_handler=handler) as server:
        report = invoke_tools(_declared(_tool()), server.endpoint, ["search"], execute=True)
    assert "MCP-DRIFT-CALL-NO-STRUCTURED-CONTENT" in {f.rule_id for f in report.findings}


def test_an_unknown_content_block_type_is_reported() -> None:
    def handler(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return {
            "resultType": "complete",
            "content": [{"type": "hologram", "data": "x"}],
            "structuredContent": {"hits": []},
        }

    with McpMockServer([_tool()], call_handler=handler) as server:
        report = invoke_tools(_declared(_tool()), server.endpoint, ["search"], execute=True)
    assert "MCP-CONF-CALL-CONTENT-BLOCK-UNKNOWN" in {f.rule_id for f in report.findings}


def test_a_tool_without_an_output_schema_is_not_faulted_for_returning_nothing() -> None:
    """No declaration means nothing to conform to."""
    bare = _tool("bare")
    bare.pop("outputSchema")

    def handler(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return {"resultType": "complete", "content": [{"type": "text", "text": "ok"}]}

    with McpMockServer([bare], call_handler=handler) as server:
        report = invoke_tools(_declared(bare), server.endpoint, ["bare"], execute=True)
    assert report.findings == []


def test_conformance_check_reports_shape_not_content() -> None:
    """Unit-level cover for the helper the privacy property rests on."""
    from apiverity.core.model import SchemaNode

    schema = SchemaNode(
        type="object",
        required=["a"],
        properties={"a": SchemaNode(type="string"), "b": SchemaNode(type="integer")},
    )
    problems = check_against_schema({"b": "oops"}, schema)
    rendered = " ".join(f"{p} {m}" for p, m in problems)
    assert "/a required property is absent" in rendered
    assert "expected integer, got string" in rendered
    assert "oops" not in rendered
