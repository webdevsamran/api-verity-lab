"""`apiverity monitor` against a server that answers, then does not, then does.

The unit tests cover the differ. This covers the thing the differ cannot be
trusted on alone: that a real `drift` run against a real socket, with the
process killed underneath it, does not come back reading like a fix.

A stub returning canned findings would prove nothing here, because the whole
question is what `drift` produces when the connection is refused -- and what it
produces is findings, not an exception, so an exit-code check alone would miss
it.
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

from apiverity.cli.commands.common import EXIT_FINDINGS, EXIT_OK, EXIT_UNREACHABLE, EXIT_USAGE
from apiverity.cli.main import main

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[2]
_SPEC = str(_ROOT / "fixtures/apis/drift/openapi.yaml")


class _Service:
    """Two declared operations, one of which can be made to answer wrongly."""

    def __init__(self, port: int = 0) -> None:
        self.conforming = True
        service = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args: Any) -> None:  # pragma: no cover - quiet
                return

            def do_GET(self) -> None:
                if self.path.startswith("/reports"):
                    payload: Any = ["r-1"]
                elif service.conforming:
                    payload = {"id": "u-1", "name": "Ada", "email": "ada@example.test"}
                else:
                    # `email` is required by the contract. Dropping it is the
                    # drift this monitor is watching for.
                    payload = {"id": "u-1", "name": "Ada"}
                body = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("X-Request-Id", "fixed")
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self._httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def __enter__(self) -> _Service:
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=5)


def _monitor(state: Path, base_url: str, out: Path | None = None) -> tuple[int, dict[str, Any]]:
    argv = ["monitor", "--state", str(state), "--json"]
    if out:
        argv += ["--out", str(out)]
    argv += ["--", "drift", _SPEC, "--base-url", base_url, "--timeout", "2"]
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = main(argv)
    return code, json.loads(buffer.getvalue())


def test_a_service_that_goes_down_never_reads_as_a_fix(tmp_path: Path) -> None:
    """The whole point of the command, end to end over a real socket."""
    state = tmp_path / "state.json"
    service = _Service()
    with service:
        port = service.port
        # 1. Baseline. There is already drift, and nothing is alerted.
        service.conforming = False
        code, first = _monitor(state, service.base_url)
        assert first["baseline"] is True
        assert first["findings"] == [], "the baseline run alerted on the existing state"
        assert code == EXIT_OK
        known = first["unchanged_count"]
        assert known, "the fixture produced no drift to carry"

        # 2. Steady state. Same findings, nothing to say.
        code, second = _monitor(state, service.base_url)
        assert second["findings"] == [] and second["resolved"] == []
        assert code == EXIT_OK

    # 3. The service is gone. `drift` still exits cleanly with findings of its
    #    own, so nothing but the unobservable-rule handling saves this.
    code, third = _monitor(state, f"http://127.0.0.1:{port}")
    assert third["resolved"] == [], "findings about an unreachable service were called fixed"
    assert third["inconclusive"], "an outage was reported as a normal run"
    assert third["carried_forward"] == known
    assert code == EXIT_UNREACHABLE

    # 4. Back up, and still drifting. The carried findings are not re-announced.
    again = _Service(port=port)
    with again:
        again.conforming = False
        code, fourth = _monitor(state, again.base_url)
        assert fourth["findings"] == [], "carried findings were announced as new on recovery"
        assert fourth["inconclusive"] is None
        assert code == EXIT_OK

        # 5. Fixed for real. Now -- and only now -- it resolves.
        again.conforming = True
        code, fifth = _monitor(state, again.base_url)
        assert [f["rule_id"] for f in fifth["resolved"]] == ["DRIFT-MISSING-FIELD"]
        assert code == EXIT_OK


def test_new_drift_is_reported_and_fails_the_run(tmp_path: Path) -> None:
    state = tmp_path / "state.json"
    out = tmp_path / "report.json"
    with _Service() as service:
        _monitor(state, service.base_url)  # baseline: conforming
        service.conforming = False
        code, second = _monitor(state, service.base_url, out=out)

    assert [f["rule_id"] for f in second["findings"]] == ["DRIFT-MISSING-FIELD"]
    assert code == EXIT_FINDINGS, "new drift did not fail the run"

    # The written report is what `notify` reads, and it holds the new finding
    # rather than the standing state.
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["command"] == "monitor"
    assert [f["rule_id"] for f in written["findings"]] == ["DRIFT-MISSING-FIELD"]


def test_one_state_file_belongs_to_one_command(tmp_path: Path) -> None:
    """Sharing it makes each command's findings read as the other's turnover."""
    state = tmp_path / "state.json"
    with _Service() as service:
        _monitor(state, service.base_url)
        code = main(["monitor", "--state", str(state), "--", "validate", _SPEC])
    assert code == EXIT_USAGE


def test_a_run_that_could_not_start_is_inconclusive_not_empty(tmp_path: Path) -> None:
    """The spec moves and the cron entry does not. Nothing is resolved by that."""
    spec = tmp_path / "openapi.yaml"
    spec.write_text(Path(_SPEC).read_text(encoding="utf-8"), encoding="utf-8")
    state = tmp_path / "state.json"

    def run() -> tuple[int, dict[str, Any]]:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = main(
                [
                    "monitor",
                    "--state",
                    str(state),
                    "--json",
                    "--",
                    "drift",
                    str(spec),
                    "--base-url",
                    base_url,
                    "--timeout",
                    "2",
                ]
            )
        return code, json.loads(buffer.getvalue())

    with _Service() as service:
        base_url = service.base_url
        run()
        service.conforming = False
        _, second = run()
        assert second["findings"], "the fixture produced nothing to lose"

        spec.unlink()
        code, third = run()

    assert third["inconclusive"], "a run that never started was reported as a clean one"
    assert third["resolved"] == [], "a missing spec resolved every known finding"
    assert code == EXIT_UNREACHABLE


def test_monitor_refuses_to_monitor_itself(tmp_path: Path) -> None:
    assert main(["monitor", "--state", str(tmp_path / "s.json"), "--", "monitor"]) == EXIT_USAGE


def test_nothing_to_run_is_a_usage_error(tmp_path: Path) -> None:
    assert main(["monitor", "--state", str(tmp_path / "s.json")]) == EXIT_USAGE
