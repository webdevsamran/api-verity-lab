"""Register this tool with the coding agents working in a repository.

An agent that does not know `apiverity breaking` exists will write a migration
guide by reading two YAML files by eye. The fix is a file in the repository
telling it otherwise -- `AGENTS.md`, a Claude Code skill, a Cursor rule, an
`.mcp.json` entry. Four formats, one body of guidance.

## The guidance is generated, not typed

Every claim in the rendered body comes from the code: the command list from the
argument parser, the tool list from :data:`apiverity.mcp.tools.TOOLS`, the exit
codes from the constants the commands return. A hand-written agent file is the
worst kind of documentation drift, because the reader is a machine that will
act on it without noticing that `apiverity check` has not existed for a year.

`tests/unit/test_agent_skill.py` asserts the rendered body against the same
sources, in both directions.

## What it does to files it did not write

Nothing, unless asked twice.

* **Dry by default.** A bare run prints what it would write and writes nothing,
  the way `replay` and `notify` are dry by default. Installing into somebody's
  editor configuration as a side effect of being run is not something a tool
  gets to do.
* **A marked block, and only that block.** Re-running replaces what is between
  the markers and touches nothing else. An `AGENTS.md` that has no markers yet
  gains a section at the end -- a file a repository is expected to already have
  is one to add to, not to own. A Cursor rule or Claude skill already at that
  path *without* the markers is refused by name, because a file at a
  single-purpose path is one somebody meant.
* **`.mcp.json` is merged, never replaced.** Other servers in it are somebody
  else's, and a rewrite that dropped them would break three integrations to
  fix one.

## What it will not claim

Only four targets, and each is a file format this writes -- not an assertion
about which assistant reads it. `AGENTS.md` is the cross-tool convention and
the widest reach; the rest are per-tool locations that move between versions.
The report says what was written where, and nothing about what will read it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MARK_OPEN = "<!-- generated:apiverity-agent-guide -->"
MARK_CLOSE = "<!-- /generated:apiverity-agent-guide -->"

#: Target -> the path it writes, relative to the repository root.
TARGETS: dict[str, str] = {
    "agents-md": "AGENTS.md",
    "claude-skill": ".claude/skills/apiverity/SKILL.md",
    "cursor-rule": ".cursor/rules/apiverity.mdc",
    "mcp-json": ".mcp.json",
}


def _commands() -> list[str]:
    """Every subcommand the parser defines, from the parser."""
    from apiverity.cli.main import build_parser

    parser = build_parser()
    action = parser._subparsers._group_actions[0]  # type: ignore[union-attr]
    return sorted(str(name) for name in (action.choices or {}))


def _mcp_tools() -> list[tuple[str, str]]:
    from apiverity.mcp.tools import TOOLS

    return [(tool.name, (tool.description or "").strip()) for tool in TOOLS]


def _exit_codes() -> list[tuple[int, str]]:
    """The exit contract, as the commands actually use it.

    Named here rather than imported as a mapping because no such mapping
    exists: the constants are five integers and their meaning lives in
    `docs/exit-codes.md`. A test asserts the values against the constants, so
    the numbers cannot drift even though the sentences are written here.
    """
    from apiverity.cli.commands.common import (
        EXIT_FINDINGS,
        EXIT_INTERNAL,
        EXIT_OK,
        EXIT_UNREACHABLE,
        EXIT_USAGE,
    )

    return [
        (EXIT_OK, "nothing to report"),
        (EXIT_FINDINGS, "findings at or above the gate threshold -- the normal failure"),
        (EXIT_USAGE, "the command line or an input file was wrong"),
        (EXIT_UNREACHABLE, "a target could not be reached, so the run established nothing"),
        (EXIT_INTERNAL, "an unexpected error; this one is a bug report"),
    ]


def guidance() -> str:
    """The body every target carries, rendered from the code."""
    from apiverity import __version__

    commands = _commands()
    tools = _mcp_tools()

    lines = [
        "## apiverity — API contract governance",
        "",
        "`apiverity` compiles OpenAPI, Swagger, AsyncAPI, GraphQL, gRPC and MCP tool",
        "manifests into one contract model and runs every engine against that model.",
        "Prefer it over reading two spec files by eye: the questions below have exact",
        "answers, and an eyeball comparison of two YAML documents does not.",
        "",
        "### Use it for",
        "",
        "| Question | Command |",
        "|---|---|",
        "| Is this change breaking? | `apiverity breaking old.yaml new.yaml` |",
        "| What changed? | `apiverity diff old.yaml new.yaml` |",
        "| What version should this be? | `apiverity breaking old.yaml new.yaml --suggest-version` |",
        "| Why does this rule exist? | `apiverity explain BRK-RESP-FIELD-REMOVED` |",
        "| Does the running service match its contract? | `apiverity drift api.yaml --base-url URL` |",
        "| Whose build breaks? | `apiverity breaking ... --consumers consumers.yaml` |",
        "| Which contracts in this repo are failing? | `apiverity sweep .` |",
        "",
        "Add `--json` to any of them for a machine-readable result artifact",
        "(`schemas/result-v1.schema.json`), which is the form to parse rather than",
        "scraping the text output.",
        "",
        "### Exit codes",
        "",
        "| Code | Meaning |",
        "|---|---|",
    ]
    lines += [f"| `{code}` | {meaning} |" for code, meaning in _exit_codes()]
    lines += [
        "",
        "Exit `1` is a *result*, not a crash -- it is how a gate reports findings.",
        "Do not treat it as a tool failure.",
        "",
        "### Every command",
        "",
        "```",
        ", ".join(commands),
        "```",
        "",
        "`apiverity <command> --help` for any of them.",
        "",
        "### As an MCP server",
        "",
        "`apiverity-mcp --root .` exposes a read-only subset over MCP:",
        "",
    ]
    lines += [f"- `{name}` — {description}" for name, description in tools]
    lines += [
        "",
        "Read-only on purpose: nothing in that subset writes a file, opens a socket or",
        "runs another process.",
        "",
        "### What not to do",
        "",
        "- Do not hand-edit a generated document. `docs/rule-catalog.md`,",
        "  `docs/check-rules.md` and the rest are produced by `scripts/generate_*.py`",
        "  and CI fails when a committed copy disagrees with the code.",
        "- Do not state a count in prose without deriving it. This project binds every",
        "  such number to a test.",
        "- Do not report that a check passed when it did not run. A target that could",
        "  not be reached establishes nothing, and the tool distinguishes the two.",
        "",
        f"Generated by apiverity {__version__}. Re-run `apiverity agent-setup --write`",
        "after upgrading.",
    ]
    return "\n".join(lines) + "\n"


@dataclass
class Plan:
    """What a run would write, or did."""

    path: Path
    target: str
    #: The complete file content this run produces.
    content: str
    #: What the file is now, when it exists.
    existing: str | None = None
    #: Set when the file cannot be written without `--force`, with the reason.
    blocked: str | None = None

    @property
    def unchanged(self) -> bool:
        return self.existing == self.content

    def as_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "path": str(self.path),
            "state": (
                "blocked"
                if self.blocked
                else "unchanged"
                if self.unchanged
                else "update"
                if self.existing is not None
                else "create"
            ),
            **({"reason": self.blocked} if self.blocked else {}),
            "bytes": len(self.content.encode("utf-8")),
        }


def _splice(existing: str, body: str) -> str | None:
    """Replace the marked block, or None when the markers are not both there."""
    start = existing.find(MARK_OPEN)
    end = existing.find(MARK_CLOSE)
    if start == -1 or end == -1 or end < start:
        return None
    head = existing[: start + len(MARK_OPEN)]
    return f"{head}\n{body}{existing[end:]}"


def _marked(body: str) -> str:
    return f"{MARK_OPEN}\n{body}{MARK_CLOSE}\n"


def _agents_md(path: Path, body: str) -> Plan:
    plan = Plan(path=path, target="agents-md", content="")
    if path.exists():
        plan.existing = path.read_text(encoding="utf-8")
        spliced = _splice(plan.existing, body)
        if spliced is None:
            # Appended rather than refused: AGENTS.md is a file a repository
            # is expected to already have, and adding a marked section to the
            # end of it touches nothing somebody wrote.
            separator = "" if plan.existing.endswith("\n\n") else "\n"
            plan.content = f"{plan.existing.rstrip()}\n\n{_marked(body)}"
            del separator
        else:
            plan.content = spliced
    else:
        plan.content = f"# AGENTS.md\n\n{_marked(body)}"
    return plan


def _claude_skill(path: Path, body: str) -> Plan:
    front = (
        "---\n"
        "name: apiverity\n"
        "description: >-\n"
        "  Governing API contracts in this repository: whether a change is breaking,\n"
        "  what version it should be, whether the running service still matches, and\n"
        "  whose build breaks. Use before hand-comparing two spec files.\n"
        "---\n\n"
    )
    plan = Plan(path=path, target="claude-skill", content=front + body)
    if path.exists():
        plan.existing = path.read_text(encoding="utf-8")
        if MARK_OPEN not in plan.existing and "name: apiverity" not in plan.existing:
            plan.blocked = "a different skill already lives here; this run will not overwrite it"
    return plan


def _cursor_rule(path: Path, body: str) -> Plan:
    front = (
        "---\n"
        "description: apiverity — API contract governance commands for this repository\n"
        "alwaysApply: false\n"
        "---\n\n"
    )
    plan = Plan(path=path, target="cursor-rule", content=front + _marked(body))
    if path.exists():
        plan.existing = path.read_text(encoding="utf-8")
        if MARK_OPEN not in plan.existing:
            plan.blocked = "a rule file already lives here without this tool's markers"
    return plan


def _mcp_json(path: Path) -> Plan:
    entry = {"command": "apiverity-mcp", "args": ["--root", "."]}
    plan = Plan(path=path, target="mcp-json", content="")
    document: dict[str, Any] = {}
    if path.exists():
        plan.existing = path.read_text(encoding="utf-8")
        try:
            loaded = json.loads(plan.existing)
        except ValueError as exc:
            plan.blocked = f"the existing file is not valid JSON ({exc}); nothing was merged"
            plan.content = plan.existing
            return plan
        if not isinstance(loaded, dict):
            plan.blocked = "the existing file is not a JSON object"
            plan.content = plan.existing
            return plan
        document = loaded
    servers = document.get("mcpServers")
    if servers is not None and not isinstance(servers, dict):
        plan.blocked = "`mcpServers` in the existing file is not an object"
        plan.content = plan.existing or ""
        return plan
    # Merged, never replaced: the other entries are somebody else's integrations.
    merged = dict(servers or {})
    merged["apiverity"] = entry
    document["mcpServers"] = merged
    plan.content = json.dumps(document, indent=2, sort_keys=True) + "\n"
    return plan


@dataclass
class Setup:
    root: Path
    plans: list[Plan] = field(default_factory=list)

    def as_dict(self, *, written: bool) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "written": written,
            "targets": [plan.as_dict() for plan in self.plans],
            # Named, so a run that refused something does not look like a run
            # that had nothing to do.
            "blocked": [
                {"target": p.target, "path": str(p.path), "reason": p.blocked}
                for p in self.plans
                if p.blocked
            ],
        }


def plan(root: str | Path, targets: list[str] | None = None) -> Setup:
    """What installing into `root` would write."""
    base = Path(root)
    chosen = list(targets or TARGETS)
    unknown = [name for name in chosen if name not in TARGETS]
    if unknown:
        raise ValueError(f"unknown target(s): {sorted(unknown)}. Known: {sorted(TARGETS)}")

    body = guidance()
    setup = Setup(root=base)
    for name in chosen:
        path = base / TARGETS[name]
        if name == "agents-md":
            setup.plans.append(_agents_md(path, body))
        elif name == "claude-skill":
            setup.plans.append(_claude_skill(path, body))
        elif name == "cursor-rule":
            setup.plans.append(_cursor_rule(path, body))
        else:
            setup.plans.append(_mcp_json(path))
    return setup


def apply(setup: Setup, *, force: bool = False) -> list[Plan]:
    """Write the plans that are not blocked. Returns what was written."""
    written: list[Plan] = []
    for item in setup.plans:
        if item.blocked and not force:
            continue
        if item.unchanged:
            continue
        item.path.parent.mkdir(parents=True, exist_ok=True)
        item.path.write_text(item.content, encoding="utf-8", newline="\n")
        written.append(item)
    return written


__all__ = [
    "MARK_CLOSE",
    "MARK_OPEN",
    "TARGETS",
    "Plan",
    "Setup",
    "apply",
    "guidance",
    "plan",
]
