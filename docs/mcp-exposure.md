# Should api-verity-lab expose an MCP server?

**Verdict: yes, for a deliberately small read-only subset. Not yet built.**

This is an assessment, not a feature. Nothing here ships today; the point is to
record what the surface would be and what has to be true before it exists.

> **Two different things, both called MCP.** This document is about apiverity
> *being* an MCP server, so an agent can ask it whether a change is breaking.
> That is unbuilt.
>
> Reading MCP *as a contract format* — loading a server's `tools/list`
> manifest, diffing two versions of it, and classifying the changes — ships
> today. See [spec support](spec-support.md) and the `BRK-MCP-*` family in the
> [rule catalog](rule-catalog.md). The two are independent: one governs other
> people's agent tooling, the other exposes this tool to an agent.

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

Nine of the nineteen commands are pure functions of files on disk:

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

## What has to be true first

1. **A stable tool schema.** `result-v1` is versioned, but the MCP tool
   *inputs* would be a new public contract with the same
   never-change-a-meaning rule as [exit codes](exit-codes.md). Worth designing
   once rather than growing.
2. **Path confinement.** Every exposed tool takes file paths. An MCP server
   handing an agent unrestricted read access to the filesystem via a spec-path
   argument is a real hazard; the server would need a configured root.
3. **A decision about who ships it.** An `apiverity-mcp` extra keeps the core
   dependency-free, which matters more here than convenience.

None of these is hard. They are simply not free, and the honest position is
that this is a good idea that has not been built rather than a capability the
project has.
