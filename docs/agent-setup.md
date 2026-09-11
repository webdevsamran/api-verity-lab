# Telling coding agents this tool exists

```bash
apiverity agent-setup            # what it would write
apiverity agent-setup --write    # write it
```

An agent that does not know `apiverity breaking` exists will write a migration
guide by comparing two YAML files by eye. The fix is a file in the repository
telling it otherwise.

## Four targets, one body of guidance

| Target | Path |
|---|---|
| `agents-md` | `AGENTS.md` |
| `claude-skill` | `.claude/skills/apiverity/SKILL.md` |
| `cursor-rule` | `.cursor/rules/apiverity.mdc` |
| `mcp-json` | `.mcp.json` |

`--target NAME` (repeatable) installs a subset.

These are **file formats this writes**, not assertions about which assistant
reads them. `AGENTS.md` is the cross-tool convention with the widest reach; the
rest are per-tool locations that move between versions. The run reports what it
wrote where, and nothing about what will read it.

## The guidance is generated

Every claim in the body comes from the code:

- the command list from the argument parser,
- the MCP tool list from `apiverity.mcp.tools.TOOLS`,
- the exit codes from the constants the commands return,
- the version, so a stale file is detectable.

A hand-written agent file is the worst kind of documentation drift, because the
reader is a machine. It will run `apiverity check`, get a usage error, and
invent a reason. `tests/unit/test_agent_setup.py` asserts the body against
those sources in both directions — every command listed, and no command named
that does not exist.

This repository's own `AGENTS.md` carries the generated block, and a test fails
if it falls behind the CLI. Same rule as every other generated document here.

## What it does to files it did not write

**Nothing, unless asked twice.** A bare run prints a plan and writes nothing —
the way `replay` and `notify` are dry by default. Installing into somebody's
editor configuration as a side effect of being run is not something a tool gets
to do.

**Only the marked block moves.** Re-running replaces what lies between
`<!-- generated:apiverity-agent-guide -->` and its closing marker and touches
nothing else.

**An existing `AGENTS.md` is added to, not owned.** It is a file a repository is
expected to already have, so a copy without the markers gains a section at the
end. A `cursor-rule` or `claude-skill` already at its path *without* the markers
is refused by name — a file at a single-purpose path is one somebody meant:

```
note: .cursor/rules/apiverity.mdc was not written: a rule file already lives
      here without this tool's markers
```

The run exits `1` and the other targets still install. `--force` overwrites.

**`.mcp.json` is merged, never replaced.** Other servers in it belong to other
integrations, and a rewrite that dropped them would break three to fix one. A
file that is not valid JSON is refused rather than replaced — the run does not
get to decide that somebody's unparseable config was worthless.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | planned, or written |
| `1` | at least one target was refused; the rest were written |
| `2` | an unknown `--target` |

## The MCP server

`mcp-json` registers `apiverity-mcp --root .`, which serves a read-only subset
of the CLI over MCP. Nothing in that subset writes a file, opens a socket or
runs another process — see [MCP exposure](mcp-exposure.md) for what is in it
and why the rest is not.
