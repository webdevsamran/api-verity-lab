"""The wire format, separated from what the server does with it.

LSP is JSON-RPC 2.0 over a stream, framed with HTTP-style headers:

    Content-Length: 92\\r\\n
    \\r\\n
    {"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}

Two things about that framing are worth stating, because both are places a
hand-rolled implementation goes wrong and the symptom is a client that hangs
with no error anywhere:

**`Content-Length` counts bytes, not characters.** A message with a non-ASCII
character in it -- a rule message quoting a contract, say -- is longer in UTF-8
than in code points, and a length computed from `len(str)` desynchronises the
stream from that message onward.

**The stream is binary.** Writing through a text-mode stdout on Windows
translates `\\n` to `\\r\\n`, which corrupts every frame. The server takes
`BufferedReader`/`BufferedWriter` and never a `TextIO`.
"""

from __future__ import annotations

import json
from typing import Any, BinaryIO

ENCODING = "utf-8"
HEADER_SEPARATOR = b"\r\n\r\n"
CONTENT_LENGTH = b"content-length:"


class ProtocolError(Exception):
    """A frame that cannot be read."""


def read_message(stream: BinaryIO) -> dict[str, Any] | None:
    """The next message, or `None` at end of stream.

    `None` is a normal outcome: a client that exits without `shutdown` closes
    the pipe, and treating that as an error would mean every editor quit logged
    a crash.
    """
    header = b""
    while not header.endswith(HEADER_SEPARATOR):
        byte = stream.read(1)
        if not byte:
            if header.strip():
                raise ProtocolError(f"stream ended mid-header: {header!r}")
            return None
        header += byte

    length = None
    for line in header.split(b"\r\n"):
        if line.lower().startswith(CONTENT_LENGTH):
            try:
                length = int(line.split(b":", 1)[1].strip())
            except ValueError as exc:
                raise ProtocolError(f"unparseable Content-Length: {line!r}") from exc
    if length is None:
        raise ProtocolError(f"no Content-Length in header: {header!r}")

    body = b""
    while len(body) < length:
        chunk = stream.read(length - len(body))
        if not chunk:
            raise ProtocolError(f"stream ended after {len(body)} of {length} bytes")
        body += chunk

    try:
        message = json.loads(body.decode(ENCODING))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ProtocolError(f"body is not JSON: {exc}") from exc
    if not isinstance(message, dict):
        raise ProtocolError("body is not a JSON object")
    return message


def write_message(stream: BinaryIO, message: dict[str, Any]) -> None:
    """Frame and send one message."""
    # `ensure_ascii=False`: the transport is UTF-8, and escaping every accented
    # character makes a frame bigger and a log harder to read for nothing. It is
    # also the honest setting -- with escaping on, byte length and character
    # length happen to agree and the computation below would look correct while
    # never being exercised.
    body = json.dumps(message, separators=(",", ":"), ensure_ascii=False).encode(ENCODING)
    # Bytes, not characters. A message quoting a contract's unicode
    # desynchronises the stream from that frame onward if this counts wrong.
    stream.write(b"Content-Length: " + str(len(body)).encode("ascii") + HEADER_SEPARATOR + body)
    stream.flush()


def response(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def notification(method: str, params: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "method": method, "params": params}


#: JSON-RPC / LSP error codes used here.
METHOD_NOT_FOUND = -32601
INTERNAL_ERROR = -32603
INVALID_REQUEST = -32600


__all__ = [
    "CONTENT_LENGTH",
    "ENCODING",
    "HEADER_SEPARATOR",
    "INTERNAL_ERROR",
    "INVALID_REQUEST",
    "METHOD_NOT_FOUND",
    "ProtocolError",
    "error",
    "notification",
    "read_message",
    "response",
    "write_message",
]
