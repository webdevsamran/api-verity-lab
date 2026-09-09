"""Routes the contract says are gone, that the server still answers.

Every other check here asks whether the server does what the contract says.
This asks the opposite: does the server still do something the contract stopped
saying? A route is removed from the document in one pull request and from the
deployment in another, and nothing fails in between -- the docs are right, the
tests pass, the gate is green, and the endpoint keeps answering anyone who
remembers the URL.

Run against a real HTTP server rather than a stub, because the whole check is
about what a status code means and a mock that returns whatever it is told
proves nothing about that.
"""

from __future__ import annotations

import contextlib
import io
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from apiverity.cli.commands.common import EXIT_FINDINGS, EXIT_USAGE
from apiverity.cli.main import main
from apiverity.runtime.ghosts import (
    Candidate,
    audit,
    removed_operations,
    unmatched_paths,
)
from apiverity.specs.loader import detect_and_load

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[2]


class _Deployment:
    """A server that still answers some routes nobody declares any more."""

    def __init__(self, alive: dict[str, int]) -> None:
        self.alive = alive
        self.seen: list[tuple[str, str]] = []
        server = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args: Any) -> None:  # pragma: no cover - quiet
                return

            def _respond(self) -> None:
                server.seen.append((self.command, self.path))
                status = server.alive.get(self.path, 404)
                body = b"{}"
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            do_GET = _respond
            do_HEAD = _respond
            do_POST = _respond
            do_DELETE = _respond

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def __enter__(self) -> _Deployment:
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=5)


def _ids(report: Any) -> dict[str, list[Any]]:
    out: dict[str, list[Any]] = {}
    for finding in report.findings:
        out.setdefault(finding.rule_id, []).append(finding)
    return out


# ----------------------------------------------------------------- candidates


def test_candidates_come_from_what_a_previous_contract_declared() -> None:
    old, _, _ = detect_and_load(str(_ROOT / "fixtures/apis/versioned/v1.yaml"))
    new, _, _ = detect_and_load(str(_ROOT / "fixtures/apis/versioned/v2.yaml"))
    candidates = removed_operations(old, new)
    assert [c.key for c in candidates] == ["DELETE /users/{id}"]
    assert candidates[0].source.startswith("removed from")


def test_candidates_come_from_paths_real_traffic_used() -> None:
    candidates = unmatched_paths(["GET /admin/legacy", "/debug"], "traffic.har")
    assert [c.key for c in candidates] == ["GET /admin/legacy", "GET /debug"]
    assert all(c.source == "seen in traffic.har" for c in candidates)


def test_nothing_is_ever_guessed() -> None:
    """A tool that enumerates likely paths against a host is a scanner."""
    assert unmatched_paths([], "x.har") == []


# --------------------------------------------------------------------- audit


def test_a_route_that_still_answers_is_an_error() -> None:
    with _Deployment({"/admin/legacy": 200}) as server:
        report = audit([Candidate("GET", "/admin/legacy", "removed from v1.yaml")], server.base_url)
    ghost = _ids(report)["GHOST-ROUTE"][0]
    assert ghost.severity == "ERROR"
    assert ghost.status == 200
    assert "removed from the document and not from the deployment" in ghost.message


def test_a_route_that_is_really_gone_is_recorded_as_evidence() -> None:
    """The good news is worth keeping: it is the answer to an audit question."""
    with _Deployment({}) as server:
        report = audit([Candidate("GET", "/admin/legacy", "removed from v1.yaml")], server.base_url)
    gone = _ids(report)["GHOST-GONE"][0]
    assert gone.severity == "INFO"
    assert gone.status == 404


def test_a_deliberate_410_is_distinguished_from_a_404() -> None:
    with _Deployment({"/retired": 410}) as server:
        report = audit([Candidate("GET", "/retired", "removed from v1.yaml")], server.base_url)
    assert _ids(report)["GHOST-GONE"][0].status == 410


def test_a_405_means_the_path_survived_even_though_the_method_did_not() -> None:
    with _Deployment({"/orders": 405}) as server:
        report = audit([Candidate("GET", "/orders", "removed from v1.yaml")], server.base_url)
    finding = _ids(report)["GHOST-PATH-ALIVE"][0]
    assert finding.severity == "WARN"
    assert "Something is still routed there" in finding.message


def test_a_write_is_never_sent() -> None:
    """A removed DELETE cannot be probed by sending a DELETE."""
    with _Deployment({"/users/1": 200}) as server:
        report = audit(
            [Candidate("DELETE", "/users/{id}", "removed from v1.yaml")], server.base_url
        )
        assert server.seen == []
    finding = _ids(report)["GHOST-NOT-PROBED"][0]
    assert finding.severity == "INFO"
    assert "DELETE is a write" in finding.message


def test_an_unprobed_candidate_is_reported_rather_than_dropped() -> None:
    """An audit that quietly skips half its input is worse than one that says so."""
    with _Deployment({}) as server:
        report = audit([Candidate("POST", "/things", "seen in traffic.har")], server.base_url)
    assert report.candidates == 1
    assert report.probed == 0
    assert "GHOST-NOT-PROBED" in _ids(report)


def test_a_templated_path_is_filled_from_the_contract_that_declared_it() -> None:
    old, _, _ = detect_and_load(str(_ROOT / "fixtures/apis/versioned/v1.yaml"))
    with _Deployment({}) as server:
        audit([Candidate("GET", "/users/{id}", "removed from v1.yaml")], server.base_url, old=old)
        (method, path), *_ = server.seen
    assert method == "GET"
    assert "{" not in path, f"a templated path reached the wire: {path}"


def test_an_unreachable_target_establishes_nothing() -> None:
    report = audit(
        [Candidate("GET", "/x", "removed from v1.yaml")], "http://127.0.0.1:1", timeout=0.4
    )
    finding = _ids(report)["GHOST-UNREACHABLE"][0]
    assert finding.severity == "INFO"
    assert "establishes nothing" in finding.message


# ----------------------------------------------------------------------- CLI


def _run(argv: list[str]) -> tuple[int, dict[str, Any], str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    text = out.getvalue()
    return code, (json.loads(text) if text.strip().startswith("{") else {}), err.getvalue()


def _har(tmp_path: Path, path: str) -> str:
    """A recorded request to a path the contract does not declare."""
    log = {
        "log": {
            "entries": [
                {
                    "startedDateTime": "2026-03-01T09:00:00.000Z",
                    "time": 4.0,
                    "request": {
                        "method": "GET",
                        "url": f"https://api.example.com{path}",
                        "headers": [],
                        "queryString": [],
                    },
                    "response": {"status": 200, "headers": [], "content": {}},
                }
            ]
        }
    }
    target = tmp_path / "traffic.har"
    target.write_text(json.dumps(log), encoding="utf-8")
    return str(target)


def test_the_command_finds_a_ghost_from_recorded_traffic(tmp_path: Path) -> None:
    with _Deployment({"/admin/legacy": 200}) as server:
        code, payload, _ = _run(
            [
                "ghosts",
                str(_ROOT / "fixtures/apis/crud/openapi.yaml"),
                "--corpus",
                _har(tmp_path, "/admin/legacy"),
                "--base-url",
                server.base_url,
                "--json",
            ]
        )
    assert code == EXIT_FINDINGS
    assert "GHOST-ROUTE" in {f["rule_id"] for f in payload["findings"]}


def test_a_removed_write_is_reported_without_being_sent() -> None:
    """v1 -> v2 drops a DELETE, and a DELETE is not something to send."""
    with _Deployment({}) as server:
        code, payload, _ = _run(
            [
                "ghosts",
                str(_ROOT / "fixtures/apis/versioned/v2.yaml"),
                "--was",
                str(_ROOT / "fixtures/apis/versioned/v1.yaml"),
                "--base-url",
                server.base_url,
                "--json",
            ]
        )
        assert server.seen == []
    assert code == 0, "an unprobed candidate is not a finding a gate should fail on"
    assert {f["rule_id"] for f in payload["findings"]} == {"GHOST-NOT-PROBED"}


def test_no_candidates_is_a_usage_error_not_a_pass() -> None:
    """Nothing was asked, so nothing was established.

    A green run here would be the most misleading output in the tool.
    """
    code, _, err = _run(
        [
            "ghosts",
            str(_ROOT / "fixtures/apis/versioned/v2.yaml"),
            "--base-url",
            "http://127.0.0.1:1",
        ]
    )
    assert code == EXIT_USAGE
    assert "no candidate routes" in err


def test_the_artifact_uses_the_shared_finding_shape() -> None:
    with _Deployment({}) as server:
        _, payload, _ = _run(
            [
                "ghosts",
                str(_ROOT / "fixtures/apis/versioned/v2.yaml"),
                "--was",
                str(_ROOT / "fixtures/apis/versioned/v1.yaml"),
                "--base-url",
                server.base_url,
                "--json",
            ]
        )
    for finding in payload["findings"]:
        assert {"rule_id", "severity", "message"} <= set(finding)
