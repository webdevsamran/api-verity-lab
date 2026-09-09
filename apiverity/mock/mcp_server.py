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
    ERR_METHOD_NOT_FOUND,
    ERR_UNSUPPORTED_PROTOCOL_VERSION,
    SPOKEN_PROTOCOL_VERSION,
)


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
        call_handler: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
    ) -> None:
        self.tools = tools or []
        self.host = host
        self.page_size = page_size
        self.per_connection_tools = per_connection_tools
        self.supported_versions = supported_versions
        self.implement_discover = implement_discover
        self.omit_cache_fields = omit_cache_fields
        self.call_handler = call_handler
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._list_requests = 0

        server = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args: Any) -> None:  # pragma: no cover - quiet
                return

            def do_POST(self) -> None:  # BaseHTTPRequestHandler dispatches on this name
                length = int(self.headers.get("content-length", 0))
                try:
                    request = json.loads(self.rfile.read(length) or b"{}")
                except json.JSONDecodeError:
                    self._send({"jsonrpc": "2.0", "id": None, "error": {"code": -32700}})
                    return
                self._send(server.handle(request))

            def _send(self, payload: dict[str, Any]) -> None:
                body = json.dumps(payload).encode()
                self.send_response(200)
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

    def handle(self, request: dict[str, Any]) -> dict[str, Any]:
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
            return {"jsonrpc": "2.0", "id": request_id, "result": self._tools_page(params)}

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

    def _tools_page(self, params: dict[str, Any]) -> dict[str, Any]:
        if self.per_connection_tools:
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
