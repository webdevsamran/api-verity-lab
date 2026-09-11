"""A recording proxy: point a client at it, get a HAR corpus out.

`drift --corpus` and `infer` both want real traffic, and until now the only way
to get it was to already have a HAR from somewhere else. This records one.

It is a **forward-to-one-target** proxy, not a general one, and every design
decision below follows from that being the safe shape:

* It binds to `127.0.0.1` unless told otherwise, and it refuses `0.0.0.0`
  without an explicit acknowledgement. An unauthenticated recording proxy
  reachable from the network is a credential collector somebody else can point
  at whatever they like.
* There is no `CONNECT`. Tunnelling would either pass TLS through opaquely --
  recording nothing -- or require intercepting it, which means issuing
  certificates for hosts this process does not own. It answers `405` and says
  which.
* Every request goes to the one target the run named. A proxy that forwards
  wherever the client asks is an open relay.

## Redaction happens before the write, not after

`docs/privacy.md` says response bodies do not reach an artifact unasked, and
`SAFETY_MODEL.md` says credentials are never persisted. A recorder that wrote
the HAR and then sanitized it would have already put an `Authorization` header
on disk -- and on a crash between the two, left it there.

So headers, query strings, request URLs and bodies are redacted in memory, and
the entry appended to the log is the redacted one. The URL is rebuilt from the
redacted parameters rather than carried through: redacting `queryString` and
leaving `request.url` alone writes the credential into the file anyway, one
field over. The unredacted response still goes
back to the client, because the client asked for it and this is a proxy.

Two passes over a JSON body, not one: the field-name rules, then the patterns
over the serialized result. The second catches a credential sitting inside an
opaque string value -- an echoed request body, a log line carried in a field --
which nothing keyed on field names can see into.

**What neither catches** is an unlabelled secret in free text: a bare token
with nothing beside it saying what it is. Redaction here is rule-based, not
clairvoyant, and a recorder claiming otherwise is the claim that gets one
committed. Read what you captured before you commit it.

## What it admits it did not record

A corpus that silently drops what it could not handle is a corpus whose gaps
look like facts about the service. Every skip is counted and named:

* a body over `max_body_bytes`, because a recorder is not a place to put a
  40 MB upload;
* a non-text content type, which has no useful `text` in a HAR;
* a response this process never received, because the upstream failed.

The counts ride in the HAR's `log.comment`, so they survive the file rather
than only appearing on the console of the run that produced it.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit

from apiverity.traffic.redact import RedactionConfig, redact_headers, redact_json, redact_query

#: Bodies above this are recorded as absent-with-a-reason rather than kept.
DEFAULT_MAX_BODY_BYTES = 256 * 1024

#: Content types whose `text` is worth keeping in a HAR. Everything else is
#: recorded as skipped: a base64 blob in a corpus is bytes nobody will diff.
TEXTUAL = (
    "application/json",
    "application/xml",
    "text/",
    "+json",
    "+xml",
    "application/x-www-form",
)

#: Hop-by-hop headers, which belong to the connection and not to the message.
#: Forwarding them corrupts the proxied response -- a `Content-Length` from the
#: upstream describes a body this process may have re-encoded, and a
#: `Transfer-Encoding: chunked` describes a framing that is already undone.
HOP_BY_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
        "content-length",
        "content-encoding",
    }
)


class CaptureRefused(Exception):
    """A configuration this will not run under."""


def _textual(content_type: str) -> bool:
    lowered = content_type.lower()
    return any(marker in lowered for marker in TEXTUAL)


def _scrub(value: Any, cfg: RedactionConfig, depth: int = 0) -> Any:
    """Apply the pattern rules to every string in a structure.

    `redact_json` decides by field name, which cannot see into a value. A
    service that echoes a request body, or logs a line into a field, puts a
    labelled credential inside a string where no name-keyed rule reaches it.
    """
    if depth > 24:
        return value
    if isinstance(value, str):
        for pattern in cfg.compiled():
            value = pattern.sub(cfg.replacement, value)
        return value
    if isinstance(value, dict):
        return {k: _scrub(v, cfg, depth + 1) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub(v, cfg, depth + 1) for v in value]
    return value


@dataclass
class Skips:
    """What the recording did not keep, and why."""

    oversized_request: int = 0
    oversized_response: int = 0
    binary_request: int = 0
    binary_response: int = 0
    upstream_failed: int = 0
    #: Exchanges that arrived after the entry limit was reached. Counted rather
    #: than dropped silently: a corpus of exactly the requested size otherwise
    #: hides that traffic kept flowing, which is the difference between "this
    #: is what happened" and "this is the first N of what happened".
    after_limit: int = 0

    def as_dict(self) -> dict[str, int]:
        return {k: v for k, v in self.__dict__.items() if v}

    def summary(self) -> str:
        items = self.as_dict()
        if not items:
            return "nothing was skipped"
        return ", ".join(f"{name.replace('_', ' ')}: {count}" for name, count in items.items())


@dataclass
class Capture:
    """The corpus accumulating in memory."""

    target: str
    redaction: RedactionConfig = field(default_factory=RedactionConfig)
    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES
    #: Response bodies are what `drift --corpus` compares against, so unlike
    #: `import_har` this keeps them -- redacted -- and says so in the file.
    keep_response_bodies: bool = True
    #: A hard cap, not a threshold. The command's poll loop notices the limit
    #: a tenth of a second later, by which time more requests have arrived --
    #: so asking for two and getting three was the first behaviour here, and
    #: "--max-entries 2" plainly means two.
    max_entries: int | None = None
    entries: list[dict[str, Any]] = field(default_factory=list)
    skips: Skips = field(default_factory=Skips)

    def _body(
        self, raw: bytes, content_type: str, *, request: bool
    ) -> tuple[str | None, str | None]:
        """The text to record, or why there is none."""
        if not raw:
            return None, None
        if len(raw) > self.max_body_bytes:
            if request:
                self.skips.oversized_request += 1
            else:
                self.skips.oversized_response += 1
            return None, f"body of {len(raw)} bytes exceeded the {self.max_body_bytes}-byte cap"
        if not _textual(content_type):
            if request:
                self.skips.binary_request += 1
            else:
                self.skips.binary_response += 1
            return None, f"content type {content_type or '(none)'} is not recorded as text"

        text = raw.decode("utf-8", "replace")
        try:
            parsed = json.loads(text)
        except ValueError:
            # Not JSON, so the field-name rules cannot apply; the regex
            # patterns still can, and they are what catch a bearer token in a
            # form body.
            for pattern in self.redaction.compiled():
                text = pattern.sub(self.redaction.replacement, text)
            return text, None
        # Field names first, then the patterns over each string *value*. The
        # second pass catches a credential inside an opaque string -- an echoed
        # request body, a log line carried in a field -- which no rule keyed on
        # field names can see into.
        #
        # Over the values, not over the serialized document: in the serialized
        # form `{"password": "x"}` nested in a string reads as
        # `password\": \"x`, and the patterns match a name next to a colon.
        # The escaping is exactly what hides it.
        redacted = _scrub(redact_json(parsed, self.redaction), self.redaction)
        return json.dumps(redacted, separators=(",", ":")), None

    def record(
        self,
        *,
        method: str,
        url: str,
        request_headers: dict[str, str],
        request_body: bytes,
        status: int,
        response_headers: dict[str, str],
        response_body: bytes,
        started: str,
        duration_ms: int,
    ) -> None:
        """Append one exchange, redacted, unless the corpus is already full."""
        if self.max_entries is not None and len(self.entries) >= self.max_entries:
            self.skips.after_limit += 1
            return
        split = urlsplit(url)
        query = {}
        for pair in split.query.split("&"):
            if not pair:
                continue
            name, _, value = pair.partition("=")
            query[name] = value
        query = redact_query(query, self.redaction)

        # The URL is rebuilt from the redacted parameters, not carried through.
        # Redacting `queryString` and leaving `request.url` alone writes the
        # credential into the file anyway, one field over -- which is what the
        # first version of this did, and what the test that reads the file back
        # caught.
        url = urlunsplit(
            (
                split.scheme,
                split.netloc,
                split.path,
                urlencode({k: str(v) for k, v in query.items()}, safe="[]"),
                "",
            )
        )

        request_type = request_headers.get("content-type", request_headers.get("Content-Type", ""))
        response_type = response_headers.get(
            "content-type", response_headers.get("Content-Type", "")
        )
        req_text, req_dropped = self._body(request_body, request_type, request=True)
        if self.keep_response_bodies:
            resp_text, resp_dropped = self._body(response_body, response_type, request=False)
        else:
            resp_text, resp_dropped = None, "response bodies were not kept by this run"

        entry: dict[str, Any] = {
            "startedDateTime": started,
            "time": duration_ms,
            "request": {
                "method": method,
                "url": url,
                "httpVersion": "HTTP/1.1",
                "headers": [
                    {"name": k, "value": v}
                    for k, v in redact_headers(request_headers, self.redaction).items()
                ],
                "queryString": [{"name": k, "value": str(v)} for k, v in query.items()],
                "cookies": [],
                "headersSize": -1,
                "bodySize": len(request_body),
            },
            "response": {
                "status": status,
                "statusText": "",
                "httpVersion": "HTTP/1.1",
                "headers": [
                    {"name": k, "value": v}
                    for k, v in redact_headers(response_headers, self.redaction).items()
                ],
                "cookies": [],
                "content": {
                    "size": len(response_body),
                    "mimeType": response_type,
                    **({"text": resp_text} if resp_text is not None else {}),
                    **({"comment": resp_dropped} if resp_dropped else {}),
                },
                "headersSize": -1,
                "bodySize": len(response_body),
            },
            "cache": {},
            "timings": {"send": 0, "wait": duration_ms, "receive": 0},
        }
        if req_text is not None:
            entry["request"]["postData"] = {"mimeType": request_type, "text": req_text}
        elif req_dropped:
            entry["request"]["postData"] = {"mimeType": request_type, "comment": req_dropped}
        self.entries.append(entry)

    def har(self) -> dict[str, Any]:
        from apiverity import __version__

        return {
            "log": {
                "version": "1.2",
                "creator": {"name": "apiverity capture", "version": __version__},
                # In the file, not only on the console: a corpus whose gaps are
                # only described in the output of the run that made it has gaps
                # that look like facts about the service.
                "comment": (
                    f"recorded against {self.target}; redacted before write; {self.skips.summary()}"
                ),
                "entries": self.entries,
            }
        }

    def write(self, path: str | Path) -> Path:
        target = Path(path)
        if str(target.parent) not in ("", "."):
            target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.har(), indent=2) + "\n", encoding="utf-8", newline="\n")
        return target


def check_bind(host: str, *, acknowledged: bool) -> None:
    """Refuse a bind address that makes this reachable from the network.

    An unauthenticated recording proxy on a routable address is a credential
    collector somebody else can point at whatever they like -- and this one
    writes what it sees to a file.
    """
    if host in ("127.0.0.1", "localhost", "::1"):
        return
    if acknowledged:
        return
    raise CaptureRefused(
        f"binding to {host} makes this recorder reachable from the network, and it "
        "writes what it records to a file. Pass --i-know-this-is-exposed to do it "
        "anyway, or leave the default of 127.0.0.1."
    )


def serve(
    capture: Capture,
    *,
    host: str = "127.0.0.1",
    port: int = 0,
    timeout: float = 30.0,
) -> tuple[ThreadingHTTPServer, threading.Thread]:
    """Start the proxy. The caller owns shutting it down."""
    import httpx

    upstream = httpx.Client(base_url=capture.target, timeout=timeout, follow_redirects=False)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args: Any) -> None:  # pragma: no cover - quiet
            return

        def do_CONNECT(self) -> None:
            # Tunnelling would either pass TLS through opaquely, recording
            # nothing, or require issuing certificates for hosts this process
            # does not own. Neither is something a contract tool should do.
            self.send_error(
                405,
                "CONNECT is not supported: this records one target over plain HTTP "
                "rather than intercepting TLS",
            )

        def _proxy(self) -> None:
            import time

            length = int(self.headers.get("content-length") or 0)
            body = self.rfile.read(length) if length else b""
            request_headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP_BY_HOP}
            # The upstream decides the Host; forwarding the proxy's own would
            # reach a virtual host that does not exist there.
            request_headers.pop("Host", None)
            request_headers.pop("host", None)

            started = time.strftime("%Y-%m-%dT%H:%M:%S") + "Z"
            began = time.monotonic()
            try:
                response = upstream.request(
                    self.command, self.path, headers=request_headers, content=body or None
                )
            except Exception as exc:
                capture.skips.upstream_failed += 1
                self.send_error(502, f"upstream failed: {exc}")
                return
            duration_ms = int((time.monotonic() - began) * 1000)

            capture.record(
                method=self.command,
                url=str(response.request.url),
                request_headers=request_headers,
                request_body=body,
                status=response.status_code,
                response_headers=dict(response.headers),
                response_body=response.content,
                started=started,
                duration_ms=duration_ms,
            )

            self.send_response(response.status_code)
            for name, value in response.headers.items():
                if name.lower() not in HOP_BY_HOP:
                    self.send_header(name, value)
            self.send_header("content-length", str(len(response.content)))
            self.end_headers()
            self.wfile.write(response.content)

        do_GET = _proxy
        do_POST = _proxy
        do_PUT = _proxy
        do_PATCH = _proxy
        do_DELETE = _proxy
        do_HEAD = _proxy
        do_OPTIONS = _proxy

    server = ThreadingHTTPServer((host, port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


__all__ = [
    "DEFAULT_MAX_BODY_BYTES",
    "HOP_BY_HOP",
    "Capture",
    "CaptureRefused",
    "Skips",
    "check_bind",
    "serve",
]
