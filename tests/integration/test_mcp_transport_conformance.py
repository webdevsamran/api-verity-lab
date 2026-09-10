"""What this client puts on the wire, against a server that checks.

The drift wedge rests on one assumption: that `McpClient` speaks the revision
it says it speaks. It did not. Revision 2026-07-28 makes four things MUST on
every Streamable HTTP POST, and this client met none of them:

- `_meta` belongs on `params`, and the schema declares it **required** there.
  It was being written as a sibling of `params`, so both required keys inside
  it -- the protocol version and the client capabilities -- were in a place the
  schema does not define.
- `MCP-Protocol-Version` is required on every POST, and a server that does not
  support pre-`2025-06-18` clients MUST reject a request without it.
- `Mcp-Method` is required for all requests, so gateways can route without
  parsing a body.
- `Mcp-Name` is required for `tools/call`, `resources/read` and `prompts/get`.

None of it surfaced, because the only server these tests ever ran against
accepted anything. So the mock validates now, exactly as the transport requires
of a server, and these tests read what actually crossed the socket.

Sources, read 2026-09-10: the 2026-07-28 schema (`RequestParams._meta`,
`RequestMetaObject`, `HEADER_MISMATCH = -32020`) and the Streamable HTTP
transport document (Protocol Version Header, Standard Request Headers, Value
Encoding).
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from apiverity.mock.mcp_server import McpMockServer, _header_complaint
from apiverity.specs.mcp.runner import (
    METHOD_HEADER,
    NAME_HEADER,
    PROTOCOL_VERSION_HEADER,
    SPOKEN_PROTOCOL_VERSION,
    McpClient,
    Observation,
    decode_header_value,
    encode_header_value,
    list_tools,
)

pytestmark = pytest.mark.integration


def _tool(name: str = "search") -> dict[str, Any]:
    return {
        "name": name,
        "description": "Find things.",
        "inputSchema": {"type": "object", "properties": {}},
    }


# ------------------------------------------------------- the body's shape


def test_meta_is_sent_inside_params_where_the_schema_declares_it() -> None:
    sent: dict[str, Any] = {}

    class Recorder:
        def post(self, url: str, *, json: dict[str, Any], headers: dict[str, str]) -> Any:
            sent["body"] = json
            sent["headers"] = headers
            return _Reply({"jsonrpc": "2.0", "id": 1, "result": {"tools": []}})

    with McpClient("https://example.invalid/mcp", client=Recorder()) as client:
        client.call("tools/list")

    body = sent["body"]
    assert "_meta" not in body, "`_meta` is a member of params, not of the envelope"
    meta = body["params"]["_meta"]
    assert meta["io.modelcontextprotocol/protocolVersion"] == SPOKEN_PROTOCOL_VERSION
    assert meta["io.modelcontextprotocol/clientCapabilities"] == {}


def test_the_client_identifies_itself_on_every_request() -> None:
    """A tool that probes other people's servers should say what it is.

    The spec says clients SHOULD send `clientInfo` on every request. The
    operator reading their access log after an unexpected `tools/list` is the
    reason it is not optional here.
    """
    from apiverity import __version__

    sent: dict[str, Any] = {}

    class Recorder:
        def post(self, url: str, *, json: dict[str, Any], headers: dict[str, str]) -> Any:
            sent["body"] = json
            return _Reply({"jsonrpc": "2.0", "id": 1, "result": {}})

    with McpClient("https://example.invalid/mcp", client=Recorder()) as client:
        client.call("tools/list")

    info = sent["body"]["params"]["_meta"]["io.modelcontextprotocol/clientInfo"]
    assert info == {"name": "apiverity", "version": __version__}


def test_caller_params_survive_the_meta_injection() -> None:
    """`_meta` is added to the params, not instead of them."""
    sent: dict[str, Any] = {}

    class Recorder:
        def post(self, url: str, *, json: dict[str, Any], headers: dict[str, str]) -> Any:
            sent["body"] = json
            return _Reply({"jsonrpc": "2.0", "id": 1, "result": {}})

    with McpClient("https://example.invalid/mcp", client=Recorder()) as client:
        client.call("tools/list", {"cursor": "page-2"})

    assert sent["body"]["params"]["cursor"] == "page-2"
    assert "_meta" in sent["body"]["params"]


# ----------------------------------------------------------- the headers


def test_every_post_carries_the_required_routing_headers() -> None:
    sent: dict[str, Any] = {}

    class Recorder:
        def post(self, url: str, *, json: dict[str, Any], headers: dict[str, str]) -> Any:
            sent["headers"] = headers
            return _Reply({"jsonrpc": "2.0", "id": 1, "result": {}})

    with McpClient("https://example.invalid/mcp", client=Recorder()) as client:
        client.call("tools/list")

    assert sent["headers"][PROTOCOL_VERSION_HEADER] == SPOKEN_PROTOCOL_VERSION
    assert sent["headers"][METHOD_HEADER] == "tools/list"
    # `Mcp-Name` is required only where there is a target to name.
    assert NAME_HEADER not in sent["headers"]


def test_a_tool_call_names_its_target_in_a_header() -> None:
    sent: dict[str, Any] = {}

    class Recorder:
        def post(self, url: str, *, json: dict[str, Any], headers: dict[str, str]) -> Any:
            sent["headers"] = headers
            return _Reply({"jsonrpc": "2.0", "id": 1, "result": {}})

    with McpClient("https://example.invalid/mcp", client=Recorder()) as client:
        client.call("tools/call", {"name": "get_weather", "arguments": {}})

    assert sent["headers"][NAME_HEADER] == "get_weather"


def test_the_version_header_and_the_body_cannot_disagree() -> None:
    """They are written from one constant, in one place, deliberately.

    A server that finds them different MUST answer 400 with a `HeaderMismatch`
    error, so assembling them separately is how a client breaks itself.
    """
    sent: dict[str, Any] = {}

    class Recorder:
        def post(self, url: str, *, json: dict[str, Any], headers: dict[str, str]) -> Any:
            sent["body"], sent["headers"] = json, headers
            return _Reply({"jsonrpc": "2.0", "id": 1, "result": {}})

    with McpClient("https://example.invalid/mcp", client=Recorder()) as client:
        client.call("tools/list")

    in_body = sent["body"]["params"]["_meta"]["io.modelcontextprotocol/protocolVersion"]
    assert sent["headers"][PROTOCOL_VERSION_HEADER] == in_body


def test_an_operator_supplied_header_still_wins() -> None:
    """Overriding one is explicit; a flag that silently does nothing is not."""
    sent: dict[str, Any] = {}

    class Recorder:
        def post(self, url: str, *, json: dict[str, Any], headers: dict[str, str]) -> Any:
            sent["headers"] = headers
            return _Reply({"jsonrpc": "2.0", "id": 1, "result": {}})

    with McpClient(
        "https://example.invalid/mcp",
        headers={PROTOCOL_VERSION_HEADER: "2025-06-18"},
        client=Recorder(),
    ) as client:
        client.call("tools/list")

    assert sent["headers"][PROTOCOL_VERSION_HEADER] == "2025-06-18"


# -------------------------------------------------------- header encoding


@pytest.mark.parametrize(
    "value",
    ["get_weather", "天気を取得", " leading-and-trailing ", "=?base64?x?="],
)
def test_header_values_round_trip(value: str) -> None:
    assert decode_header_value(encode_header_value(value)) == value


def test_an_ascii_safe_name_is_sent_as_itself() -> None:
    """Encoding everything would be safe and unreadable in a log."""
    assert encode_header_value("get_weather") == "get_weather"


def test_a_name_that_looks_like_the_sentinel_is_encoded_anyway() -> None:
    """Otherwise the server decodes it into something the body never said.

    That is not a cosmetic difference: servers MUST decode the header before
    comparing it to the body, so an unencoded sentinel-shaped name is a way to
    make the two disagree on purpose.
    """
    encoded = encode_header_value("=?base64?x?=")
    assert encoded != "=?base64?x?="
    assert decode_header_value(encoded) == "=?base64?x?="


def test_a_non_ascii_tool_name_is_reachable() -> None:
    """Tool names are only SHOULD-constrained to header-safe characters.

    So a server whose tool is named in Japanese is a legal server, and a client
    that cannot address it is the one at fault.
    """
    sent: dict[str, Any] = {}

    class Recorder:
        def post(self, url: str, *, json: dict[str, Any], headers: dict[str, str]) -> Any:
            sent["headers"] = headers
            return _Reply({"jsonrpc": "2.0", "id": 1, "result": {}})

    with McpClient("https://example.invalid/mcp", client=Recorder()) as client:
        client.call("tools/call", {"name": "天気", "arguments": {}})

    assert decode_header_value(sent["headers"][NAME_HEADER]) == "天気"
    assert sent["headers"][NAME_HEADER].isascii()


# ------------------------------------------- against a server that checks


def test_a_real_round_trip_passes_a_validating_server() -> None:
    """The end-to-end proof: a server enforcing the MUSTs accepts this client."""
    with (
        McpMockServer([_tool("alpha")], enforce_headers=True) as server,
        McpClient(server.endpoint) as client,
    ):
        observation = Observation(endpoint=server.endpoint)
        tools, _ = list_tools(client, observation)
    assert [t["name"] for t in tools] == ["alpha"]
    headers = server.received_headers[0]
    assert headers[PROTOCOL_VERSION_HEADER.lower()] == SPOKEN_PROTOCOL_VERSION
    assert headers[METHOD_HEADER.lower()] == "tools/list"


def test_the_validating_server_actually_rejects_a_bad_request() -> None:
    """A mock that accepts anything proves nothing.

    So the validator is tested against requests it must refuse, rather than
    trusted because the good case passed.
    """
    good = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/list",
        "params": {
            "_meta": {
                "io.modelcontextprotocol/protocolVersion": SPOKEN_PROTOCOL_VERSION,
                "io.modelcontextprotocol/clientCapabilities": {},
            }
        },
    }
    good_headers = {
        PROTOCOL_VERSION_HEADER: SPOKEN_PROTOCOL_VERSION,
        METHOD_HEADER: "tools/list",
    }
    assert _header_complaint(good_headers, good) is None

    # `_meta` beside `params` instead of inside it -- the shape this client sent.
    misplaced = json.loads(json.dumps(good))
    misplaced["_meta"] = misplaced["params"].pop("_meta")
    assert _header_complaint(good_headers, misplaced) is not None

    assert _header_complaint({METHOD_HEADER: "tools/list"}, good) is not None
    assert _header_complaint({PROTOCOL_VERSION_HEADER: SPOKEN_PROTOCOL_VERSION}, good) is not None
    assert (
        _header_complaint(
            {**good_headers, PROTOCOL_VERSION_HEADER: "2025-06-18"},
            good,
        )
        is not None
    )
    assert _header_complaint({**good_headers, METHOD_HEADER: "tools/call"}, good) is not None


def test_a_named_method_without_its_name_header_is_refused() -> None:
    call = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "get_weather",
            "_meta": {
                "io.modelcontextprotocol/protocolVersion": SPOKEN_PROTOCOL_VERSION,
                "io.modelcontextprotocol/clientCapabilities": {},
            },
        },
    }
    headers = {
        PROTOCOL_VERSION_HEADER: SPOKEN_PROTOCOL_VERSION,
        METHOD_HEADER: "tools/call",
    }
    assert _header_complaint(headers, call) is not None
    assert _header_complaint({**headers, NAME_HEADER: "other_tool"}, call) is not None
    assert _header_complaint({**headers, NAME_HEADER: "get_weather"}, call) is None


class _Reply:
    """The two attributes `McpClient.call` reads off an httpx response."""

    def __init__(self, payload: dict[str, Any], status: int = 200) -> None:
        self._payload = payload
        self.status_code = status
        self.headers: dict[str, str] = {"content-type": "application/json"}

    def json(self) -> dict[str, Any]:
        return self._payload
