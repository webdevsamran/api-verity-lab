"""Authorization checked between two identities.

Every other check in this project reads a contract or watches one identity talk
to a service. Neither can see the two failures that matter most in practice,
because both are about what happens when a *different* caller asks:

- **BOLA** (OWASP API1): a resource one tenant created, read by another. The
  request is well-formed, the schema is satisfied, the status is 200, and the
  data belongs to somebody else.
- **BFLA** (OWASP API5): an operation the contract says needs a scope,
  answered for a caller who does not hold it.

The servers below are deliberately wrong in exactly one way each, because a
probe that reports nothing against a correct service proves only that it ran.
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

from apiverity.cli.main import main
from apiverity.security.authz import (
    DENIED,
    AuthzReport,
    Identity,
    probe_function_authorization,
    probe_object_authorization,
)
from apiverity.specs.loader import detect_and_load

_ROOT = Path(__file__).resolve().parents[2]
_CONTRACT = "fixtures/apis/templates/openapi.yaml"


# ------------------------------------------------------- the probe itself


def _recording_transport(answer: dict[tuple[str, str], int]) -> Any:
    """A transport with a fixed answer per (identity, method)."""
    calls: list[tuple[str, str, str]] = []

    def transport(identity: str, method: str, path: str, _body: Any) -> tuple[int, Any]:
        calls.append((identity, method, path))
        status = answer.get((identity, method), 403)
        body = {"id": "1"} if status < 400 else {"error": "no"}
        return status, body

    transport.calls = calls  # type: ignore[attr-defined]
    return transport


def test_a_service_that_refuses_the_other_identity_produces_nothing() -> None:
    transport = _recording_transport({("alice", "POST"): 201})
    report = probe_object_authorization(
        transport,
        "/widgets",
        "/widgets/{id}",
        Identity("alice"),
        Identity("bob"),
        create_payload={"name": "x"},
    )
    assert report.findings == []
    assert report.attempts == 3


def test_a_clean_report_still_says_how_many_attempts_it_made() -> None:
    """ "Twelve attempts, all refused" and "nothing happened" look identical in
    a summary line, and only one of them is evidence."""
    transport = _recording_transport({("alice", "POST"): 201})
    report = probe_object_authorization(
        transport,
        "/widgets",
        "/widgets/{id}",
        Identity("alice"),
        Identity("bob"),
        create_payload={"name": "x"},
    )
    assert report.attempts == 3
    assert report.ok


@pytest.mark.parametrize(
    ("method", "rule"),
    [("GET", "AUTHZ-BOLA-READ"), ("PATCH", "AUTHZ-BOLA-WRITE"), ("DELETE", "AUTHZ-BOLA-DELETE")],
)
def test_each_way_in_is_reported_separately(method: str, rule: str) -> None:
    """A service that hides another tenant's object from a GET and accepts a
    PATCH on it is checking visibility somewhere that is not the write path.
    Stopping at the first finding would hide the second."""
    transport = _recording_transport({("alice", "POST"): 201, ("bob", method): 200})
    report = probe_object_authorization(
        transport,
        "/widgets",
        "/widgets/{id}",
        Identity("alice"),
        Identity("bob"),
        create_payload={"name": "x"},
    )
    assert [f.rule_id for f in report.findings] == [rule]
    assert not report.ok


def test_all_three_are_reported_when_all_three_leak() -> None:
    transport = _recording_transport(
        {
            ("alice", "POST"): 201,
            ("bob", "GET"): 200,
            ("bob", "PATCH"): 200,
            ("bob", "DELETE"): 204,
        }
    )
    report = probe_object_authorization(
        transport,
        "/widgets",
        "/widgets/{id}",
        Identity("alice"),
        Identity("bob"),
        create_payload={"name": "x"},
    )
    assert len(report.findings) == 3


@pytest.mark.parametrize("status", sorted(DENIED))
def test_every_denial_status_counts_as_a_denial(status: int) -> None:
    """404 counts. Hiding the existence of another tenant's object is a
    legitimate and common way to refuse, and reporting it as a leak would make
    the probe unusable against services that do the right thing."""
    transport = _recording_transport({("alice", "POST"): 201, ("bob", "GET"): status})
    report = probe_object_authorization(
        transport,
        "/widgets",
        "/widgets/{id}",
        Identity("alice"),
        Identity("bob"),
        create_payload={"name": "x"},
    )
    assert [f.rule_id for f in report.findings if f.rule_id == "AUTHZ-BOLA-READ"] == []


def test_a_create_that_fails_reports_that_nothing_was_probed() -> None:
    """No object means no probe, and a report that said nothing would read as
    a service that refused every attempt."""
    transport = _recording_transport({("alice", "POST"): 500})
    report = probe_object_authorization(
        transport,
        "/widgets",
        "/widgets/{id}",
        Identity("alice"),
        Identity("bob"),
        create_payload={"name": "x"},
    )
    assert report.findings == []
    assert report.attempts == 0
    assert "nothing to probe" in report.not_probed[0][1]


def test_a_collection_with_no_delete_says_so() -> None:
    transport = _recording_transport({("alice", "POST"): 201})
    report = probe_object_authorization(
        transport,
        "/orders",
        "/orders/{id}",
        Identity("alice"),
        Identity("bob"),
        create_payload={},
        deletable=False,
    )
    assert report.attempts == 2
    assert any("declares no DELETE" in reason for _key, reason in report.not_probed)


# ------------------------------------------------------------------- BFLA


@pytest.fixture(scope="module")
def service():
    loaded, _findings, _plugin = detect_and_load(_CONTRACT)
    return loaded


def test_an_operation_answered_without_its_scope_is_reported(service) -> None:
    transport = _recording_transport({("bob", "GET"): 200})
    report = probe_function_authorization(transport, service, Identity("bob", scopes=[]))
    assert [f.rule_id for f in report.findings] == ["AUTHZ-BFLA"]
    assert "items:read" in report.findings[0].message


def test_an_identity_that_holds_the_scope_is_not_probed(service) -> None:
    transport = _recording_transport({("bob", "GET"): 200})
    report = probe_function_authorization(
        transport, service, Identity("bob", scopes=["items:read"])
    )
    assert report.findings == []
    assert report.attempts == 0


def test_unstated_scopes_are_not_treated_as_none(service) -> None:
    """`scopes: []` and "not stated" are different, and only the first is a
    basis for a finding. Assuming an identity holds nothing would report every
    operation it can reach as a defect."""
    transport = _recording_transport({("bob", "GET"): 200})
    report = probe_function_authorization(transport, service, Identity("bob", scopes=None))
    assert [f.rule_id for f in report.findings] == ["AUTHZ-SCOPES-UNDECLARED"]
    assert report.ok  # INFO, not a failure
    assert report.attempts == 0


def test_a_write_is_never_issued_as_a_bfla_probe(service) -> None:
    """A probe that issued the DELETE it was testing for would be
    indistinguishable from the attack."""
    transport = _recording_transport({("bob", "GET"): 403})
    probe_function_authorization(transport, service, Identity("bob", scopes=[]))
    assert transport.calls, "nothing was probed, so this proves nothing"
    assert all(method in ("GET", "HEAD", "OPTIONS") for _who, method, _path in transport.calls)


# ------------------------------------------------------------ the command


class _Leaky(BaseHTTPRequestHandler):
    """Answers 200 to everyone for everything. One defect, several symptoms."""

    def log_message(self, *_args: Any) -> None:
        return

    def _answer(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        body = json.dumps({"id": "1", "name": "alice-secret"}).encode()
        self.send_response(201 if self.command == "POST" else 200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = do_POST = do_PATCH = do_DELETE = _answer


class _Strict(_Leaky):
    """Refuses anyone whose bearer token is not `alice`."""

    def _answer(self) -> None:
        if self.headers.get("Authorization") != "Bearer alice-token":
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                self.rfile.read(length)
            self.send_response(403)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        super()._answer()

    do_GET = do_POST = do_PATCH = do_DELETE = _answer


@pytest.fixture(params=[_Leaky, _Strict], ids=["leaky", "strict"])
def server(request):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), request.param)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}", request.param is _Leaky
    finally:
        httpd.shutdown()
        httpd.server_close()


@pytest.fixture
def profiles(tmp_path: Path, monkeypatch: Any) -> str:
    monkeypatch.setenv("ALICE_TOKEN", "alice-token")
    monkeypatch.setenv("BOB_TOKEN", "bob-token")
    path = tmp_path / "profiles.yaml"
    path.write_text(
        "profiles:\n"
        "  - {name: alice, kind: bearer, token_env: ALICE_TOKEN, scopes: [items:read]}\n"
        "  - {name: bob, kind: bearer, token_env: BOB_TOKEN, scopes: []}\n",
        encoding="utf-8",
    )
    return str(path)


def _run(argv: list[str]) -> tuple[int, dict[str, Any], str]:
    out, err = io.StringIO(), io.StringIO()
    code = 0
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = main(argv)
        except SystemExit as stop:
            code = int(stop.code or 0)
    try:
        return code, json.loads(out.getvalue()), err.getvalue()
    except ValueError:
        return code, {}, err.getvalue()


def _argv(base_url: str, profiles: str, *extra: str) -> list[str]:
    return [
        "--no-config",
        "test",
        _CONTRACT,
        "--base-url",
        base_url,
        "--authz",
        "--include-mutations",
        "--auth-profiles",
        profiles,
        "--auth-profile",
        "alice",
        "--as",
        "bob",
        "--json",
        *extra,
    ]


def test_the_command_reports_a_leak_and_clears_a_strict_service(server, profiles: str) -> None:
    base_url, leaky = server
    code, payload, _err = _run(_argv(base_url, profiles))
    rules = {f["rule_id"] for f in payload["authz"]["findings"]}
    if leaky:
        assert code != 0
        assert {"AUTHZ-BOLA-READ", "AUTHZ-BOLA-WRITE", "AUTHZ-BOLA-DELETE"} <= rules
        assert "AUTHZ-BFLA" in rules
    else:
        assert code == 0
        assert rules == set()
        assert payload["authz"]["attempts"] > 0


def test_it_will_not_run_with_one_identity(profiles: str) -> None:
    """An identity cannot be refused its own data."""
    argv = _argv("http://127.0.0.1:1", profiles)
    argv[argv.index("bob")] = "alice"
    code, _payload, err = _run(argv)
    assert code != 0
    assert "are both 'alice'" in err


def test_it_will_not_run_without_two_profiles() -> None:
    code, _payload, err = _run(
        [
            "--no-config",
            "test",
            _CONTRACT,
            "--base-url",
            "http://127.0.0.1:1",
            "--authz",
            "--include-mutations",
        ]
    )
    assert code != 0
    assert "needs two identities" in err


def test_it_will_not_write_without_being_told(profiles: str) -> None:
    argv = [a for a in _argv("http://127.0.0.1:1", profiles) if a != "--include-mutations"]
    code, _payload, err = _run(argv)
    assert code != 0
    assert "--include-mutations" in err
    assert "attempts unauthorized access" in err


def test_the_rules_are_catalogued() -> None:
    """A rule nobody can explain gets suppressed rather than fixed."""
    from apiverity.rules.check_catalog import catalog

    known = catalog()
    for rule in (
        "AUTHZ-BOLA-READ",
        "AUTHZ-BOLA-WRITE",
        "AUTHZ-BOLA-DELETE",
        "AUTHZ-BFLA",
        "AUTHZ-SCOPES-UNDECLARED",
    ):
        assert rule in known, rule
        assert known[rule].produced_by == "test --authz"


def test_the_report_is_empty_rather_than_absent_for_a_contract_with_no_objects(
    profiles: str,
) -> None:
    """A contract with no create-and-read-back pair has no object for one
    identity to make and another to be refused."""
    code, payload, _err = _run(
        [
            "--no-config",
            "test",
            "fixtures/apis/slo/openapi.yaml",
            "--base-url",
            "http://127.0.0.1:1",
            "--authz",
            "--include-mutations",
            "--auth-profiles",
            profiles,
            "--auth-profile",
            "alice",
            "--as",
            "bob",
            "--json",
        ]
    )
    assert code == 0
    assert payload["authz"]["attempts"] == 0
    assert any("no collection" in n["reason"] for n in payload["authz"]["not_probed"])


def test_the_module_reachability_walk_sees_it() -> None:
    """It would otherwise join the library-only list, which is empty."""
    assert (_ROOT / "apiverity" / "security" / "authz.py").is_file()
    report = AuthzReport()
    assert report.ok and report.attempts == 0
