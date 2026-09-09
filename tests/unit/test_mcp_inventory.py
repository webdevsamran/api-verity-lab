"""Shadow MCP servers, found by reading configuration rather than scanning.

OWASP MCP09 is an agent reaching a server nobody approved. The obvious
implementation is a port sweep and it is wrong twice: `SAFETY_MODEL.md` §1 is
"explicit targets only", and a scan cannot see the case that actually happens,
which is a developer adding a server to their own editor's config.

Most of these tests are about what the report is forced to admit. A count of
zero servers is the number a reader is most likely to misread, so the report
has to say which locations it read and which it did not.
"""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
from typing import Any

from apiverity.cli.commands.common import EXIT_FINDINGS, EXIT_OK
from apiverity.cli.main import main
from apiverity.runtime.mcp_inventory import coverage_note, take_inventory


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _ids(report: Any) -> set[str]:
    return {f.rule_id for f in report.findings}


def _run(argv: list[str]) -> tuple[int, dict[str, Any]]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        code = main(argv)
    text = out.getvalue()
    return code, (json.loads(text) if text.strip().startswith("{") else {})


# --------------------------------------------------------------- reading


def test_servers_are_read_from_a_project_config(tmp_path: Path) -> None:
    _write(tmp_path / ".mcp.json", {"mcpServers": {"orders": {"url": "https://x/mcp"}}})
    report = take_inventory(tmp_path)
    assert [s.name for s in report.servers] == ["orders"]
    assert report.servers[0].transport == "http"
    assert report.servers[0].client == "Claude Code"


def test_the_other_config_shape_is_read_too(tmp_path: Path) -> None:
    """`servers` and `mcpServers` are both in use across clients."""
    _write(tmp_path / ".vscode" / "mcp.json", {"servers": {"docs": {"command": "docs-mcp"}}})
    assert [s.name for s in take_inventory(tmp_path).servers] == ["docs"]


def test_home_configs_are_not_read_without_being_asked(tmp_path: Path) -> None:
    """A CI run is entitled to the checkout, not to somebody's home directory."""
    home = tmp_path / "home"
    _write(home / ".cursor" / "mcp.json", {"mcpServers": {"secret": {"command": "x"}}})
    project = tmp_path / "project"
    project.mkdir()

    assert take_inventory(project, home=home).servers == []
    included = take_inventory(project, home=home, include_home=True)
    assert [s.name for s in included.servers] == ["secret"]


def test_a_named_config_is_read_wherever_it_is(tmp_path: Path) -> None:
    elsewhere = tmp_path / "odd" / "place.json"
    _write(elsewhere, {"mcpServers": {"weird": {"command": "x"}}})
    report = take_inventory(tmp_path / "project", extra_configs=[str(elsewhere)])
    assert [s.name for s in report.servers] == ["weird"]


def test_a_platform_specific_path_is_skipped_on_other_platforms(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write(
        home / "Library/Application Support/Claude/claude_desktop_config.json",
        {"mcpServers": {"mac_only": {"command": "x"}}},
    )
    on_windows = take_inventory(tmp_path, home=home, include_home=True, platform="win32")
    assert [s.name for s in on_windows.servers] == []
    on_mac = take_inventory(tmp_path, home=home, include_home=True, platform="darwin")
    assert [s.name for s in on_mac.servers] == ["mac_only"]


# ------------------------------------------------------- what it admits to


def test_every_path_considered_is_reported_present_or_not(tmp_path: Path) -> None:
    report = take_inventory(tmp_path)
    assert len(report.paths_examined) == 3
    assert {entry["status"] for entry in report.paths_examined} == {"absent"}


def test_a_count_of_zero_comes_with_the_sentence_that_qualifies_it(tmp_path: Path) -> None:
    note = coverage_note(take_inventory(tmp_path))
    assert "0 server(s) across 0 of 3" in note
    assert "keeps its configuration elsewhere was not read" in note


def test_every_known_location_records_where_it_came_from(tmp_path: Path) -> None:
    """A documented path and a guessed one are different claims."""
    report = take_inventory(tmp_path)
    assert all(entry["source"] for entry in report.paths_examined)


def test_a_config_that_cannot_be_parsed_is_reported_not_skipped(tmp_path: Path) -> None:
    """Silently skipping it would report fewer servers than exist."""
    (tmp_path / ".mcp.json").write_text("{ not json", encoding="utf-8")
    report = take_inventory(tmp_path)
    assert "MCP-INVENTORY-CONFIG-UNREADABLE" in _ids(report)
    assert "does not cover them" in report.findings[0].message


# ----------------------------------------------------------------- shadow


def test_a_configured_server_absent_from_the_inventory_is_an_error(tmp_path: Path) -> None:
    _write(
        tmp_path / ".mcp.json",
        {"mcpServers": {"orders": {"url": "https://x/mcp"}, "rogue": {"command": "x"}}},
    )
    (tmp_path / "inv.yaml").write_text("version: 1\nservers:\n  - name: orders\n", encoding="utf-8")
    report = take_inventory(tmp_path, approved_path=str(tmp_path / "inv.yaml"))
    shadow = [f for f in report.findings if f.rule_id == "MCP-SHADOW-SERVER"]
    assert [f.server for f in shadow] == ["rogue"]
    assert shadow[0].severity == "ERROR"


def test_an_approved_server_nobody_configured_is_only_a_note(tmp_path: Path) -> None:
    (tmp_path / "inv.yaml").write_text("version: 1\nservers:\n  - name: ghost\n", encoding="utf-8")
    report = take_inventory(tmp_path, approved_path=str(tmp_path / "inv.yaml"))
    note = next(f for f in report.findings if f.rule_id == "MCP-INVENTORY-UNCONFIGURED")
    assert note.severity == "INFO"
    assert "somewhere this build does not know about" in note.message


def test_no_inventory_means_no_shadow_findings(tmp_path: Path) -> None:
    """Without an approved list there is nothing to be unapproved against."""
    _write(tmp_path / ".mcp.json", {"mcpServers": {"anything": {"command": "x"}}})
    assert "MCP-SHADOW-SERVER" not in _ids(take_inventory(tmp_path))


def test_a_plain_string_inventory_entry_works(tmp_path: Path) -> None:
    _write(tmp_path / ".mcp.json", {"mcpServers": {"orders": {"command": "x"}}})
    (tmp_path / "inv.yaml").write_text("version: 1\nservers: [orders]\n", encoding="utf-8")
    assert "MCP-SHADOW-SERVER" not in _ids(
        take_inventory(tmp_path, approved_path=str(tmp_path / "inv.yaml"))
    )


def test_an_unreadable_inventory_is_an_error_not_an_empty_list(tmp_path: Path) -> None:
    """An empty approved list would make every configured server a shadow."""
    (tmp_path / "inv.yaml").write_text("just a string", encoding="utf-8")
    report = take_inventory(tmp_path, approved_path=str(tmp_path / "inv.yaml"))
    assert "MCP-INVENTORY-UNREADABLE" in _ids(report)


# --------------------------------------------------------------- hygiene


def test_a_server_fetched_at_launch_is_a_dependency_with_no_lockfile(tmp_path: Path) -> None:
    _write(
        tmp_path / ".mcp.json",
        {"mcpServers": {"fs": {"command": "npx", "args": ["-y", "@scope/server-fs"]}}},
    )
    finding = next(
        f for f in take_inventory(tmp_path).findings if f.rule_id == "MCP-SHADOW-FETCHED-AT-LAUNCH"
    )
    assert "@scope/server-fs" in finding.message


def test_a_pinned_local_binary_is_not_flagged(tmp_path: Path) -> None:
    _write(tmp_path / ".mcp.json", {"mcpServers": {"fs": {"command": "/opt/bin/fs-mcp"}}})
    assert "MCP-SHADOW-FETCHED-AT-LAUNCH" not in _ids(take_inventory(tmp_path))


def test_plaintext_to_a_remote_host_is_reported(tmp_path: Path) -> None:
    _write(tmp_path / ".mcp.json", {"mcpServers": {"a": {"url": "http://mcp.example.com/mcp"}}})
    assert "MCP-SHADOW-PLAINTEXT-URL" in _ids(take_inventory(tmp_path))


def test_plaintext_to_localhost_is_not(tmp_path: Path) -> None:
    _write(tmp_path / ".mcp.json", {"mcpServers": {"a": {"url": "http://127.0.0.1:3000/mcp"}}})
    assert "MCP-SHADOW-PLAINTEXT-URL" not in _ids(take_inventory(tmp_path))


def test_a_literal_credential_in_a_client_config_is_an_error(tmp_path: Path) -> None:
    _write(
        tmp_path / ".mcp.json",
        {"mcpServers": {"b": {"command": "x", "env": {"API_TOKEN": "abcd1234efgh5678"}}}},
    )
    finding = next(
        f for f in take_inventory(tmp_path).findings if f.rule_id == "MCP-SHADOW-INLINE-CREDENTIAL"
    )
    assert finding.severity == "ERROR"
    assert "API_TOKEN" in finding.message


def test_the_credential_finding_never_quotes_the_credential(tmp_path: Path) -> None:
    """Reporting a leak by repeating it into an artifact is not a fix."""
    _write(
        tmp_path / ".mcp.json",
        {"mcpServers": {"b": {"command": "x", "env": {"API_TOKEN": "abcd1234efgh5678"}}}},
    )
    report = take_inventory(tmp_path)
    assert "abcd1234efgh5678" not in report.model_dump_json()


def test_an_environment_reference_is_not_a_literal(tmp_path: Path) -> None:
    _write(
        tmp_path / ".mcp.json",
        {"mcpServers": {"b": {"command": "x", "env": {"API_TOKEN": "${REAL_TOKEN}"}}}},
    )
    assert "MCP-SHADOW-INLINE-CREDENTIAL" not in _ids(take_inventory(tmp_path))


def test_a_non_secret_env_key_is_left_alone(tmp_path: Path) -> None:
    _write(
        tmp_path / ".mcp.json",
        {"mcpServers": {"b": {"command": "x", "env": {"LOG_LEVEL": "debug"}}}},
    )
    assert "MCP-SHADOW-INLINE-CREDENTIAL" not in _ids(take_inventory(tmp_path))


# -------------------------------------------------------------------- CLI


def test_the_command_exits_zero_on_a_clean_project(tmp_path: Path) -> None:
    code, payload = _run(["mcp-inventory", str(tmp_path), "--json"])
    assert code == EXIT_OK
    assert payload["servers"] == []
    assert "of 3 known configuration locations" in payload["coverage"]


def test_the_command_fails_on_a_shadow_server(tmp_path: Path) -> None:
    _write(tmp_path / ".mcp.json", {"mcpServers": {"rogue": {"command": "x"}}})
    (tmp_path / "inv.yaml").write_text("version: 1\nservers: []\n", encoding="utf-8")
    code, payload = _run(
        ["mcp-inventory", str(tmp_path), "--inventory", str(tmp_path / "inv.yaml"), "--json"]
    )
    assert code == EXIT_FINDINGS
    assert {f["rule_id"] for f in payload["findings"]} == {"MCP-SHADOW-SERVER"}


def test_the_text_output_does_not_render_servers_as_blank_lines(tmp_path: Path) -> None:
    """It did. Three configured servers printed as three empty rows."""
    _write(tmp_path / ".mcp.json", {"mcpServers": {"orders": {"url": "https://x/mcp"}}})
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        main(["mcp-inventory", str(tmp_path)])
    body = out.getvalue()
    assert "name=orders" in body
