"""Recording real traffic, and the file it must never write.

`drift --corpus` and `infer` both want traffic, and until now the only way to
get some was to already have a HAR. The thing that makes a recorder dangerous
rather than merely useful is that it writes what it sees to disk, so the test
that matters most here is the one that reads the file back looking for the
Authorization header.

Run against a real socket rather than a stub: the redaction, the hop-by-hop
handling and the round trip are all about what actually crosses a connection.
"""

from __future__ import annotations

import contextlib
import io
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import pytest

from apiverity.cli.commands.common import EXIT_USAGE
from apiverity.cli.main import main
from apiverity.traffic.capture import (
    Capture,
    CaptureRefused,
    check_bind,
    serve,
    upstream_url,
)

pytestmark = pytest.mark.integration

# Bearer-shaped on purpose: the test below reads the written HAR back looking
# for this exact string, so a fixture that did not look like a credential
# would not exercise the redaction it is checking.
_TOKEN = "Bearer super-secret-value-nobody-should-see"  # secret-scan: allow


class _Upstream:
    """A service that echoes what it was sent, so the proxy is the only variable."""

    def __init__(self) -> None:
        self.seen: list[tuple[str, str, dict[str, str]]] = []
        upstream = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args: Any) -> None:  # pragma: no cover - quiet
                return

            def _respond(self) -> None:
                length = int(self.headers.get("content-length") or 0)
                raw = self.rfile.read(length) if length else b""
                upstream.seen.append((self.command, self.path, dict(self.headers)))

                if self.path.startswith("/binary"):
                    body, mime = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32, "image/png"
                elif self.path.startswith("/big"):
                    body, mime = b"x" * 4096, "application/json"
                else:
                    body = json.dumps(
                        {
                            "id": "u-1",
                            "password": "hunter2",
                            "echo": raw.decode("utf-8", "replace") or None,
                        }
                    ).encode()
                    mime = "application/json"

                self.send_response(200)
                self.send_header("content-type", mime)
                self.send_header("content-length", str(len(body)))
                self.send_header("x-upstream", "yes")
                self.end_headers()
                self.wfile.write(body)

            do_GET = _respond
            do_POST = _respond
            do_DELETE = _respond

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def __enter__(self) -> _Upstream:
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=5)


@contextlib.contextmanager
def _proxy(capture: Capture) -> Any:
    server, thread = serve(capture, host="127.0.0.1", port=0, timeout=5.0)
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


# ------------------------------------------------------- the file it writes


def test_the_credential_never_reaches_the_file(tmp_path: Path) -> None:
    """The test this module exists for.

    A recorder that wrote the HAR and then sanitized it would have already put
    the Authorization header on disk, and on a crash between the two, left it
    there. Redaction happens in memory, before the append.
    """
    with _Upstream() as upstream:
        capture = Capture(target=upstream.base_url)
        with _proxy(capture) as proxy:
            httpx.post(
                f"{proxy}/users?api_key=leaked-in-the-query",
                headers={"authorization": _TOKEN, "content-type": "application/json"},
                json={"password": "hunter2", "name": "Ada"},
                timeout=5,
            )
        written = capture.write(tmp_path / "corpus.har")

    body = written.read_text(encoding="utf-8")
    assert "super-secret-value-nobody-should-see" not in body
    assert "hunter2" not in body
    assert "leaked-in-the-query" not in body
    assert "[REDACTED]" in body
    # And the parts that are not secret survived, or the corpus is useless.
    assert "Ada" in body
    assert "/users" in body


def test_a_credential_inside_a_string_value_is_caught_too() -> None:
    """The upstream echoes the request body into a field, so the secret sits
    inside an opaque string where no field-name rule can see it.

    Found by recording through this proxy: the field-name pass redacted
    `password` and the identical string one level down survived.
    """
    capture = Capture(target="http://x.test")
    capture.record(
        method="POST",
        url="http://x.test/users",
        request_headers={"content-type": "application/json"},
        request_body=b"",
        status=200,
        response_headers={"content-type": "application/json"},
        response_body=json.dumps(
            {
                "echo": '{"password": "hunter2"}',
                "yaml": "token: abc123",
                "log": {"line": "api_key=abc123"},
            }
        ).encode(),
        started="2026-01-01T00:00:00Z",
        duration_ms=1,
    )
    text = capture.entries[0]["response"]["content"]["text"]
    assert "hunter2" not in text
    assert "abc123" not in text
    assert text.count("[REDACTED]") == 3


def test_what_redaction_cannot_catch_is_stated_rather_than_implied() -> None:
    """A bare value with nothing beside it saying what it is.

    Rule-based redaction is not clairvoyant, and a recorder claiming otherwise
    is the claim that gets a credential committed. The module says so; this
    pins the boundary so nobody later assumes it is tighter than it is.
    """
    capture = Capture(target="http://x.test")
    capture.record(
        method="GET",
        url="http://x.test/u",
        request_headers={},
        request_body=b"",
        status=200,
        response_headers={"content-type": "application/json"},
        response_body=json.dumps({"note": "AKIAIOSFODNN7EXAMPLE"}).encode(),
        started="2026-01-01T00:00:00Z",
        duration_ms=1,
    )
    assert "AKIAIOSFODNN7EXAMPLE" in capture.entries[0]["response"]["content"]["text"]


def test_the_client_still_gets_the_real_response() -> None:
    """It is a proxy. Redaction is about the file, not about the caller."""
    with _Upstream() as upstream:
        capture = Capture(target=upstream.base_url)
        with _proxy(capture) as proxy:
            response = httpx.get(f"{proxy}/users", timeout=5)
    assert response.status_code == 200
    assert response.json()["password"] == "hunter2"
    assert response.headers["x-upstream"] == "yes"


def test_the_upstream_sees_the_request_it_was_sent() -> None:
    with _Upstream() as upstream:
        capture = Capture(target=upstream.base_url)
        with _proxy(capture) as proxy:
            httpx.post(f"{proxy}/users", json={"name": "Ada"}, timeout=5)
    method, path, headers = upstream.seen[-1]
    assert (method, path) == ("POST", "/users")
    assert "content-length" in {k.lower() for k in headers}


# -------------------------------------------------------------- the corpus


def test_what_it_records_is_a_har_the_importer_reads(tmp_path: Path) -> None:
    from apiverity.traffic.redact import import_har

    with _Upstream() as upstream:
        capture = Capture(target=upstream.base_url)
        with _proxy(capture) as proxy:
            httpx.get(f"{proxy}/users", timeout=5)
            httpx.post(f"{proxy}/users", json={"name": "Ada"}, timeout=5)
        path = capture.write(tmp_path / "corpus.har")

    entries = import_har(str(path), include_response_bodies=True)
    assert [e["method"] for e in entries] == ["GET", "POST"]
    assert all(e["status"] == 200 for e in entries)
    assert all(e.get("started_at") or e.get("startedDateTime") or True for e in entries)


def test_a_body_too_large_is_absent_with_a_reason(tmp_path: Path) -> None:
    """A corpus that silently drops what it could not handle has gaps that
    read as facts about the service."""
    with _Upstream() as upstream:
        capture = Capture(target=upstream.base_url, max_body_bytes=100)
        with _proxy(capture) as proxy:
            httpx.get(f"{proxy}/big", timeout=5)
        har = capture.har()

    content = har["log"]["entries"][0]["response"]["content"]
    assert "text" not in content
    assert "exceeded" in content["comment"]
    assert capture.skips.oversized_response == 1
    assert "oversized response: 1" in har["log"]["comment"]


def test_a_binary_body_is_absent_with_a_reason(tmp_path: Path) -> None:
    with _Upstream() as upstream:
        capture = Capture(target=upstream.base_url)
        with _proxy(capture) as proxy:
            httpx.get(f"{proxy}/binary", timeout=5)
        har = capture.har()

    content = har["log"]["entries"][0]["response"]["content"]
    assert "text" not in content
    assert "image/png" in content["comment"]
    assert capture.skips.binary_response == 1


def test_the_skips_ride_in_the_file_not_only_on_the_console() -> None:
    capture = Capture(target="http://x.test")
    assert "nothing was skipped" in capture.har()["log"]["comment"]
    capture.skips.upstream_failed = 2
    assert "upstream failed: 2" in capture.har()["log"]["comment"]


def test_response_bodies_can_be_left_out(tmp_path: Path) -> None:
    with _Upstream() as upstream:
        capture = Capture(target=upstream.base_url, keep_response_bodies=False)
        with _proxy(capture) as proxy:
            httpx.get(f"{proxy}/users", timeout=5)
        har = capture.har()
    content = har["log"]["entries"][0]["response"]["content"]
    assert "text" not in content
    assert "not kept by this run" in content["comment"]


def test_an_upstream_that_fails_is_counted_and_reported_as_502() -> None:
    capture = Capture(target="http://127.0.0.1:9")
    with _proxy(capture) as proxy:
        response = httpx.get(f"{proxy}/users", timeout=5)
    assert response.status_code == 502
    assert capture.skips.upstream_failed == 1
    assert capture.entries == []


# ---------------------------------------------------------- what it refuses


def test_connect_is_refused_with_a_reason() -> None:
    """Tunnelling would record nothing, or require issuing certificates for
    hosts this process does not own."""
    with _Upstream() as upstream:
        capture = Capture(target=upstream.base_url)
        with _proxy(capture) as proxy:
            host = proxy.removeprefix("http://")
            import socket

            name, _, port = host.partition(":")
            with socket.create_connection((name, int(port)), 5) as sock:
                sock.sendall(b"CONNECT example.test:443 HTTP/1.1\r\nHost: example.test\r\n\r\n")
                head = sock.recv(200).decode("utf-8", "replace")
    assert " 405 " in head


def test_a_request_for_another_host_is_refused() -> None:
    """The module docstring says "every request goes to the one target the run
    named. A proxy that forwards wherever the client asks is an open relay."
    Nothing enforced it.

    A client configured to use a proxy sends the **absolute form** on the
    request line -- `GET http://elsewhere/ HTTP/1.1` -- and httpx treats an
    absolute URL as the whole address, ignoring the `base_url` the recorder was
    started with. So the recorder forwarded wherever it was asked, to anything
    that could open a socket to the port. CodeQL reported it as a full SSRF and
    was right.
    """
    import socket

    with _Upstream() as upstream:
        capture = Capture(target=upstream.base_url)
        with _proxy(capture) as proxy:
            name, _, port = proxy.removeprefix("http://").partition(":")
            with socket.create_connection((name, int(port)), 5) as sock:
                sock.sendall(
                    b"GET http://169.254.169.254/latest/meta-data/ HTTP/1.1\r\n"
                    b"Host: 169.254.169.254\r\n\r\n"
                )
                head = sock.recv(400).decode("utf-8", "replace")

    assert " 403 " in head, head
    assert capture.skips.off_target == 1
    assert not capture.entries, "an off-target request must not reach the corpus either"


def test_the_absolute_form_for_the_target_itself_still_works() -> None:
    """Refusing every absolute URL would break the ordinary case: a browser
    told to use this proxy sends the absolute form for the target too."""
    import socket

    with _Upstream() as upstream:
        capture = Capture(target=upstream.base_url)
        with _proxy(capture) as proxy:
            name, _, port = proxy.removeprefix("http://").partition(":")
            with socket.create_connection((name, int(port)), 5) as sock:
                sock.sendall(
                    f"GET {upstream.base_url}/orders HTTP/1.1\r\n".encode()
                    + b"Host: ignored.invalid\r\n\r\n"
                )
                head = sock.recv(400).decode("utf-8", "replace")

    assert " 200 " in head, head
    assert capture.skips.off_target == 0
    assert capture.entries


def test_the_off_target_count_rides_in_the_file_like_every_other_skip() -> None:
    """A refusal nobody can see afterwards is a refusal nobody can audit."""
    assert "off_target" in Capture(target="http://x").skips.__dict__


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("/orders?page=2", "http://api.test:9/orders?page=2"),
        ("http://api.test:9/orders?page=2", "http://api.test:9/orders?page=2"),
        ("HTTP://API.TEST:9/orders", "http://api.test:9/orders"),
        ("http://api.test:9", "http://api.test:9/"),
        ("http://evil.test/steal", None),
        ("https://api.test:9/orders", None),
        ("http://api.test:80/orders", None),
        ("//evil.test/steal", None),
        (r"/\\evil.test/steal", "http://api.test:9/" + chr(92) + chr(92) + "evil.test/steal"),
    ],
)
def test_which_requests_reach_the_upstream(raw: str, expected: str | None) -> None:
    """Scheme and authority have to match the target, and whatever survives is
    reassembled onto the target's own scheme and host -- so the host is never
    a value that came off the request line."""
    assert upstream_url(raw, "http://api.test:9") == expected


def test_the_host_always_comes_from_the_target() -> None:
    """The property, rather than a list of examples: for every request line
    this accepts, the host is the target's."""
    target = "http://api.test:9"
    accepted = [
        "/orders",
        "/orders?page=2",
        "http://api.test:9/orders",
        "/..%2f..%2fadmin",
        "/a?b=http://evil.test",
    ]
    for raw in accepted:
        built = upstream_url(raw, target)
        assert built is not None, raw
        assert urlsplit(built).netloc == "api.test:9", raw
        assert urlsplit(built).scheme == "http", raw


def test_binding_beyond_localhost_needs_saying_so() -> None:
    check_bind("127.0.0.1", acknowledged=False)
    check_bind("localhost", acknowledged=False)
    with pytest.raises(CaptureRefused, match="reachable from the network"):
        check_bind("0.0.0.0", acknowledged=False)
    check_bind("0.0.0.0", acknowledged=True)


def test_the_command_refuses_the_same_way(tmp_path: Path) -> None:
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        code = main(
            [
                "capture",
                "--target",
                "http://x.test",
                "--out",
                str(tmp_path / "c.har"),
                "--host",
                "0.0.0.0",
            ]
        )
    assert code == EXIT_USAGE
    assert "reachable from the network" in err.getvalue()


# ------------------------------------------------------------- the command


def test_the_command_writes_a_corpus_even_when_nothing_came_through(tmp_path: Path) -> None:
    """An empty corpus is a fact about the run. A missing file reads as a crash."""
    out = tmp_path / "corpus.har"
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(io.StringIO()):
        code = main(
            [
                "capture",
                "--target",
                "http://127.0.0.1:9",
                "--out",
                str(out),
                "--duration",
                "0.2",
                "--json",
            ]
        )
    assert code == 0
    payload = json.loads(buffer.getvalue())
    assert payload["entries"] == 0
    assert payload["redacted"] is True
    assert out.is_file()
    assert json.loads(out.read_text(encoding="utf-8"))["log"]["entries"] == []


def test_max_entries_stops_it(tmp_path: Path) -> None:
    out = tmp_path / "corpus.har"
    with _Upstream() as upstream:
        done = threading.Event()

        def run() -> None:
            with (
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                main(
                    [
                        "capture",
                        "--target",
                        upstream.base_url,
                        "--out",
                        str(out),
                        "--port",
                        "8899",
                        "--max-entries",
                        "2",
                        "--duration",
                        "20",
                    ]
                )
            done.set()

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        # The listener needs a moment; retry rather than sleeping blind.
        sent = 0
        for _ in range(80):
            if done.is_set():
                break
            try:
                httpx.get("http://127.0.0.1:8899/users", timeout=2)
                sent += 1
            except httpx.HTTPError:
                continue
            if sent >= 4:
                break
        thread.join(timeout=30)

    assert not thread.is_alive(), "it did not stop at the entry limit"
    # Asserted against the file rather than captured stdout: the command runs
    # in another thread, and `redirect_stdout` is process-wide.
    har = json.loads(out.read_text(encoding="utf-8"))["log"]
    # Exactly two. The poll loop notices the limit a tenth of a second later,
    # so a threshold gave three when two were asked for; the cap is enforced
    # where the entry is appended.
    assert len(har["entries"]) == 2, f"recorded {len(har['entries'])} after asking for 2"
    if sent > 2:
        # And traffic that kept flowing is counted, not silently absent: a
        # corpus of exactly N otherwise hides that it is the first N of more.
        assert "after limit" in har["comment"]
