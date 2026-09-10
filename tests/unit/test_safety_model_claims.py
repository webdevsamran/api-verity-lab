"""Every numbered control in `SAFETY_MODEL.md`, checked.

The page opens with "These controls are implemented in code and enforced by
default". Three of them were not.

`apiverity/traffic/safety.py` holds the host allowlist, the target
classification, the dry-run plan and the destructive-method gate --
controls 2, 4 and 5 -- and `apiverity replay` called none of them.
`check_replay_safety`, `build_dry_run_plan` and `confirmation_token` were
reached only by their own unit tests. `replay_corpus` had a weaker check of its
own, whose production branch keyed off a `production` flag on corpus entries
that **nothing in this project ever set**, so control 3 named a branch no
command could reach.

A safety page that overstates is worse than no page: it is the document
somebody reads before pointing this at a service they care about. So each
numbered control now has a test, and `test_every_numbered_control_has_a_test`
fails the build when a new one arrives without one.
"""

from __future__ import annotations

import contextlib
import io
import json
import re
from pathlib import Path
from typing import Any

import pytest

from apiverity.cli.main import build_parser, main
from apiverity.traffic.safety import (
    build_dry_run_plan,
    check_replay_safety,
    classify_target,
    confirmation_token,
)

_ROOT = Path(__file__).resolve().parents[2]
_DOC = _ROOT / "SAFETY_MODEL.md"
_NUMBERED = re.compile(r"^(\d+)\. ", re.MULTILINE)

#: Control number -> the test in this file that checks it. A control checked
#: somewhere else names that file instead; what matters is that the number is
#: accounted for.
CHECKED_BY: dict[int, str] = {
    1: "test_no_command_sends_traffic_without_a_target",
    2: "test_a_target_outside_the_allowlist_is_refused",
    3: "test_a_write_to_an_unclassifiable_or_production_target_needs_the_acknowledgement",
    4: "test_replay_is_a_dry_run_until_told_otherwise",
    5: "test_a_write_needs_its_method_named_and_the_token",
    6: "tests/unit/test_load_shapes.py -- a shape it cannot read is refused",
    7: "test_there_is_no_capture_proxy",
    8: "tests/integration/test_mcp_invoke.py -- reads by default",
    9: "tests/integration/test_mcp_invoke.py -- exact names, never globs",
    10: "tests/integration/test_mcp_invoke.py -- dry run, and --execute needs a target",
    11: "tests/integration/test_mcp_invoke.py -- annotations authorize nothing",
    12: "tests/integration/test_mcp_transport_conformance.py -- stdio unsupported",
    13: "tests/integration/test_core_pipeline.py -- redaction before persistence",
    14: "tests/unit/test_auth_profiles.py -- the credential never reaches the artifact",
    15: "tests/unit/test_rule_packs_run.py -- contracts scanned for secrets",
    16: "tests/unit/test_response_leakage.py -- the value is never recorded",
    17: "tests/integration/test_selfhosted_server.py -- hashed tokens, RBAC, isolation",
    18: "tests/integration/test_selfhosted_server.py -- rate limiting",
    19: "tests/integration/test_audit_export.py -- the hash chain",
    20: "tests/integration/test_store_concurrency.py -- backpressure and idempotency",
    21: "tests/integration/test_enterprise_ops.py -- backups exclude credential hashes",
    22: "tests/integration/test_authorization.py -- two identities, reads only for BFLA",
}


def _entries(*methods: str) -> list[Any]:
    from apiverity.traffic.replay import ReplayEntry

    return [ReplayEntry(method=m, path=f"/{m.lower()}") for m in methods]


def _run(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = 0
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = main(argv)
        except SystemExit as stop:
            code = int(stop.code or 0)
    return code, out.getvalue(), err.getvalue()


def _har(tmp_path: Path, *methods: str) -> str:
    path = tmp_path / "corpus.har"
    path.write_text(
        json.dumps(
            {
                "log": {
                    "entries": [
                        {
                            "request": {
                                "method": method,
                                "url": f"https://api.example.com/things/{index}",
                                "headers": [],
                                "queryString": [],
                            },
                            "response": {"status": 200, "content": {}},
                        }
                        for index, method in enumerate(methods)
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    return str(path)


# ------------------------------------------------------------ the controls


def test_no_command_sends_traffic_without_a_target() -> None:
    """Control 1. Every command that sends a request takes `--base-url`, and
    none of them defaults it to anything."""
    import argparse

    parser = build_parser()
    sub = next(
        action for action in parser._actions if isinstance(action, argparse._SubParsersAction)
    )
    for name in ("test", "workflow", "drift", "ghosts", "replay", "baseline", "regression"):
        base_url = next(
            action for action in sub.choices[name]._actions if "--base-url" in action.option_strings
        )
        assert base_url.default in (None, ""), name


def test_a_target_outside_the_allowlist_is_refused(tmp_path: Path) -> None:
    """Control 2, through the command rather than through the function."""
    code, _out, err = _run(
        [
            "--no-config",
            "replay",
            _har(tmp_path, "GET"),
            "--base-url",
            "https://api.example.com",
            "--allow-host",
            "https://somewhere.else",
            "--execute",
        ]
    )
    assert code != 0
    assert "not in the allowlist" in err


def test_a_write_to_an_unclassifiable_or_production_target_needs_the_acknowledgement(
    tmp_path: Path,
) -> None:
    """Control 3. The branch that used to key off a flag nothing ever set."""
    argv = [
        "--no-config",
        "replay",
        _har(tmp_path, "DELETE"),
        "--base-url",
        "https://api.example.com",
        "--allow-host",
        "https://api.example.com",
        "--allow-method",
        "DELETE",
        "--execute",
    ]
    code, _out, err = _run(argv)
    assert code != 0
    assert "classifies as production" in err
    assert "--i-know-this-is-production" in err


def test_a_read_only_corpus_needs_no_acknowledgement(tmp_path: Path) -> None:
    """The other half of control 3, and the reason the earlier gate was never
    adopted: it refused a GET-only replay against production."""
    decision = check_replay_safety(
        base_url="https://api.example.com",
        allowed_hosts=["https://api.example.com"],
        entries=_entries("GET", "HEAD"),
    )
    assert decision.approved


def test_replay_is_a_dry_run_until_told_otherwise(tmp_path: Path) -> None:
    """Control 4. It reports exactly what would be sent, and sends nothing."""
    code, out, _err = _run(
        [
            "--no-config",
            "replay",
            _har(tmp_path, "GET", "DELETE"),
            "--base-url",
            "https://api.example.com",
            "--allow-host",
            "https://api.example.com",
        ]
    )
    assert code == 0
    assert "dry run: 2 request(s) would be sent" in out
    assert "DELETE  https://api.example.com/things/1" in out
    assert "dry_run=True" in out and "sent=0" in out


def test_the_dry_run_prints_the_command_that_would_be_accepted(tmp_path: Path) -> None:
    """Telling somebody a command that will then be refused is worse than not
    telling them one, so the acknowledgement is in the printed line."""
    _code, out, _err = _run(
        [
            "--no-config",
            "replay",
            _har(tmp_path, "DELETE"),
            "--base-url",
            "https://api.example.com",
            "--allow-host",
            "https://api.example.com",
        ]
    )
    assert "--allow-method DELETE" in out
    assert "--confirm " in out
    assert "--i-know-this-is-production" in out


def test_a_write_needs_its_method_named_and_the_token(tmp_path: Path) -> None:
    """Control 5, in both halves."""
    entries = _entries("DELETE")
    without_method = check_replay_safety(
        base_url="http://localhost:9000",
        allowed_hosts=["http://localhost:9000"],
        entries=entries,
    )
    assert not without_method.approved
    assert "destructive allowlist" in without_method.reason

    without_token = check_replay_safety(
        base_url="http://localhost:9000",
        allowed_hosts=["http://localhost:9000"],
        entries=entries,
        destructive_allowlist={"DELETE"},
    )
    assert not without_token.approved
    assert "confirmation token" in without_token.reason


def test_the_token_is_bound_to_the_run_it_was_printed_for() -> None:
    """Otherwise it is a password, and a password gets pasted into a script."""
    a = confirmation_token("http://localhost:9000", {"DELETE"}, 4)
    assert a != confirmation_token("http://localhost:9001", {"DELETE"}, 4)
    assert a != confirmation_token("http://localhost:9000", {"POST"}, 4)
    assert a != confirmation_token("http://localhost:9000", {"DELETE"}, 5)


def test_there_is_no_capture_proxy() -> None:
    """Control 7. It described a "local capture mode" this project does not
    have, which is a reassurance about something absent."""
    package = _ROOT / "apiverity"
    proxies = [
        path
        for path in package.rglob("*.py")
        if "reverse proxy" in path.read_text(encoding="utf-8").lower()
    ]
    assert proxies == []
    assert "There is no capture proxy" in _DOC.read_text(encoding="utf-8")


def test_an_unclassifiable_host_is_treated_as_production() -> None:
    """A host this cannot classify is not one it should assume is safe."""
    assert classify_target("https://internal-7").classification == "unknown"
    decision = check_replay_safety(
        base_url="https://internal-7",
        allowed_hosts=["https://internal-7"],
        entries=_entries("POST"),
        destructive_allowlist={"POST"},
    )
    assert not decision.approved


def test_the_dry_run_plan_is_what_would_be_sent() -> None:
    plan = build_dry_run_plan(_entries("GET", "DELETE"), "https://api.example.com")
    assert [(p.method, p.url) for p in plan] == [
        ("GET", "https://api.example.com/get"),
        ("DELETE", "https://api.example.com/delete"),
    ]


# ------------------------------------------------------- the page itself


def test_every_numbered_control_has_a_test() -> None:
    """The guard. A control added to the page without one fails here, which is
    the only thing that keeps "implemented in code and enforced by default"
    from becoming a sentence somebody wrote once."""
    numbered = {int(n) for n in _NUMBERED.findall(_DOC.read_text(encoding="utf-8"))}
    assert numbered, "the page has no numbered controls; has it been restructured?"
    missing = sorted(numbered - set(CHECKED_BY))
    assert missing == [], (
        f"controls {missing} are published in SAFETY_MODEL.md and named in no test. "
        "Add one, and put its name in CHECKED_BY."
    )
    stale = sorted(set(CHECKED_BY) - numbered)
    assert stale == [], f"CHECKED_BY names controls {stale} that the page no longer has"
    # Contiguous from 1, so a control cannot be added by skipping a number.
    assert sorted(numbered) == list(range(1, max(numbered) + 1))
    # And not sub-numbered: `7b.` is not matched by the pattern above, so a
    # control added that way would slip past the whole guard. This was written
    # after doing exactly that.
    assert not re.search(r"^\d+[a-z]\. ", _DOC.read_text(encoding="utf-8"), re.MULTILINE)


@pytest.mark.parametrize("number", sorted(CHECKED_BY))
def test_each_named_test_exists(number: int) -> None:
    """`CHECKED_BY` is where an oversight would hide: a name that points at
    nothing silences the guard above."""
    target = CHECKED_BY[number]
    if target.startswith("tests/"):
        path, _, _note = target.partition(" -- ")
        assert (_ROOT / path).is_file(), f"control {number} names {path}, which is not there"
    else:
        assert target in globals(), f"control {number} names {target}, which is not in this file"


def test_the_page_says_what_it_does_not_claim() -> None:
    """The section that keeps the rest honest: these gates make accidents
    harder, not permission."""
    text = _DOC.read_text(encoding="utf-8")
    assert "## What we do not claim" in text
    assert "not permission" in text
