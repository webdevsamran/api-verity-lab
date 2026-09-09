# api-verity-lab as an MCP server

**Shipped, as the deliberately small read-only subset this document specified.**

```bash
apiverity-mcp --root .
```

Newline-delimited JSON-RPC over stdio. Seven tools, every one a pure function
of files beneath `--root`; nothing contacts a network target, starts a
listener, or writes to disk. No new dependency: the framing is about fifty
lines and the package already has everything it needs.

This began as an assessment of whether the surface was worth building. The
assessment is kept below because the reasoning is the specification -- what is
exposed, what deliberately is not, and why -- and the three prerequisites it
named are now met rather than deleted.

> **Two different things, both called MCP, and both now shipped.** This
> document is about apiverity *being* an MCP server, so an agent can ask it
> whether a change is breaking.
>
> The other direction — reading MCP *as a contract format*, loading a server's
> `tools/list` manifest, diffing two versions and detecting drift against a
> live server — is [spec support](spec-support.md), the `BRK-MCP-*` family in
> the [rule catalog](rule-catalog.md), and [MCP drift](mcp-drift.md). The two
> are independent: one governs other people's agent tooling, the other exposes
> this tool to an agent.

## Why this project fits

An agent editing an API spec has a question this tool already answers exactly:
*did that change break anything, and for whom?* The answer is deterministic,
fast, needs no network, and is already emitted as a structured `result-v1`
artifact rather than prose. That is close to an ideal MCP tool: a typed
question with a typed answer and no side effects.

It also fits the failure mode MCP tools tend to have. An agent asking a model
"is this breaking?" gets a plausible answer. Asking this tool gets one with a
rule id behind it that the agent can quote and a human can check.

## What would be exposed

Seven of the twenty-one commands are pure functions of files on disk. (This
document said "nine" above a table of seven for its whole life;
`tests/unit/test_mcp_server.py` now binds both numbers to the code -- the seven
to `len(TOOLS)` and the table's own row count, the twenty to the CLI's
subparsers -- so neither can drift again.)

| Tool | Answers |
|---|---|
| `validate` | Is this document a valid contract, and what is wrong with it? |
| `diff` | What changed between these two versions? |
| `breaking` | Which changes break consumers, and in which direction? |
| `changelog` | Render those changes as a human changelog |
| `coverage` | Which operations does this test suite actually touch? |
| `rules` | What rules exist, with ids and severities? |
| `plugins` | Which spec formats are installed? |

Each already supports `--json` and each emits a `result-v1` artifact, so the
MCP schema is the schema the project already publishes. That is most of the
work already done.

## What would deliberately not be exposed

- `drift`, `replay`, `baseline`, `regression` — these contact a target. An
  agent should not be able to send traffic to an arbitrary base URL because a
  prompt told it to. If they are ever exposed it must be behind an explicit
  allowlist supplied by the human, not a parameter the model chooses.
- `mock`, `serve`, `server-db` — these start listeners and hold state. A tool
  call that leaves a process running is not a tool call.
- `export` — writes bundles to disk.

The split is not arbitrary: it is the same boundary
[SAFETY_MODEL.md](safety-model.md) already draws between commands that read and
commands that reach out.

## The three prerequisites, and how they were met

1. **A stable tool schema.** `result-v1` is versioned, but the MCP tool
   *inputs* would be a new public contract with the same
   never-change-a-meaning rule as [exit codes](exit-codes.md). Worth designing
   once rather than growing.
2. **Path confinement.** Every exposed tool takes file paths. An MCP server
   handing an agent unrestricted read access to the filesystem via a spec-path
   argument is a real hazard; the server would need a configured root.
3. **A decision about who ships it.** An `apiverity-mcp` extra keeps the core
   dependency-free, which matters more here than convenience.

All three are now in place, and each carries a test that fails if it regresses:

**The stable tool schema** is versioned by `MCP_TOOLS_SCHEMA_VERSION`,
independently of the package version, which moves for unrelated reasons.
Removing a tool or changing what an argument means increments it.

**Path confinement** resolves every path argument beneath `--root` and refuses
anything outside it, including a sibling directory that merely shares a name
prefix. The subtlety is that the *resolved* path is what reaches the loader:
`detect_and_load` reads the caller's string twice, so validating a candidate
and then passing the original string onward would not be confinement at all.
`http(s)://` sources are refused outright, because `specs.read_source` accepts
them and would fetch them -- server-side request forgery through an argument a
model chooses, in a server documented as making no network calls.

**Who ships it** turned out to need no answer: writing the JSON-RPC framing
directly costs about fifty lines and no dependency, so the core stays as it
was. The console script is `apiverity-mcp`.

One thing this document did not anticipate. The CLI keeps artifact provenance
in four process globals (`_LAST_SPEC`, `_LAST_PROTOCOL`, and two more) set as a
side effect of loading a contract, and `_load` calls `sys.exit` on a bad path.
Both are correct for one command per process and wrong for a server: a `rules`
call, which loads nothing, would have reported the previous caller's spec as
its own provenance, and one bad path would have ended the session. Handlers
call `core.artifact.enrich` directly with per-call arguments instead, and never
touch `_emit` -- which also prints to stdout, and stdout is the frame stream.
