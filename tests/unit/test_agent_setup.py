"""The guidance an agent reads has to be derived, not typed.

A stale README costs a human a minute. A stale agent file costs an agent
nothing at all -- it will run `apiverity check`, get a usage error, and invent
a reason. So every claim in the rendered body comes from the code, and this
asserts that in both directions.

The other half is what the command does to files it did not write: nothing,
unless asked twice.
"""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
from typing import Any

import pytest

from apiverity.agents.skill import (
    MARK_CLOSE,
    MARK_OPEN,
    TARGETS,
    apply,
    guidance,
    plan,
)
from apiverity.cli.commands.common import EXIT_FINDINGS, EXIT_OK, EXIT_USAGE
from apiverity.cli.main import build_parser, main
from apiverity.mcp.tools import TOOLS


def _run(argv: list[str]) -> tuple[int, dict[str, Any], str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    text = out.getvalue()
    return code, (json.loads(text) if text.strip().startswith("{") else {}), err.getvalue()


# ------------------------------------------------------------ derived, not typed


def test_every_command_the_cli_defines_is_in_the_guidance() -> None:
    body = guidance()
    choices = build_parser()._subparsers._group_actions[0].choices
    missing = [name for name in choices if name not in body]
    assert not missing, f"{missing} exist and the agent guidance does not mention them"


def test_the_guidance_names_no_command_that_does_not_exist() -> None:
    """The direction that matters: an agent will run whatever it is told."""
    import re

    choices = set(build_parser()._subparsers._group_actions[0].choices)
    named = set(re.findall(r"`apiverity ([a-z][a-z-]*)", guidance()))
    invented = named - choices - {"<command>"}
    assert not invented, f"the guidance tells an agent to run {sorted(invented)}"


def test_every_mcp_tool_is_listed() -> None:
    body = guidance()
    for tool in TOOLS:
        assert f"`{tool.name}`" in body
        assert (tool.description or "").strip().rstrip(".") in body


def test_the_exit_codes_are_the_constants() -> None:
    from apiverity.cli.commands.common import (
        EXIT_INTERNAL,
        EXIT_UNREACHABLE,
    )

    body = guidance()
    for code in (EXIT_OK, EXIT_FINDINGS, EXIT_USAGE, EXIT_UNREACHABLE, EXIT_INTERNAL):
        assert f"| `{code}` |" in body


def test_the_guidance_carries_the_version_it_was_generated_from() -> None:
    """A file with no version in it is one nobody can tell is stale."""
    from apiverity import __version__

    assert f"apiverity {__version__}" in guidance()


def test_it_states_no_count_it_did_not_derive() -> None:
    """The project's own rule, applied to the file the project writes."""
    import re

    for number in re.findall(r"\b(\d+) (?:commands|rules|tools|checks)\b", guidance()):
        pytest.fail(f"the guidance hard-codes a count: {number}")


# --------------------------------------------------------------- what it writes


def test_a_dry_run_writes_nothing(tmp_path: Path) -> None:
    code, payload, _ = _run(["agent-setup", str(tmp_path), "--json"])
    assert code == EXIT_OK
    assert payload["wrote"] == []
    assert list(tmp_path.iterdir()) == []
    assert "pass --write" in payload["note"]


def test_write_installs_every_target(tmp_path: Path) -> None:
    code, payload, _ = _run(["agent-setup", str(tmp_path), "--write", "--json"])
    assert code == EXIT_OK
    for relative in TARGETS.values():
        assert (tmp_path / relative).is_file(), f"{relative} was not written"
    assert len(payload["wrote"]) == len(TARGETS)


def test_a_second_run_changes_nothing(tmp_path: Path) -> None:
    _run(["agent-setup", str(tmp_path), "--write"])
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    _, payload, _ = _run(["agent-setup", str(tmp_path), "--write", "--json"])
    assert payload["wrote"] == []
    assert {t["state"] for t in payload["targets"]} == {"unchanged"}
    assert {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before


def test_one_target_can_be_installed_alone(tmp_path: Path) -> None:
    _run(["agent-setup", str(tmp_path), "--target", "agents-md", "--write"])
    assert (tmp_path / "AGENTS.md").is_file()
    assert not (tmp_path / ".mcp.json").exists()


def test_an_unknown_target_is_a_usage_error(tmp_path: Path) -> None:
    code, _, err = _run(["agent-setup", str(tmp_path), "--target", "emacs"])
    assert code == EXIT_USAGE
    assert "unknown target" in err


# ------------------------------------------------- files somebody else wrote


def test_an_existing_agents_md_is_added_to_not_replaced(tmp_path: Path) -> None:
    """It is a file a repository is expected to have; this is a guest in it."""
    existing = "# AGENTS.md\n\n## House rules\n\nRun the tests before pushing.\n"
    (tmp_path / "AGENTS.md").write_text(existing, encoding="utf-8")
    _run(["agent-setup", str(tmp_path), "--target", "agents-md", "--write"])
    body = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert "Run the tests before pushing." in body
    assert MARK_OPEN in body and MARK_CLOSE in body


def test_only_the_marked_block_moves_on_an_upgrade(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text(
        f"# AGENTS.md\n\n## House rules\n\nkeep me\n\n{MARK_OPEN}\nstale\n{MARK_CLOSE}\n\n"
        "## Trailing section\n\nkeep me too\n",
        encoding="utf-8",
    )
    _run(["agent-setup", str(tmp_path), "--target", "agents-md", "--write"])
    body = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert "stale" not in body
    assert "keep me" in body and "keep me too" in body
    assert body.count(MARK_OPEN) == 1


def test_a_cursor_rule_somebody_else_wrote_is_refused_by_name(tmp_path: Path) -> None:
    target = tmp_path / TARGETS["cursor-rule"]
    target.parent.mkdir(parents=True)
    target.write_text("---\ndescription: mine\n---\n\nhand written\n", encoding="utf-8")

    code, payload, err = _run(
        ["agent-setup", str(tmp_path), "--target", "cursor-rule", "--write", "--json"]
    )
    assert code == EXIT_FINDINGS
    assert target.read_text(encoding="utf-8") == "---\ndescription: mine\n---\n\nhand written\n"
    assert payload["blocked"][0]["target"] == "cursor-rule"
    assert "was not written" in err


def test_force_overwrites_it(tmp_path: Path) -> None:
    target = tmp_path / TARGETS["cursor-rule"]
    target.parent.mkdir(parents=True)
    target.write_text("hand written\n", encoding="utf-8")
    code, _, _ = _run(
        ["agent-setup", str(tmp_path), "--target", "cursor-rule", "--write", "--force"]
    )
    assert code == EXIT_OK
    assert MARK_OPEN in target.read_text(encoding="utf-8")


def test_a_claude_skill_at_that_path_is_refused(tmp_path: Path) -> None:
    target = tmp_path / TARGETS["claude-skill"]
    target.parent.mkdir(parents=True)
    target.write_text("---\nname: something-else\n---\n\nnot ours\n", encoding="utf-8")
    code, _, _ = _run(["agent-setup", str(tmp_path), "--target", "claude-skill", "--write"])
    assert code == EXIT_FINDINGS
    assert "not ours" in target.read_text(encoding="utf-8")


# ------------------------------------------------------------------- .mcp.json


def test_other_mcp_servers_survive_the_merge(tmp_path: Path) -> None:
    """A rewrite that dropped them would break three integrations to fix one."""
    (tmp_path / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"other": {"command": "x"}}, "unrelated": 1}),
        encoding="utf-8",
    )
    _run(["agent-setup", str(tmp_path), "--target", "mcp-json", "--write"])
    document = json.loads((tmp_path / ".mcp.json").read_text(encoding="utf-8"))
    assert document["mcpServers"]["other"] == {"command": "x"}
    assert document["mcpServers"]["apiverity"]["command"] == "apiverity-mcp"
    assert document["unrelated"] == 1


def test_an_unparseable_mcp_json_is_refused_rather_than_replaced(tmp_path: Path) -> None:
    (tmp_path / ".mcp.json").write_text("{not json", encoding="utf-8")
    code, payload, _ = _run(
        ["agent-setup", str(tmp_path), "--target", "mcp-json", "--write", "--json"]
    )
    assert code == EXIT_FINDINGS
    assert (tmp_path / ".mcp.json").read_text(encoding="utf-8") == "{not json"
    assert "not valid JSON" in payload["blocked"][0]["reason"]


def test_an_mcp_servers_key_that_is_not_an_object_is_refused(tmp_path: Path) -> None:
    (tmp_path / ".mcp.json").write_text(json.dumps({"mcpServers": []}), encoding="utf-8")
    code, _, _ = _run(["agent-setup", str(tmp_path), "--target", "mcp-json", "--write"])
    assert code == EXIT_FINDINGS


# ------------------------------------------------ this repository's own copy


def test_this_repositorys_agents_md_is_not_stale() -> None:
    """The project eats it: the same rule it applies to every generated document.

    `AGENTS.md` here carries the generated block, and a command added without
    re-running `apiverity agent-setup --write` leaves the agents working in
    this repository reading a list that no longer matches the CLI.
    """
    root = Path(__file__).resolve().parents[2]
    body = (root / "AGENTS.md").read_text(encoding="utf-8")
    assert MARK_OPEN in body, (
        "AGENTS.md has lost the generated markers; run "
        "`apiverity agent-setup --target agents-md --write`"
    )
    block = body[body.index(MARK_OPEN) + len(MARK_OPEN) : body.index(MARK_CLOSE)]
    assert block.strip() == guidance().strip(), (
        "AGENTS.md no longer matches what the code renders. Run "
        "`apiverity agent-setup --target agents-md --write`"
    )


# --------------------------------------------------------------- the plan API


def test_the_plan_reports_what_each_target_would_become(tmp_path: Path) -> None:
    setup = plan(tmp_path)
    assert {p.as_dict()["state"] for p in setup.plans} == {"create"}
    apply(setup)
    assert {p.as_dict()["state"] for p in plan(tmp_path).plans} == {"unchanged"}


def test_an_unknown_target_raises_rather_than_installing_the_rest(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown target"):
        plan(tmp_path, ["agents-md", "emacs"])
    assert list(tmp_path.iterdir()) == []
