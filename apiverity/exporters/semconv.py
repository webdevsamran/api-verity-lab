"""OpenTelemetry GenAI semantic conventions, for the spans this tool emits.

Why this exists
---------------
A drift run makes real MCP calls against a real server. Those calls are the
same kind of event the user's own agents emit, and the value of naming them the
same way is that they land in the same dashboard: a schema that drifted at
09:14 sits next to the tool call that failed at 09:14, in one trace view, with
no bespoke exporter in between.

Getting the names right is the whole job. An attribute called `mcp_method`
instead of `mcp.method.name` is not "close" -- it is invisible to every query,
alert and dashboard built on the convention, which is the only reason to emit
it. So the names below are transcribed from the specification rather than
recalled, and the source is dated.

Status, stated plainly
----------------------
These conventions are **Development** status, in a repository that split out of
`open-telemetry/semantic-conventions` and has no tagged release. They will
change. What that means here is that the attribute *names* live in this one
module rather than being spelled inline at each call site, so a rename upstream
is a diff in one file instead of a search across the runtime.

Read 2026-09-10 from `open-telemetry/semantic-conventions-genai`,
`docs/gen-ai/mcp.md` (MCP client and server spans) at commit-of-the-day; the
repository was created 2026-05-05 and carries no release tags.

What is deliberately not emitted
--------------------------------
`gen_ai.tool.call.arguments` and `gen_ai.tool.call.result` are defined by the
convention as **Opt-In**, and they carry the tool's inputs and outputs
verbatim. This package's export path already refuses request and response
bodies (`redact_attributes`), because a span is an artifact that leaves the
machine and a tool result is exactly the place a credential or a customer
record shows up. They are named here so that their absence is a decision on the
record rather than an omission someone later "fixes".
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

# --------------------------------------------------------------- attributes
#
# Transcribed from the convention. Grouped by the registry they come from,
# because the stability of each group differs and that matters when one moves.

#: MCP registry -- Development.
MCP_METHOD_NAME = "mcp.method.name"
MCP_PROTOCOL_VERSION = "mcp.protocol.version"
MCP_SESSION_ID = "mcp.session.id"
MCP_RESOURCE_URI = "mcp.resource.uri"

#: GenAI registry -- Development.
GEN_AI_OPERATION_NAME = "gen_ai.operation.name"
GEN_AI_TOOL_NAME = "gen_ai.tool.name"
GEN_AI_PROMPT_NAME = "gen_ai.prompt.name"

#: JSON-RPC registry -- Development; `rpc.response.status_code` is RC.
JSONRPC_REQUEST_ID = "jsonrpc.request.id"
JSONRPC_PROTOCOL_VERSION = "jsonrpc.protocol.version"
RPC_RESPONSE_STATUS_CODE = "rpc.response.status_code"

#: Stable registries.
ERROR_TYPE = "error.type"
NETWORK_TRANSPORT = "network.transport"
NETWORK_PROTOCOL_NAME = "network.protocol.name"
SERVER_ADDRESS = "server.address"
SERVER_PORT = "server.port"

#: The value `gen_ai.operation.name` takes for a tool call, and only for one.
#: The convention says it SHOULD be set for a tool call and SHOULD NOT be set
#: otherwise, which is why this is applied by method rather than to every span.
OPERATION_EXECUTE_TOOL = "execute_tool"

#: `error.type` for a `tools/call` that returned `isError: true`. The call
#: succeeded at the JSON-RPC layer and failed at the tool layer, and the
#: convention gives that case its own value rather than leaving it looking
#: like a success.
ERROR_TOOL = "tool_error"

#: Methods that name a target, and where the name comes from. The span name is
#: `{method} {target}`, so a target this table does not cover produces a span
#: named for the method alone -- which is correct, not a fallback: an
#: unbounded target would make span names high-cardinality.
_TARGET_SOURCE = {
    "tools/call": ("name", GEN_AI_TOOL_NAME),
    "prompts/get": ("name", GEN_AI_PROMPT_NAME),
}

#: `mcp.resource.uri` is set for the methods that carry one. Kept apart from
#: the table above because the convention says instrumentations SHOULD NOT put
#: a resource URI in the span *name* by default -- URIs are unbounded, and a
#: span name per customer record is how a tracing bill becomes a story.
_RESOURCE_URI_METHODS = (
    "resources/read",
    "resources/subscribe",
    "resources/unsubscribe",
    "notifications/resources/updated",
)


def span_name(method: str, params: dict[str, Any] | None = None) -> str:
    """`{mcp.method.name} {target}`, or the method alone when there is none.

    The convention allows a resource URI as the target on opt-in only, and
    this never opts in: a URI is unbounded, and unbounded span names defeat
    every aggregation the trace was collected for.
    """
    source = _TARGET_SOURCE.get(method)
    if source is None:
        return method
    target = (params or {}).get(source[0])
    if isinstance(target, str) and target:
        return f"{method} {target}"
    return method


def client_attributes(
    method: str,
    *,
    endpoint: str,
    params: dict[str, Any] | None = None,
    request_id: int | str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Attributes for an MCP client span, before the response is known.

    Conditionally-required attributes are *omitted* when their condition does
    not hold, never emitted empty. A span carrying `gen_ai.tool.name: ""` for a
    `tools/list` asserts there was a tool involved, which is the same class of
    error as a report naming a protocol revision nobody observed.
    """
    from apiverity.specs.mcp.runner import SPOKEN_PROTOCOL_VERSION

    parsed = urlparse(endpoint)
    attributes: dict[str, Any] = {
        MCP_METHOD_NAME: method,
        MCP_PROTOCOL_VERSION: SPOKEN_PROTOCOL_VERSION,
        # `tcp` when the transport is HTTP, per the convention's own note --
        # not `http`, which belongs in `network.protocol.name`.
        NETWORK_TRANSPORT: "tcp",
        NETWORK_PROTOCOL_NAME: (parsed.scheme or "http").lower(),
    }
    if parsed.hostname:
        attributes[SERVER_ADDRESS] = parsed.hostname
    if parsed.port is not None:
        attributes[SERVER_PORT] = parsed.port

    source = _TARGET_SOURCE.get(method)
    if source is not None:
        target = (params or {}).get(source[0])
        if isinstance(target, str) and target:
            attributes[source[1]] = target
    if method == "tools/call":
        attributes[GEN_AI_OPERATION_NAME] = OPERATION_EXECUTE_TOOL
    if method in _RESOURCE_URI_METHODS:
        uri = (params or {}).get("uri")
        if isinstance(uri, str) and uri:
            attributes[MCP_RESOURCE_URI] = uri

    # Not captured when the id is null or omitted: that is a notification, and
    # the convention says so explicitly.
    if request_id is not None:
        attributes[JSONRPC_REQUEST_ID] = str(request_id)
    if session_id:
        attributes[MCP_SESSION_ID] = session_id
    return attributes


def response_attributes(
    *,
    error: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
    transport_error: str | None = None,
) -> tuple[dict[str, Any], str]:
    """Attributes and span status for a finished MCP call.

    Three outcomes, and the convention distinguishes all three: a JSON-RPC
    error, a successful call whose *result* reports a tool failure
    (`CallToolResult.isError`), and a transport failure where no JSON-RPC layer
    was reached at all. Collapsing the middle one into "ok" is the reason
    tool-level failures go unnoticed in the dashboards this feeds.
    """
    if transport_error:
        return {ERROR_TYPE: transport_error}, "error"
    if error:
        code = error.get("code")
        attributes: dict[str, Any] = {}
        if code is not None:
            # All JSON-RPC error codes count as errors, per the convention.
            attributes[RPC_RESPONSE_STATUS_CODE] = str(code)
            attributes[ERROR_TYPE] = str(code)
        else:
            attributes[ERROR_TYPE] = "_OTHER"
        return attributes, "error"
    if result is not None and result.get("isError") is True:
        return {ERROR_TYPE: ERROR_TOOL}, "error"
    return {}, "ok"


def traceparent(trace_id: str, span_id: str, *, sampled: bool = True) -> str:
    """A W3C `traceparent` for the given ids.

    Version `00`, 32 hex of trace id, 16 of span id, and the sampled flag.
    Ids shorter than that are left-padded rather than rejected: an id is a
    correlation key, and refusing to propagate one because it came from a
    different generator would break the correlation this exists to create.
    """
    trace = trace_id.rjust(32, "0")[:32].lower()
    span = span_id.rjust(16, "0")[:16].lower()
    return f"00-{trace}-{span}-{'01' if sampled else '00'}"
