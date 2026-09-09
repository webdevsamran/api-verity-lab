"""Talk to a live MCP server, and compare it to what it declared.

This is the leg the market leaves open. Version-to-version manifest diffing is
shipped by several projects; comparing a *declared* tool schema against what a
*running* server actually serves is not, and it is the thing this engine has
been doing for five other protocols since v0.1.

Two transports exist in the specification and this speaks one of them
---------------------------------------------------------------------
MCP binds to stdio and to Streamable HTTP. Only the second is implemented, and
the reason is the safety model rather than effort.

`SAFETY_MODEL.md` §1 is "explicit targets only", and every gate beneath it is
expressed over a URL: `traffic/safety.py::classify_target` derives
local/dev/staging/production from `urlparse(base_url).hostname`. It cannot
classify `npx -y some-mcp-server`. Shipping stdio would mean shipping an
execution path that none of the existing controls can even express, and then
documenting a safety model it does not have. Reading a command line out of a
config file and spawning it is also arbitrary code execution, a categorically
different hazard from sending an HTTP request, and nothing in this package
spawns a subprocess in a runtime path today.

So stdio is stated as unsupported, with the reason, rather than left as a TODO.

There is no handshake any more, and that changes the probe
----------------------------------------------------------
Revision 2026-07-28 made MCP stateless: the `initialize` /
`notifications/initialized` handshake was removed along with protocol-level
sessions, and every request now carries its protocol version and client
capabilities in `_meta`. Servers MUST implement `server/discover`.

This client never sends `initialize`. Three reasons, and they are all the same
reason in different clothes: sending a method the current revision removed
teaches a modern server nothing; a legacy `initialize` reply reports the
version the server agreed to speak in a negotiation *we* drove, not the version
it serves, so recording it would be asserting something the run did not
establish; and `initialize` opens session state we would then own and have to
tear down.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import httpx

#: The revision this client speaks. Sent on every request; never assumed of the
#: server.
SPOKEN_PROTOCOL_VERSION = "2026-07-28"

_META_VERSION = "io.modelcontextprotocol/protocolVersion"
_META_CAPABILITIES = "io.modelcontextprotocol/clientCapabilities"

#: JSON-RPC error codes this client reasons about.
ERR_METHOD_NOT_FOUND = -32601
ERR_UNSUPPORTED_PROTOCOL_VERSION = -32022

#: Following `nextCursor` forever is a denial of service against ourselves.
DEFAULT_MAX_PAGES = 50


class McpTransportError(RuntimeError):
    """The server could not be reached, or did not answer JSON-RPC at all."""


@dataclass
class RpcResult:
    """One JSON-RPC reply, with the error kept rather than raised."""

    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None

    @property
    def error_code(self) -> int | None:
        if isinstance(self.error, dict) and isinstance(self.error.get("code"), int):
            return int(self.error["code"])
        return None


@dataclass
class Observation:
    """What the run established about the server. Nothing more.

    Every field here is either something a response said or an explicit
    "not established", with `reason` carrying why. A drift report that named a
    protocol revision it never saw would be exactly the defect this project
    treats as its worst.
    """

    endpoint: str
    discover_status: str = "not-attempted"
    protocol_revision: str = "unknown"
    reason: str = ""
    server_supported_versions: list[str] = field(default_factory=list)
    capabilities: dict[str, Any] = field(default_factory=dict)
    instructions: str | None = None
    era: str = "unknown"
    authorization_presented: bool = False
    header_names: list[str] = field(default_factory=list)
    pages_read: int = 0
    pagination_exhausted: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "endpoint": self.endpoint,
            "transport": "streamable-http",
            "spoken_protocol_version": SPOKEN_PROTOCOL_VERSION,
            "discover_status": self.discover_status,
            "protocol_revision": self.protocol_revision,
            "reason": self.reason,
            "server_supported_versions": self.server_supported_versions,
            "era": self.era,
            "authorization_presented": self.authorization_presented,
            "header_names": self.header_names,
            "pages_read": self.pages_read,
            "pagination_exhausted": self.pagination_exhausted,
        }


class McpClient:
    """A minimal Streamable HTTP JSON-RPC client for MCP.

    Deliberately not a general MCP SDK: it issues the two read-only calls the
    drift check needs, plus `tools/call` when the caller has explicitly asked
    for it. `httpx` is already a runtime dependency, so this adds none.
    """

    def __init__(
        self,
        endpoint: str,
        *,
        timeout: float = 10.0,
        headers: dict[str, str] | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.endpoint = endpoint
        self.timeout = timeout
        self.headers = dict(headers or {})
        self._client = client
        self._owns_client = client is None
        self._id = 0

    def __enter__(self) -> McpClient:
        if self._client is None:
            self._client = httpx.Client(timeout=self.timeout)
        return self

    def __exit__(self, *exc: object) -> None:
        if self._owns_client and self._client is not None:
            self._client.close()
            self._client = None

    def _envelope(self, method: str, params: dict[str, Any] | None) -> dict[str, Any]:
        self._id += 1
        return {
            "jsonrpc": "2.0",
            "id": self._id,
            "method": method,
            "params": params or {},
            # Both keys are required on every request from 2026-07-28. Sent
            # unconditionally: a legacy server ignores unknown _meta rather
            # than failing, so one shape works for both eras.
            "_meta": {
                _META_VERSION: SPOKEN_PROTOCOL_VERSION,
                _META_CAPABILITIES: {},
            },
        }

    def call(self, method: str, params: dict[str, Any] | None = None) -> RpcResult:
        if self._client is None:  # pragma: no cover - guarded by __enter__
            raise McpTransportError("client used outside its context manager")
        try:
            response = self._client.post(
                self.endpoint,
                json=self._envelope(method, params),
                headers={
                    "content-type": "application/json",
                    "accept": "application/json",
                    **self.headers,
                },
            )
        except httpx.HTTPError as exc:
            raise McpTransportError(f"{self.endpoint}: {exc}") from exc

        try:
            payload = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise McpTransportError(
                f"{self.endpoint}: HTTP {response.status_code} body is not JSON"
            ) from exc

        if not isinstance(payload, dict):
            raise McpTransportError(f"{self.endpoint}: JSON-RPC reply is not an object")
        error = payload.get("error")
        result = payload.get("result")
        return RpcResult(
            result=result if isinstance(result, dict) else None,
            error=error if isinstance(error, dict) else None,
        )


def probe(client: McpClient, *, headers: dict[str, str] | None = None) -> Observation:
    """Establish what we are talking to, without asserting what we did not see.

    `server/discover` has four outcomes and three of them are conclusive:

    * a `DiscoverResult` -- the versions are copied verbatim off the wire;
    * `-32022 UnsupportedProtocolVersionError` -- still a modern server, since
      it implemented `server/discover` and told us our revision is wrong;
    * `-32601 Method not found` -- we have observed the *absence* of
      `server/discover`, which is not the same as observing a version, so the
      revision stays "unknown" with a reason;
    * transport failure -- raised, because a report built on a server we could
      not reach is worthless.
    """
    observation = Observation(endpoint=client.endpoint)
    observation.authorization_presented = any(
        name.lower() == "authorization" for name in (headers or {})
    )
    observation.header_names = sorted(headers or {})

    reply = client.call("server/discover")

    if reply.error_code == ERR_UNSUPPORTED_PROTOCOL_VERSION:
        data = reply.error.get("data") if isinstance(reply.error, dict) else None
        supported = data.get("supported") if isinstance(data, dict) else None
        observation.discover_status = "unsupported-protocol-version"
        observation.era = "modern"
        observation.server_supported_versions = (
            [str(v) for v in supported] if isinstance(supported, list) else []
        )
        observation.reason = (
            f"the server rejected protocol version {SPOKEN_PROTOCOL_VERSION} "
            f"(-32022); it supports {observation.server_supported_versions or 'an unstated set'}"
        )
        return observation

    if reply.error_code == ERR_METHOD_NOT_FOUND:
        observation.discover_status = "method-not-found"
        observation.reason = (
            "server/discover is mandatory from 2026-07-28 and was not implemented; no "
            "initialize handshake was attempted, so the revision this server speaks was "
            "not observed"
        )
        return observation

    if reply.error is not None:
        observation.discover_status = "error"
        observation.reason = f"server/discover returned error {reply.error}"
        return observation

    result = reply.result or {}
    versions = result.get("supportedVersions")
    observation.discover_status = "ok"
    observation.era = "modern"
    observation.server_supported_versions = (
        [str(v) for v in versions] if isinstance(versions, list) else []
    )
    capabilities = result.get("capabilities")
    observation.capabilities = capabilities if isinstance(capabilities, dict) else {}
    instructions = result.get("instructions")
    observation.instructions = instructions if isinstance(instructions, str) else None
    if SPOKEN_PROTOCOL_VERSION in observation.server_supported_versions:
        observation.protocol_revision = SPOKEN_PROTOCOL_VERSION
        observation.reason = "the server lists this revision in supportedVersions"
    else:
        observation.reason = (
            f"the server answered server/discover but does not list "
            f"{SPOKEN_PROTOCOL_VERSION}; the revision it serves was not established"
        )
    return observation


def list_tools(
    client: McpClient, observation: Observation, *, max_pages: int = DEFAULT_MAX_PAGES
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Read every page of `tools/list`, bounded.

    The bound matters for correctness, not just for safety. If the cap is hit,
    `observation.pagination_exhausted` is False and the caller must not report
    a declared-but-absent tool as missing: a tool on page fifty-one is not a
    tool that was removed.
    """
    tools: list[dict[str, Any]] = []
    envelope: dict[str, Any] = {}
    cursor: str | None = None

    for page in range(max_pages):
        params = {"cursor": cursor} if cursor else {}
        reply = client.call("tools/list", params)
        if reply.error is not None:
            raise McpTransportError(f"tools/list failed: {reply.error}")
        envelope = reply.result or {}
        page_tools = envelope.get("tools")
        if not isinstance(page_tools, list):
            raise McpTransportError("tools/list returned no `tools` array")
        tools.extend(t for t in page_tools if isinstance(t, dict))
        observation.pages_read = page + 1
        cursor = envelope.get("nextCursor") if isinstance(envelope.get("nextCursor"), str) else None
        if not cursor:
            observation.pagination_exhausted = True
            return tools, envelope

    observation.pagination_exhausted = False
    return tools, envelope
