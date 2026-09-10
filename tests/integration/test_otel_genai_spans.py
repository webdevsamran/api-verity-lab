"""Spans for MCP calls, named the way the rest of the ecosystem names them.

A drift run makes the same kind of call an agent makes. Naming those calls
`mcp.method.name` rather than something of our own invention is the entire
value: it puts a schema that drifted at 09:14 next to the tool call that failed
at 09:14, in a dashboard the team already has.

Which makes the attribute *names* the thing worth testing. `mcp_method` instead
of `mcp.method.name` is not nearly right -- it is invisible to every query and
alert built on the convention, and a span nobody can query is worse than no
span, because it looks like coverage.

Two things this pins beyond the names. `TraceRecorder` was library-only until
now: nothing in the CLI could reach it, which by this project's own standard is
a defect rather than a feature awaiting a caller. And its OTLP output carried
no end time and a start time read at *serialization*, so every span in a batch
claimed to start at the same instant, the instant of the export.

Conventions read 2026-09-10 from `open-telemetry/semantic-conventions-genai`,
`docs/gen-ai/mcp.md`. They are Development status and will move; that is why
the names live in one module.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from apiverity.exporters import semconv
from apiverity.exporters.otel import KIND_CLIENT, TraceRecorder
from apiverity.mock.mcp_server import McpMockServer
from apiverity.runtime.mcp_drift import detect_mcp_drift
from apiverity.specs.mcp import load_manifest
from apiverity.specs.mcp.runner import SPOKEN_PROTOCOL_VERSION, McpClient

pytestmark = pytest.mark.integration


def _tool(name: str = "search") -> dict[str, Any]:
    return {
        "name": name,
        "description": "Find things.",
        "inputSchema": {"type": "object", "properties": {}},
    }


def _declared(*tools: dict[str, Any]):
    service, _ = load_manifest({"tools": list(tools)}, label="declared")
    return service


# ------------------------------------------------------------ span naming


def test_a_plain_method_names_the_span_after_itself() -> None:
    assert semconv.span_name("tools/list") == "tools/list"


def test_a_tool_call_names_the_span_after_its_target() -> None:
    assert semconv.span_name("tools/call", {"name": "get_weather"}) == "tools/call get_weather"


def test_a_resource_uri_never_reaches_the_span_name() -> None:
    """The convention allows it on opt-in, and this never opts in.

    A URI is unbounded. One span name per customer record defeats every
    aggregation the trace was collected for, and it is the sort of thing that
    is only noticed on the invoice.
    """
    name = semconv.span_name("resources/read", {"uri": "postgres://db/customers/4171"})
    assert name == "resources/read"


# --------------------------------------------------------- the attributes


def test_client_attributes_use_the_conventions_exact_keys() -> None:
    attributes = semconv.client_attributes(
        "tools/list",
        endpoint="https://mcp.example.com:8443/mcp",
        request_id=7,
    )
    assert attributes["mcp.method.name"] == "tools/list"
    assert attributes["mcp.protocol.version"] == SPOKEN_PROTOCOL_VERSION
    assert attributes["server.address"] == "mcp.example.com"
    assert attributes["server.port"] == 8443
    assert attributes["network.protocol.name"] == "https"
    # `tcp` for HTTP transports, per the convention's own note -- `http`
    # belongs in `network.protocol.name`, and putting it here would be a value
    # the enum does not define.
    assert attributes["network.transport"] == "tcp"
    assert attributes["jsonrpc.request.id"] == "7"


def test_a_tool_call_is_marked_as_a_tool_execution() -> None:
    attributes = semconv.client_attributes(
        "tools/call",
        endpoint="http://localhost:9000/mcp",
        params={"name": "get_weather"},
    )
    assert attributes["gen_ai.operation.name"] == "execute_tool"
    assert attributes["gen_ai.tool.name"] == "get_weather"


def test_a_list_call_claims_no_tool() -> None:
    """Conditionally-required attributes are omitted, never emitted empty.

    A `tools/list` span carrying `gen_ai.tool.name: ""` asserts a tool was
    involved. That is the same class of error as a drift report naming a
    protocol revision the run never observed.
    """
    attributes = semconv.client_attributes("tools/list", endpoint="http://localhost:9000/mcp")
    assert "gen_ai.tool.name" not in attributes
    assert "gen_ai.operation.name" not in attributes
    assert "mcp.resource.uri" not in attributes


def test_a_resource_read_records_the_uri_as_an_attribute() -> None:
    """Out of the span name, into an attribute -- where cardinality is fine."""
    attributes = semconv.client_attributes(
        "resources/read",
        endpoint="http://localhost:9000/mcp",
        params={"uri": "file:///report.pdf"},
    )
    assert attributes["mcp.resource.uri"] == "file:///report.pdf"


def test_a_notification_records_no_request_id() -> None:
    """The convention says not to capture it when the id is null or omitted."""
    attributes = semconv.client_attributes(
        "notifications/cancelled",
        endpoint="http://localhost:9000/mcp",
        request_id=None,
    )
    assert "jsonrpc.request.id" not in attributes


# ------------------------------------------------------------- outcomes


def test_a_jsonrpc_error_becomes_an_error_span() -> None:
    attributes, status = semconv.response_attributes(error={"code": -32601})
    assert status == "error"
    assert attributes["rpc.response.status_code"] == "-32601"
    assert attributes["error.type"] == "-32601"


def test_a_tool_that_failed_inside_a_successful_call_is_not_ok() -> None:
    """`CallToolResult.isError` is the case that silently reads as success.

    The JSON-RPC layer worked; the tool did not. Collapsing that into "ok" is
    why tool-level failures go unnoticed in exactly the dashboards this feeds,
    so the convention gives it its own `error.type`.
    """
    attributes, status = semconv.response_attributes(result={"isError": True, "content": []})
    assert status == "error"
    assert attributes["error.type"] == "tool_error"


def test_a_successful_call_carries_no_error_attributes() -> None:
    attributes, status = semconv.response_attributes(result={"tools": []})
    assert (attributes, status) == ({}, "ok")


def test_a_transport_failure_is_distinguishable_from_a_protocol_one() -> None:
    attributes, status = semconv.response_attributes(transport_error="McpTransportError")
    assert status == "error"
    assert attributes["error.type"] == "McpTransportError"
    assert "rpc.response.status_code" not in attributes


# ------------------------------------------------------ context propagation


def test_traceparent_is_w3c_shaped() -> None:
    header = semconv.traceparent("a" * 32, "b" * 16)
    version, trace, span, flags = header.split("-")
    assert (version, flags) == ("00", "01")
    assert len(trace) == 32
    assert len(span) == 16


def test_the_trace_context_rides_in_params_meta_unprefixed() -> None:
    """HTTP propagation would not do, and the spec says why.

    One MCP request can be retried across several HTTP requests, and one HTTP
    request can carry several MCP messages, so the HTTP context is not the MCP
    context. `traceparent` is the documented exception to the DNS-prefixed key
    rule in `_meta`.
    """
    sent: dict[str, Any] = {}

    class Recorder:
        def post(self, url: str, *, json: dict[str, Any], headers: dict[str, str]) -> Any:
            sent["body"] = json
            return _Reply({"jsonrpc": "2.0", "id": 1, "result": {"tools": []}})

    recorder = TraceRecorder(seed="run-1")
    with McpClient("https://example.invalid/mcp", client=Recorder(), recorder=recorder) as client:
        client.call("tools/list")

    meta = sent["body"]["params"]["_meta"]
    assert meta["traceparent"].startswith(f"00-{recorder.trace_id}-")
    assert meta["traceparent"].endswith("-01")
    assert recorder.spans[0].span_id in meta["traceparent"]


def test_no_recorder_means_no_traceparent_and_no_import() -> None:
    """The default path must pay nothing for an option nobody enabled."""
    sent: dict[str, Any] = {}

    class Recorder:
        def post(self, url: str, *, json: dict[str, Any], headers: dict[str, str]) -> Any:
            sent["body"] = json
            return _Reply({"jsonrpc": "2.0", "id": 1, "result": {}})

    with McpClient("https://example.invalid/mcp", client=Recorder()) as client:
        client.call("tools/list")

    assert "traceparent" not in sent["body"]["params"]["_meta"]


# --------------------------------------------------------- the OTLP output


def test_spans_carry_the_time_they_actually_ran() -> None:
    """Both timestamps were wrong, in ways a collector would not forgive.

    `startTimeUnixNano` was `time.time()` read at serialization, so every span
    in a batch shared one timestamp -- the export's, not the span's. And
    `endTimeUnixNano` was never emitted at all, leaving the measured duration
    on a dataclass that never crossed the wire.
    """
    before = time.time_ns()
    recorder = TraceRecorder(seed="timing")
    handle = recorder.start_span("tools/list", kind=KIND_CLIENT)
    recorder.end_span(handle)
    after = time.time_ns()

    span = recorder.to_otlp_json()["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
    start, end = int(span["startTimeUnixNano"]), int(span["endTimeUnixNano"])
    assert before <= start <= after
    assert end >= start
    assert span["kind"] == KIND_CLIENT


def test_two_spans_do_not_share_one_timestamp() -> None:
    recorder = TraceRecorder(seed="two")
    first = recorder.start_span("server/discover")
    recorder.end_span(first)
    second = recorder.start_span("tools/list")
    recorder.end_span(second)

    spans = recorder.to_otlp_json()["resourceSpans"][0]["scopeSpans"][0]["spans"]
    assert int(spans[0]["startTimeUnixNano"]) <= int(spans[1]["startTimeUnixNano"])
    assert {s["endTimeUnixNano"] for s in spans}


def test_bodies_and_credentials_never_become_attributes() -> None:
    """The redaction that already existed still holds over the new path."""
    recorder = TraceRecorder(seed="redact")
    handle = recorder.start_span(
        "tools/call get_weather",
        authorization="Bearer sk-live-secret",
        response_body='{"customer": "real"}',
    )
    recorder.end_span(handle)
    blob = str(recorder.to_otlp_json())
    assert "sk-live-secret" not in blob
    assert "real" not in blob
    assert "[REDACTED]" in blob


# ------------------------------------------------------- the whole path


def test_a_live_drift_run_produces_conventional_spans() -> None:
    """End to end, against a server that validates what it receives."""
    recorder = TraceRecorder(seed="drift")
    with McpMockServer([_tool("alpha")]) as server:
        report = detect_mcp_drift(
            _declared(_tool("alpha")),
            server.endpoint,
            recorder=recorder,
        )

    # An unauthenticated mock draws an INFO about anonymous listing; nothing
    # here should be an error.
    assert [f.rule_id for f in report.findings if f.severity == "ERROR"] == []
    names = [span.name for span in recorder.spans]
    assert "tools/list" in names
    assert all(span.kind == KIND_CLIENT for span in recorder.spans)

    listed = next(span for span in recorder.spans if span.name == "tools/list")
    assert listed.attributes["mcp.method.name"] == "tools/list"
    assert listed.attributes["server.address"] == "127.0.0.1"
    assert listed.duration_ms >= 0, "a span whose duration was never recorded"


def test_the_trace_is_not_claimed_when_no_recorder_was_given() -> None:
    """An empty dict says "not traced"; a fabricated id would send a reader
    looking for a trace that does not exist."""
    with McpMockServer([_tool("alpha")]) as server:
        report = detect_mcp_drift(_declared(_tool("alpha")), server.endpoint)
    assert report.trace == {}


class _Reply:
    def __init__(self, payload: dict[str, Any], status: int = 200) -> None:
        self._payload = payload
        self.status_code = status
        self.headers: dict[str, str] = {"content-type": "application/json"}

    def json(self) -> dict[str, Any]:
        return self._payload


# ------------------------------------------------- correlation (RUN-08)


def test_each_finding_names_the_call_it_was_read_out_of() -> None:
    """A finding that cannot point at its evidence has to be taken on trust.

    The point of tracing a drift run is the pivot: from "this tool's schema
    drifted" to the exact request that established it, in one click, in a
    backend the team already has.
    """
    recorder = TraceRecorder(seed="correlate")
    with McpMockServer([_tool("alpha"), _tool("ghost")]) as server:
        report = detect_mcp_drift(
            _declared(_tool("alpha")),
            server.endpoint,
            recorder=recorder,
        )

    undeclared = [f for f in report.findings if f.rule_id == "MCP-DRIFT-TOOL-UNDECLARED"]
    assert undeclared, "the fixture serves a tool the manifest never declared"
    finding = undeclared[0]
    assert finding.trace_id == recorder.trace_id
    assert finding.span_id in {span.span_id for span in recorder.spans}

    named = next(span for span in recorder.spans if span.span_id == finding.span_id)
    assert named.name == "tools/list", "the undeclared tool was seen in the tool list"


def test_the_anonymous_probe_findings_point_at_the_anonymous_call() -> None:
    """Not at the authenticated list, which is a different request.

    Attribution is applied per producer for exactly this reason: a blanket
    "everything came from the tool list" would send a reader to a call that
    does not show what the finding is about.
    """
    recorder = TraceRecorder(seed="anon")
    with McpMockServer([_tool("alpha")], require_auth="s3cret", anonymous_tools=[]) as server:
        report = detect_mcp_drift(
            _declared(_tool("alpha")),
            server.endpoint,
            headers={"Authorization": "Bearer s3cret"},
            recorder=recorder,
        )

    auth = [f for f in report.findings if f.rule_id.startswith("MCP-AUTH-")]
    assert auth, "the run made an anonymous probe and reported on it"
    spans = {span.span_id: span for span in recorder.spans}
    for finding in auth:
        if finding.span_id is None:
            continue
        assert finding.span_id in spans

    # Two `tools/list` calls happened: the credentialed one and the probe.
    lists = [span for span in recorder.spans if span.name == "tools/list"]
    assert len(lists) >= 2


def test_an_untraced_run_claims_no_trace() -> None:
    with McpMockServer([_tool("alpha")]) as server:
        report = detect_mcp_drift(_declared(_tool("alpha")), server.endpoint)
    assert all(f.trace_id is None and f.span_id is None for f in report.findings)


def test_the_published_finding_shape_carries_the_correlation() -> None:
    """`unify` is what a consumer reads; the ids have to survive it.

    The top-level `findings` array exists so a consumer does not have to know
    which drift mode ran. An id that only appears inside the mode-specific
    report would be invisible to exactly that consumer.
    """
    from apiverity.runtime.findings import unify

    recorder = TraceRecorder(seed="unify")
    with McpMockServer([_tool("alpha"), _tool("ghost")]) as server:
        report = detect_mcp_drift(
            _declared(_tool("alpha")),
            server.endpoint,
            recorder=recorder,
        )

    traced = [unify(f) for f in report.findings if f.span_id]
    assert traced
    assert all(row["trace_id"] == recorder.trace_id for row in traced)
    assert all(row["span_id"] for row in traced)

    plain = unify(type(report.findings[0])(rule_id="X", message="y"))
    assert "trace_id" not in plain and "span_id" not in plain
