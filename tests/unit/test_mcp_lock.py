"""`mcp.lock`: a reviewed baseline for an MCP tool surface.

The subject is review, not detection. `drift` needs a manifest somebody
captured and kept; most teams have neither, their agent talks to a server they
do not control, and the first sign of a change is behaviour. A lockfile moves
the burden: any change to the surface fails CI until a human edits the file in
a pull request.

Two design decisions get most of the tests. The lock carries the whole surface
rather than only a hash, so `check` can say *which* tool changed and whether it
breaks a caller. And an added tool is graded ERROR here while the shared
catalogue grades it INFO -- the disagreement is deliberate and is the reason
the file exists.
"""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
from typing import Any

import pytest

from apiverity.cli.commands.common import EXIT_FINDINGS, EXIT_OK, EXIT_USAGE
from apiverity.cli.main import main
from apiverity.core.model import Severity
from apiverity.runtime.mcp_lock import (
    LOCK_VERSION,
    LockError,
    build_lock,
    compare,
    dumps_lock,
    load_lock,
    sign_body,
    surface_hash,
)

_ROOT = Path(__file__).resolve().parents[2]
_FIXTURES = _ROOT / "fixtures" / "mcp"
_KEY_ENV = "APIVERITY_TEST_LOCK_KEY"


def _tool(name: str, **extra: Any) -> dict[str, Any]:
    tool: dict[str, Any] = {
        "name": name,
        "description": "Find things.",
        "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}},
    }
    tool.update(extra)
    return tool


def _lock(*tools: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return build_lock(list(tools), source="t.json", tool_version="0.0.0", **kwargs)


def _ids(delta: Any) -> set[str]:
    return {f.rule_id for f in delta.findings}


def _run(argv: list[str]) -> tuple[int, dict[str, Any], str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    text = out.getvalue()
    return code, (json.loads(text) if text.strip().startswith("{") else {}), err.getvalue()


# ------------------------------------------------------------------ hashing


def test_the_surface_hash_ignores_the_order_tools_arrive_in() -> None:
    """The specification only SHOULDs a deterministic order.

    A baseline that changes because a server shuffled its list is a baseline
    that gets deleted in a week.
    """
    a, b = _tool("alpha"), _tool("beta")
    assert surface_hash([a, b]) == surface_hash([b, a])


def test_the_surface_hash_changes_when_a_schema_changes() -> None:
    before = surface_hash([_tool("alpha")])
    after = surface_hash(
        [_tool("alpha", inputSchema={"type": "object", "properties": {"q": {"type": "integer"}}})]
    )
    assert before != after


def test_volatile_metadata_is_not_part_of_the_baseline() -> None:
    """`_meta` carries per-connection state; a lock that churns is not read."""
    plain = surface_hash([_tool("alpha")])
    with_meta = surface_hash([_tool("alpha", _meta={"io.modelcontextprotocol/requestId": "abc"})])
    assert plain == with_meta


# -------------------------------------------------------------------- match


def test_an_unchanged_surface_reports_no_change() -> None:
    tools = [_tool("alpha"), _tool("beta")]
    delta = compare(_lock(*tools), tools)
    assert delta.changed is False
    assert delta.advice["required_bump"] == "none"


def test_a_reordered_capture_is_not_a_change() -> None:
    a, b = _tool("alpha"), _tool("beta")
    assert compare(_lock(a, b), [b, a]).changed is False


# ------------------------------------------------------------------- change


def test_a_removed_tool_is_reported_by_the_shared_catalogue_only_once() -> None:
    """`BRK-RPC-REMOVED` already says it, at ERROR. Saying it twice is noise."""
    delta = compare(_lock(_tool("alpha"), _tool("beta")), [_tool("alpha")])
    ids = _ids(delta)
    assert "BRK-RPC-REMOVED" in ids
    assert "MCP-LOCK-TOOL-REMOVED" not in ids
    assert delta.removed == ["beta"]


def test_an_added_tool_is_an_error_here_and_the_info_it_replaces_is_dropped() -> None:
    """The one place this command disagrees with the catalogue, on purpose.

    Adding a tool breaks nothing, so a version diff grades it INFO. Against a
    baseline it is a capability an agent can now reach that nobody reviewed.
    """
    delta = compare(_lock(_tool("alpha")), [_tool("alpha"), _tool("shadow_export")])
    by_id = {f.rule_id: f for f in delta.findings}
    assert by_id["MCP-LOCK-TOOL-ADDED"].severity is Severity.ERROR
    assert "BRK-RPC-ADDED" not in by_id


def test_a_changed_schema_carries_the_rule_that_classified_it() -> None:
    """Traceability: the same rule id an OpenAPI change would have produced."""
    tightened = _tool(
        "alpha",
        inputSchema={
            "type": "object",
            "required": ["query"],
            "properties": {"query": {"type": "string"}},
        },
    )
    delta = compare(_lock(_tool("alpha")), [tightened])
    assert "BRK-REQ-FIELD-BECAME-REQUIRED" in _ids(delta)
    assert delta.modified == ["alpha"]


def test_a_silent_description_edit_is_caught() -> None:
    """The rug-pull. Nothing about the schema moved."""
    delta = compare(_lock(_tool("alpha")), [_tool("alpha", description="Also emails support.")])
    assert delta.changed is True
    assert "BRK-MCP-TOOL-DESCRIPTION-CHANGED" in _ids(delta)


# ------------------------------------------------------------------- advice


def test_a_breaking_change_recommends_a_major_from_the_locked_version() -> None:
    delta = compare(_lock(_tool("alpha"), _tool("beta"), surface_version="2.3.1"), [_tool("alpha")])
    assert delta.advice["required_bump"] == "major"
    assert delta.advice["suggested_version"] == "3.0.0"
    assert any("BRK-RPC-REMOVED" in reason for reason in delta.advice["reasons"])


def test_the_version_lives_in_the_lock_because_the_protocol_has_nowhere_for_it() -> None:
    """An MCP tool carries no version field and SEP-1575 is dormant."""
    assert _lock(_tool("alpha"))["surface_version"] == "1.0.0"


def test_an_addition_is_an_error_finding_and_still_a_minor_bump() -> None:
    """Two questions, two answers, both right.

    The finding answers "should this have been reviewed". The advice answers
    "what does SemVer call it". A reader seeing both should not conclude one
    is a bug.
    """
    delta = compare(_lock(_tool("alpha")), [_tool("alpha"), _tool("beta")])
    assert "MCP-LOCK-TOOL-ADDED" in _ids(delta)
    assert delta.advice["required_bump"] == "minor"


# ---------------------------------------------------------------- signature


def test_an_unsigned_lock_says_so_without_failing() -> None:
    delta = compare(_lock(_tool("alpha")), [_tool("alpha")])
    assert delta.signature_state == "absent"
    assert "MCP-LOCK-UNSIGNED" in _ids(delta)


def test_signing_needs_a_key_that_actually_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    """A lock signed with an empty key verifies against an empty key."""
    monkeypatch.delenv(_KEY_ENV, raising=False)
    with pytest.raises(LockError, match="not set in the environment"):
        _lock(_tool("alpha"), key_env=_KEY_ENV)


def test_a_valid_signature_reports_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_KEY_ENV, "hunter2")
    body = _lock(_tool("alpha"), key_env=_KEY_ENV)
    delta = compare(body, [_tool("alpha")])
    assert delta.signature_state == "valid"
    assert not [f for f in delta.findings if f.rule_id.startswith("MCP-LOCK-SIGNATURE")]


def test_an_edited_lock_fails_its_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_KEY_ENV, "hunter2")
    body = _lock(_tool("alpha"), key_env=_KEY_ENV)
    body["surface_version"] = "9.9.9"
    delta = compare(body, [_tool("alpha")])
    by_id = {f.rule_id: f for f in delta.findings}
    assert by_id["MCP-LOCK-SIGNATURE-INVALID"].severity is Severity.ERROR


def test_a_signature_that_cannot_be_checked_is_not_a_passed_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(_KEY_ENV, "hunter2")
    body = _lock(_tool("alpha"), key_env=_KEY_ENV)
    monkeypatch.delenv(_KEY_ENV, raising=False)
    delta = compare(body, [_tool("alpha")])
    assert delta.signature_state == "unverified"
    assert "MCP-LOCK-SIGNATURE-UNVERIFIED" in _ids(delta)


def test_the_signature_covers_the_surface_not_only_the_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(_KEY_ENV, "hunter2")
    body = _lock(_tool("alpha"), key_env=_KEY_ENV)
    original = body["signature"]["value"]
    body["surface"]["tools"][0]["description"] = "Something else entirely."
    assert sign_body(body, "hunter2") != original


# ------------------------------------------------------------------ loading


def test_a_lock_from_a_future_format_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "mcp.lock"
    path.write_text(json.dumps({"lock_version": LOCK_VERSION + 1, "surface": {}}), encoding="utf-8")
    with pytest.raises(LockError, match="not supported"):
        load_lock(path)


def test_a_lock_without_a_surface_is_refused(tmp_path: Path) -> None:
    """It could be matched and never explained, which is the wrong trade."""
    path = tmp_path / "mcp.lock"
    path.write_text(json.dumps({"lock_version": LOCK_VERSION}), encoding="utf-8")
    with pytest.raises(LockError, match="cannot be compared"):
        load_lock(path)


def test_the_written_form_is_stable_and_sorted() -> None:
    """It is committed, reviewed and diffed by people."""
    text = dumps_lock(_lock(_tool("beta"), _tool("alpha")))
    assert text == dumps_lock(_lock(_tool("alpha"), _tool("beta")))
    assert text.endswith("\n")


# ---------------------------------------------------------------------- CLI


def test_write_then_check_round_trips(tmp_path: Path) -> None:
    lock = tmp_path / "mcp.lock"
    code, payload, _ = _run(
        ["mcp-lock", "write", str(_FIXTURES / "tools_v1.json"), "--lock", str(lock), "--json"]
    )
    assert code == EXIT_OK
    assert payload["tools_locked"] == 3

    code, payload, _ = _run(
        ["mcp-lock", "check", str(_FIXTURES / "tools_v1.json"), "--lock", str(lock), "--json"]
    )
    assert code == EXIT_OK
    assert payload["changed"] is False


def test_check_fails_when_the_surface_moved(tmp_path: Path) -> None:
    lock = tmp_path / "mcp.lock"
    _run(["mcp-lock", "write", str(_FIXTURES / "tools_v1.json"), "--lock", str(lock), "--json"])
    code, payload, _ = _run(
        ["mcp-lock", "check", str(_FIXTURES / "tools_v2.json"), "--lock", str(lock), "--json"]
    )
    assert code == EXIT_FINDINGS
    assert payload["advice"]["suggested_version"] == "2.0.0"


def test_write_refuses_to_overwrite_without_force(tmp_path: Path) -> None:
    """Rewriting a baseline is the thing the file exists to make visible."""
    lock = tmp_path / "mcp.lock"
    _run(["mcp-lock", "write", str(_FIXTURES / "tools_v1.json"), "--lock", str(lock), "--json"])
    code, _, err = _run(
        ["mcp-lock", "write", str(_FIXTURES / "tools_v1.json"), "--lock", str(lock), "--json"]
    )
    assert code == EXIT_USAGE
    assert "--force" in err


def test_exactly_one_source_is_required(tmp_path: Path) -> None:
    code, _, err = _run(["mcp-lock", "check", "--lock", str(tmp_path / "mcp.lock")])
    assert code == EXIT_USAGE
    assert "exactly one" in err


def test_a_document_that_is_not_a_manifest_is_refused(tmp_path: Path) -> None:
    code, _, err = _run(
        ["mcp-lock", "write", str(_FIXTURES / "server-config.json"), "--lock", str(tmp_path / "l")]
    )
    assert code == EXIT_USAGE
    assert "not an MCP tool manifest" in err


def test_the_artifact_names_the_contract_it_read(tmp_path: Path) -> None:
    """`mcp-lock` never goes through `_load`, so its provenance was blank."""
    _, payload, _ = _run(
        [
            "mcp-lock",
            "write",
            str(_FIXTURES / "tools_v1.json"),
            "--lock",
            str(tmp_path / "mcp.lock"),
            "--json",
        ]
    )
    assert payload["protocol_version"] == "mcp"
    assert payload["contract_hash"] != "0" * 64


def test_the_recorded_source_path_is_posix(tmp_path: Path) -> None:
    """The lock is committed and reviewed on every platform the team uses."""
    lock = tmp_path / "mcp.lock"
    _run(["mcp-lock", "write", str(_FIXTURES / "tools_v1.json"), "--lock", str(lock), "--json"])
    assert "\\" not in json.loads(lock.read_text(encoding="utf-8"))["source"]
