"""A deterministic in-process MCP server, for tests and demos.

Binds to 127.0.0.1 and is not wired to the CLI. `apiverity/mock/server.py`
serves HTTP fixtures for the drift tests; this does the same job for the MCP
lane, so `test_mcp_drift.py` can exercise a real Streamable HTTP round trip --
JSON-RPC framing, pagination, `server/discover` -- without a network or a
third-party server.

It is also where the *misbehaving* server lives. Drift detection is only worth
anything if it fires, and the failure modes worth testing (a tool served that
was never declared, a schema that disagrees with the manifest, a tool set that
changes between connections) are precisely the ones no well-behaved server
will produce on demand.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from apiverity.specs.mcp.runner import (
    ERR_HEADER_MISMATCH,
    ERR_METHOD_NOT_FOUND,
    ERR_UNSUPPORTED_PROTOCOL_VERSION,
    METHOD_HEADER,
    NAME_HEADER,
    PROTOCOL_VERSION_HEADER,
    SPOKEN_PROTOCOL_VERSION,
    decode_header_value,
)

#: Methods whose target the transport requires in `Mcp-Name`, and the params
#: key it comes from. Duplicated from the client deliberately: a mock that
#: imported the client's table would agree with the client by construction and
#: prove nothing.
_NAME_REQUIRED = {"tools/call": "name", "prompts/get": "name", "resources/read": "uri"}


def _header_complaint(headers: dict[str, str], request: dict[str, Any]) -> str | None:
    """Return why this request fails header validation, or None if it passes.

    Every check here is a MUST in the Streamable HTTP transport of revision
    2026-07-28: the version header is required and must equal the one in
    `params._meta`, `Mcp-Method` is required for all requests, and `Mcp-Name`
    is required for the three methods that name a target.
    """
    lowered = {k.lower(): v for k, v in headers.items()}
    method = request.get("method")
    params = request.get("params")
    params = params if isinstance(params, dict) else {}
    meta = params.get("_meta")
    meta = meta if isinstance(meta, dict) else {}

    declared = lowered.get(PROTOCOL_VERSION_HEADER.lower())
    if declared is None:
        return f"missing {PROTOCOL_VERSION_HEADER}"
    in_body = meta.get("io.modelcontextprotocol/protocolVersion")
    if in_body is None:
        return "missing params._meta['io.modelcontextprotocol/protocolVersion']"
    if declared != in_body:
        return f"{PROTOCOL_VERSION_HEADER} {declared!r} != params._meta {in_body!r}"
    if "io.modelcontextprotocol/clientCapabilities" not in meta:
        return "missing params._meta['io.modelcontextprotocol/clientCapabilities']"

    sent_method = lowered.get(METHOD_HEADER.lower())
    if sent_method is None:
        return f"missing {METHOD_HEADER}"
    if sent_method != method:
        return f"{METHOD_HEADER} {sent_method!r} != method {method!r}"

    source = _NAME_REQUIRED.get(str(method))
    if source is not None:
        target = params.get(source)
        sent_name = lowered.get(NAME_HEADER.lower())
        if sent_name is None:
            return f"missing {NAME_HEADER} for {method}"
        if decode_header_value(sent_name) != target:
            return f"{NAME_HEADER} does not match params.{source}"
    return None


class McpMockServer:
    """Serve a tool list over Streamable HTTP, with configurable misbehaviour.

    Parameters mirror the conditions the drift checker exists to catch:

    ``pages``
        serve the tools in pages, so pagination and the page cap are exercised.
    ``per_connection_tools``
        a list of tool lists, one per connection, so a tool set that varies
        per connection can be produced deliberately.
    ``supported_versions``
        when set and not containing the client's revision, the server answers
        `server/discover` with -32022.
    ``implement_discover``
        False makes it a legacy server that answers -32601.
    ``omit_cache_fields``
        drop `ttlMs`/`cacheScope` from the list result.
    ``require_auth``
        a bearer token. Requests without it get 401, which is what a server
        that actually gates its inventory looks like.
    ``challenge``
        whether that 401 carries `WWW-Authenticate`. False produces the server
        a client cannot recover from: refused, with nowhere to go.
    ``anonymous_tools``
        a reduced tool list served to unauthenticated callers instead of a 401
        -- partial exposure, which is the case a probe that only tries
        authenticated requests can never see.
    ``enforce_headers``
        validate `MCP-Protocol-Version`, `Mcp-Method` and `Mcp-Name` against
        the body, which the transport spec requires of a server and which is
        the only way a mock can prove the client sends them. Set False for the
        permissive server that hid this for as long as it did.
    """

    def __init__(
        self,
        tools: list[dict[str, Any]] | None = None,
        *,
        host: str = "127.0.0.1",
        port: int = 0,
        page_size: int | None = None,
        per_connection_tools: list[list[dict[str, Any]]] | None = None,
        supported_versions: list[str] | None = None,
        implement_discover: bool = True,
        omit_cache_fields: bool = False,
        require_auth: str | None = None,
        challenge: bool = True,
        anonymous_tools: list[dict[str, Any]] | None = None,
        call_handler: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
        enforce_headers: bool = True,
    ) -> None:
        self.tools = tools or []
        self.host = host
        self.page_size = page_size
        self.per_connection_tools = per_connection_tools
        self.supported_versions = supported_versions
        self.implement_discover = implement_discover
        self.omit_cache_fields = omit_cache_fields
        self.require_auth = require_auth
        self.challenge = challenge
        self.anonymous_tools = anonymous_tools
        self.call_handler = call_handler
        self.enforce_headers = enforce_headers
        #: Headers of every POST received, so a test can assert on what was
        #: actually sent rather than on what the server chose to tolerate.
        self.received_headers: list[dict[str, str]] = []
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._list_requests = 0

        server = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args: Any) -> None:  # pragma: no cover - quiet
                return

            def do_POST(self) -> None:  # BaseHTTPRequestHandler dispatches on this name
                length = int(self.headers.get("content-length", 0))
                body = self.rfile.read(length) or b"{}"
                server.received_headers.append({k.lower(): v for k, v in self.headers.items()})
                presented = self.headers.get("authorization")
                authorized = (
                    server.require_auth is None or presented == f"Bearer {server.require_auth}"
                )
                if not authorized and server.anonymous_tools is None:
                    self._unauthorized()
                    return
                try:
                    request = json.loads(body)
                except json.JSONDecodeError:
                    self._send({"jsonrpc": "2.0", "id": None, "error": {"code": -32700}})
                    return
                if server.enforce_headers:
                    complaint = _header_complaint(dict(self.headers), request)
                    if complaint is not None:
                        self._send(
                            {
                                "jsonrpc": "2.0",
                                "id": request.get("id"),
                                "error": {"code": ERR_HEADER_MISMATCH, "message": complaint},
                            },
                            status=400,
                        )
                        return
                self._send(server.handle(request, authorized=authorized))

            def _unauthorized(self) -> None:
                # Deliberately not JSON: a real gateway rejects before the
                # JSON-RPC layer is reached, and the client has to cope with a
                # body it cannot parse.
                payload = b"unauthorized"
                self.send_response(401)
                if server.challenge:
                    self.send_header(
                        "WWW-Authenticate",
                        'Bearer resource_metadata="/.well-known/oauth-protected-resource"',
                    )
                self.send_header("content-type", "text/plain")
                self.send_header("content-length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def _send(self, payload: dict[str, Any], *, status: int = 200) -> None:
                body = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        # Threading, not HTTPServer: the per-connection stability check opens a
        # second connection while the first is still held open by HTTP/1.1
        # keep-alive, and a single-threaded server deadlocks on exactly that.
        # A real MCP server serves concurrent connections; so must the mock.
        self._httpd = ThreadingHTTPServer((host, port), Handler)
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    @property
    def endpoint(self) -> str:
        return f"http://{self.host}:{self.port}/mcp"

    def handle(self, request: dict[str, Any], *, authorized: bool = True) -> dict[str, Any]:
        method = request.get("method")
        request_id = request.get("id")
        params = request.get("params") or {}

        if method == "server/discover":
            if not self.implement_discover:
                return self._error(request_id, ERR_METHOD_NOT_FOUND, "Method not found")
            if self.supported_versions is not None and (
                SPOKEN_PROTOCOL_VERSION not in self.supported_versions
            ):
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": ERR_UNSUPPORTED_PROTOCOL_VERSION,
                        "message": "Unsupported protocol version",
                        "data": {
                            "supported": self.supported_versions,
                            "requested": SPOKEN_PROTOCOL_VERSION,
                        },
                    },
                }
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "supportedVersions": self.supported_versions or [SPOKEN_PROTOCOL_VERSION],
                    "capabilities": {"tools": {}},
                },
            }

        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": self._tools_page(params, authorized=authorized),
            }

        if method == "tools/call":
            name = str(params.get("name", ""))
            arguments = params.get("arguments") or {}
            self.calls.append((name, arguments))
            if self.call_handler is not None:
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": self.call_handler(name, arguments),
                }
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"resultType": "complete", "content": [{"type": "text", "text": "ok"}]},
            }

        return self._error(request_id, ERR_METHOD_NOT_FOUND, f"Method not found: {method}")

    def _tools_page(self, params: dict[str, Any], *, authorized: bool = True) -> dict[str, Any]:
        if not authorized and self.anonymous_tools is not None:
            tools = self.anonymous_tools
        elif self.per_connection_tools:
            index = min(self._list_requests, len(self.per_connection_tools) - 1)
            tools = self.per_connection_tools[index]
            self._list_requests += 1
        else:
            tools = self.tools

        result: dict[str, Any] = {"resultType": "complete"}
        if not self.omit_cache_fields:
            result["ttlMs"] = 60000
            result["cacheScope"] = "public"

        if self.page_size:
            start = int(params.get("cursor") or 0)
            page = tools[start : start + self.page_size]
            result["tools"] = page
            if start + self.page_size < len(tools):
                result["nextCursor"] = str(start + self.page_size)
        else:
            result["tools"] = tools
        return result

    @staticmethod
    def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}

    def __enter__(self) -> McpMockServer:
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=5)
