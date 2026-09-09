"""JSON-RPC over stdio, so an agent can ask whether a change is breaking.

An agent editing a spec has a question this tool already answers exactly: *did
that change break anything, and for whom?* The answer is deterministic, needs
no network, and is already a structured `result-v1` artifact rather than prose.
Asking a model "is this breaking?" gets a plausible answer; asking this gets one
with a rule id behind it that a human can check.

No SDK. The framing is newline-delimited JSON-RPC over stdin and stdout, which
is about fifty lines, and adding a dependency to a package whose whole runtime
is httpx, flask, pydantic, PyYAML and packaging would cost more than it saves.

stdout is the frame stream, so nothing here may print to it. Diagnostics go to
stderr, and handlers are forbidden from using the CLI's `_emit` for the same
reason -- see `tools.py`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, TextIO

from apiverity import __version__
from apiverity.mcp.paths import PathRefused
from apiverity.mcp.tools import MCP_TOOLS_SCHEMA_VERSION, TOOLS, TOOLS_BY_NAME

#: The revision this server's framing targets.
PROTOCOL_VERSION = "2026-07-28"

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INTERNAL_ERROR = -32603


def _result(request_id: Any, payload: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": payload}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _tool_error(request_id: Any, message: str) -> dict[str, Any]:
    """A tool that failed, reported the way the specification wants.

    A tool *failure* is a successful JSON-RPC result carrying `isError: true`;
    a JSON-RPC error is for protocol-level problems. Conflating them is one of
    the things this project's own drift checker reports against other servers,
    so it would be poor form to do it here.
    """
    return _result(
        request_id,
        {
            "resultType": "complete",
            "content": [{"type": "text", "text": message}],
            "isError": True,
        },
    )


def handle(request: dict[str, Any], root: Path) -> dict[str, Any] | None:
    """Dispatch one request. Returns None for a notification."""
    request_id = request.get("id")
    method = request.get("method")
    if not isinstance(method, str):
        return _error(request_id, INVALID_REQUEST, "missing method")

    # A notification (no id) expects no reply, per JSON-RPC.
    is_notification = "id" not in request

    if method == "server/discover":
        return _result(
            request_id,
            {
                "supportedVersions": [PROTOCOL_VERSION],
                "capabilities": {"tools": {}},
                "instructions": (
                    "Read-only contract governance. Every tool is a pure function of files "
                    "beneath this server's configured root; nothing contacts a network "
                    "target, starts a listener, or writes to disk."
                ),
            },
        )

    if method == "tools/list":
        return _result(
            request_id,
            {
                "resultType": "complete",
                "tools": [tool.manifest_entry() for tool in TOOLS],
                "ttlMs": 0,
                "cacheScope": "public",
                "_meta": {
                    "dev.apiverity/toolsSchemaVersion": MCP_TOOLS_SCHEMA_VERSION,
                    "dev.apiverity/toolVersion": __version__,
                },
            },
        )

    if method == "tools/call":
        params = request.get("params") or {}
        name = params.get("name")
        arguments = params.get("arguments") or {}
        tool = TOOLS_BY_NAME.get(name) if isinstance(name, str) else None
        if tool is None:
            # An unknown tool is a protocol-level problem, not a tool failure.
            return _error(request_id, METHOD_NOT_FOUND, f"no such tool: {name!r}")
        if not isinstance(arguments, dict):
            return _tool_error(request_id, "arguments must be an object")
        try:
            payload = tool.handler(root, arguments)
        except PathRefused as exc:
            # Safe by construction: PathRefused messages are written for a
            # caller and never carry an absolute path or exception text.
            return _tool_error(request_id, str(exc))
        except Exception:
            # Deliberately not `str(exc)`. Loader and filesystem errors embed
            # the full resolved path, which would disclose the operator's
            # directory layout to the model on every typo.
            return _tool_error(request_id, f"{tool.name} failed while processing the request")
        return _result(
            request_id,
            {
                "resultType": "complete",
                "content": [
                    {"type": "text", "text": json.dumps(payload, indent=2, sort_keys=True)}
                ],
                "structuredContent": payload,
            },
        )

    if is_notification:
        return None
    return _error(request_id, METHOD_NOT_FOUND, f"no such method: {method}")


def serve(root: Path, stdin: TextIO, stdout: TextIO) -> int:
    """Read newline-delimited JSON-RPC from `stdin`, write replies to `stdout`."""
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            reply: dict[str, Any] | None = _error(None, PARSE_ERROR, "invalid JSON")
        else:
            if not isinstance(request, dict):
                reply = _error(None, INVALID_REQUEST, "request must be an object")
            else:
                try:
                    reply = handle(request, root)
                except Exception:  # pragma: no cover - last-resort guard
                    reply = _error(request.get("id"), INTERNAL_ERROR, "internal error")
        if reply is not None:
            stdout.write(json.dumps(reply) + "\n")
            stdout.flush()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="apiverity-mcp",
        description=(
            "Expose apiverity's read-only contract analysis to an agent over MCP. "
            "Reads files beneath --root and nothing else."
        ),
    )
    parser.add_argument(
        "--root",
        default=".",
        help=(
            "directory the server may read contracts from. Every path argument is "
            "resolved beneath it; anything outside is refused (default: the working "
            "directory)"
        ),
    )
    parser.add_argument("--version", action="version", version=f"apiverity-mcp {__version__}")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"error: --root is not a directory: {args.root}", file=sys.stderr)
        return 2
    print(f"apiverity-mcp {__version__} serving {len(TOOLS)} read-only tools", file=sys.stderr)
    return serve(root, sys.stdin, sys.stdout)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
