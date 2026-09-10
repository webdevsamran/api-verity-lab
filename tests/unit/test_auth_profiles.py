"""Credentials by reference, and the two things nobody had ever run.

`apiverity/traffic/auth.py` is the whole mechanism for authenticating a run:
profiles that name an environment variable rather than carrying a token, so a
result bundle records `token_env: STAGING_TOKEN` and nothing anybody who finds
the bundle could replay.

No flag reached it. A tool for checking APIs that could only check
unauthenticated ones is most of a tool, and the two defects below had gone
unnoticed for exactly as long.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar

import httpx
import pytest

from apiverity.cli.main import main
from apiverity.traffic.auth import (
    AuthKind,
    AuthProfile,
    AuthProfileSet,
    material,
    resolve_client_cert,
)

_ROOT = Path(__file__).resolve().parents[2]
_FIXTURE = _ROOT / "fixtures" / "auth" / "profiles.yaml"
_SPEC = str(_ROOT / "fixtures" / "apis" / "crud" / "openapi.yaml")


# ------------------------------------------------------- the mTLS parameter


def test_the_client_certificate_is_what_httpx_calls_cert(tmp_path: Path) -> None:
    """It was returned as `verify=`, which is the *server* certificate setting.

    `resolve_verify` is gone; `resolve_client_cert` returns what `cert=` takes.
    """
    pem = tmp_path / "client.pem"
    pem.write_text("not a real certificate", encoding="utf-8")
    profile = AuthProfile(name="m", kind=AuthKind.mtls, cert_file=str(pem), key_file=str(pem))
    assert resolve_client_cert(profile) == (str(pem), str(pem))
    # httpx *loads* what `cert=` names, so a file that is not a certificate
    # fails here and now. That is the contrast: the same pair passed as
    # `verify=` is stored and never looked at -- see the next test.
    with pytest.raises(ssl.SSLError):
        httpx.Client(cert=resolve_client_cert(profile))


def test_httpx_accepts_a_tuple_for_verify_and_does_nothing_useful_with_it() -> None:
    """The evidence, kept as a test because it is the reason for the rename.

    httpx does not reject `verify=(cert, key)` at construction. It stores the
    tuple, so the SSL context *is* a tuple -- the client certificate is never
    presented and the failure arrives later, somewhere that says nothing about
    mTLS.
    """
    client = httpx.Client(verify=("a.pem", "b.pem"))
    assert isinstance(client._transport._pool._ssl_context, tuple)


def test_a_non_mtls_profile_has_no_client_certificate() -> None:
    assert resolve_client_cert(AuthProfile(name="b", kind=AuthKind.bearer)) is None


def test_an_mtls_profile_missing_a_file_reference_is_refused() -> None:
    with pytest.raises(ValueError, match="cert_file and key_file are required"):
        resolve_client_cert(AuthProfile(name="m", kind=AuthKind.mtls, cert_file="only.pem"))


# -------------------------------------------------------- the redaction


def test_every_field_is_a_reference_and_none_is_redacted() -> None:
    """`redacted_summary` blanked `password_env` and `key_file` while printing
    `token_env`, `key_env`, `username_env` and `cert_file`.

    Those are the same kind of thing: the name of an environment variable, or a
    path. Redacting the name of the variable holding a password while printing
    the name of the one holding a bearer token protects nothing, and costs the
    reader the one fact the summary exists to give them.
    """
    profile = AuthProfile(
        name="legacy",
        kind=AuthKind.basic,
        username_env="LEGACY_USER",
        password_env="LEGACY_PASSWORD",
    )
    summary = profile.redacted_summary()
    assert summary["password_env"] == "LEGACY_PASSWORD"
    assert "[REDACTED]" not in json.dumps(summary)


def test_the_summary_never_carries_a_resolved_value(monkeypatch: Any) -> None:
    """The property that matters: the *name* is in there and the value is not."""
    monkeypatch.setenv("A_TOKEN", "eyJhbGciOiJIUzI1NiJ9.secret")
    profile = AuthProfile(name="s", kind=AuthKind.bearer, token_env="A_TOKEN")
    rendered = json.dumps(profile.redacted_summary())
    assert "A_TOKEN" in rendered
    assert "eyJhbGciOiJIUzI1NiJ9.secret" not in rendered


def test_a_pasted_token_is_refused_at_load(tmp_path: Path) -> None:
    """The easy mistake this format exists to prevent: the field is a string
    and a token is a string, so a token fits."""
    path = tmp_path / "profiles.yaml"
    path.write_text(
        "profiles:\n  - name: oops\n    kind: bearer\n"
        "    token_env: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.aaaaaaaaaaaaaaaaaaaaaaaa\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="should name an environment variable and"):
        AuthProfileSet.load(str(path))


# ------------------------------------------------------------ the file


def test_the_bundled_fixture_declares_one_of_each_kind() -> None:
    profiles = AuthProfileSet.load(str(_FIXTURE))
    assert {p.kind.value for p in profiles.profiles} == {"bearer", "api_key", "basic", "mtls"}


def test_an_unknown_profile_names_the_ones_there_are() -> None:
    profiles = AuthProfileSet.load(str(_FIXTURE))
    with pytest.raises(KeyError, match="this file declares"):
        profiles.get("nope")


def test_two_profiles_with_one_name_are_refused(tmp_path: Path) -> None:
    path = tmp_path / "profiles.yaml"
    path.write_text(
        "profiles:\n"
        "  - {name: a, kind: bearer, token_env: T1}\n"
        "  - {name: a, kind: bearer, token_env: T2}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="two profiles are called"):
        AuthProfileSet.load(str(path))


def test_the_header_a_profile_resolves(monkeypatch: Any) -> None:
    monkeypatch.setenv("PARTNER_API_KEY", "pk-123")
    profiles = AuthProfileSet.load(str(_FIXTURE))
    headers, cert = material(profiles.get("partner-api"))
    assert headers == {"X-Partner-Key": "pk-123"}
    assert cert is None


# ----------------------------------------------------- through the command


class _Recorder(BaseHTTPRequestHandler):
    seen: ClassVar[list[dict[str, str]]] = []

    def log_message(self, *_args: Any) -> None:
        return

    def _answer(self) -> None:
        type(self).seen.append({k.lower(): v for k, v in self.headers.items()})
        body = json.dumps({"id": "1", "name": "alice"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _answer


@pytest.fixture
def recorder():
    _Recorder.seen = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Recorder)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", _Recorder
    finally:
        server.shutdown()
        server.server_close()


def _run(argv: list[str]) -> tuple[int, str, str]:
    """Like the console entry point, which turns `sys.exit` into an exit code."""
    out, err = io.StringIO(), io.StringIO()
    code = 0
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = main(argv)
        except SystemExit as stop:
            code = int(stop.code or 0)
    return code, out.getvalue(), err.getvalue()


def test_the_credential_reaches_the_server(recorder, monkeypatch: Any) -> None:
    """The point of the whole thing, checked at a socket rather than in a dict."""
    base_url, seen = recorder
    monkeypatch.setenv("STAGING_TOKEN", "tok-abcdefgh")
    _code, _out, _err = _run(
        [
            "--no-config",
            "drift",
            _SPEC,
            "--base-url",
            base_url,
            "--auth-profiles",
            str(_FIXTURE),
            "--auth-profile",
            "staging",
            "--json",
        ]
    )
    assert seen.seen, "nothing reached the server"
    assert all(h.get("authorization") == "Bearer tok-abcdefgh" for h in seen.seen)


def test_the_credential_never_reaches_the_artifact(recorder, monkeypatch: Any) -> None:
    """A bundle that carried the token would be a second copy of it, in a file
    people attach to pull requests."""
    base_url, _seen = recorder
    monkeypatch.setenv("STAGING_TOKEN", "tok-abcdefgh")
    _code, out, _err = _run(
        [
            "--no-config",
            "drift",
            _SPEC,
            "--base-url",
            base_url,
            "--auth-profiles",
            str(_FIXTURE),
            "--auth-profile",
            "staging",
            "--json",
        ]
    )
    assert "tok-abcdefgh" not in out


def test_a_header_flag_is_applied_on_top_of_the_profile(recorder, monkeypatch: Any) -> None:
    """Not instead of it: a profile carries the credential and a header carries
    the tenant id or the trace header somebody needs beside it. Making them
    exclusive would force a choice nobody wants to make."""
    base_url, seen = recorder
    monkeypatch.setenv("STAGING_TOKEN", "tok-abcdefgh")
    _run(
        [
            "--no-config",
            "drift",
            _SPEC,
            "--base-url",
            base_url,
            "--auth-profiles",
            str(_FIXTURE),
            "--auth-profile",
            "staging",
            "--header",
            "X-Tenant=acme",
            "--json",
        ]
    )
    assert seen.seen
    assert all(h.get("authorization") == "Bearer tok-abcdefgh" for h in seen.seen)
    assert all(h.get("x-tenant") == "acme" for h in seen.seen)


def test_every_command_that_sends_a_request_can_carry_an_extra_header() -> None:
    """`--header` was on two of the eight, so the merge in `auth_material` was
    dead for the other six."""
    import argparse

    from apiverity.cli.main import build_parser

    parser = build_parser()
    sub = next(
        action for action in parser._actions if isinstance(action, argparse._SubParsersAction)
    )
    for command in ("test", "workflow", "drift", "mcp-lock", "ghosts", "replay", "baseline"):
        flags = {o for a in sub.choices[command]._actions for o in a.option_strings}
        assert "--header" in flags, command


def test_naming_a_profile_without_a_file_is_a_usage_error() -> None:
    code, _out, err = _run(
        ["--no-config", "drift", _SPEC, "--base-url", "http://127.0.0.1:1", "--auth-profile", "x"]
    )
    assert code != 0
    assert "--auth-profile needs --auth-profiles" in err


def test_a_file_with_several_profiles_will_not_pick_one() -> None:
    """Guessing would authenticate as somebody the operator did not name."""
    code, _out, err = _run(
        [
            "--no-config",
            "drift",
            _SPEC,
            "--base-url",
            "http://127.0.0.1:1",
            "--auth-profiles",
            str(_FIXTURE),
            "--json",
        ]
    )
    assert code != 0
    assert "name one with --auth-profile" in err


def test_a_file_with_one_profile_needs_no_name(tmp_path: Path, recorder, monkeypatch: Any) -> None:
    base_url, seen = recorder
    monkeypatch.setenv("ONLY_TOKEN", "tok-only")
    path = tmp_path / "one.yaml"
    path.write_text(
        "profiles:\n  - {name: only, kind: bearer, token_env: ONLY_TOKEN}\n", encoding="utf-8"
    )
    _run(["--no-config", "drift", _SPEC, "--base-url", base_url, "--auth-profiles", str(path)])
    assert seen.seen
    assert all(h.get("authorization") == "Bearer tok-only" for h in seen.seen)


def test_an_unset_environment_variable_is_a_usage_error_not_an_empty_header() -> None:
    """An empty `Authorization: Bearer ` would be sent, answered with a 401,
    and reported as a service that rejects valid requests."""
    os.environ.pop("NOT_SET_ANYWHERE", None)
    code, _out, err = _run(
        [
            "--no-config",
            "drift",
            _SPEC,
            "--base-url",
            "http://127.0.0.1:1",
            "--auth-profiles",
            str(_FIXTURE),
            "--auth-profile",
            "staging",
        ]
    )
    assert code != 0 or "is not set" in err


@pytest.mark.parametrize(
    "command",
    ["test", "workflow", "drift", "mcp-lock", "ghosts", "replay", "baseline", "regression"],
)
def test_every_command_that_takes_a_base_url_takes_credentials(command: str) -> None:
    """A flag on six of eight commands is a flag somebody discovers is missing
    at the worst moment."""
    import argparse

    from apiverity.cli.main import build_parser

    parser = build_parser()
    sub = next(
        action for action in parser._actions if isinstance(action, argparse._SubParsersAction)
    )
    flags = {option for action in sub.choices[command]._actions for option in action.option_strings}
    assert {"--auth-profiles", "--auth-profile"} <= flags
