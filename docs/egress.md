---
description: >-
  Every place this package can open a socket, walked out of the source rather than remembered -- which is what makes the no-telemetry claim checkable.
---

# Where this connects, and what makes it

`docs/self-hosting.md` says "no telemetry, no phone-home, no auto-update". That
is true. Until now it was a sentence somebody typed.

A tool asking to be run inside a disconnected network has to answer the harder
question — *where can it open a socket, and what makes it?* — from the code
rather than from memory. The table below is walked out of the package by
`scripts/generate_egress_map.py`, and CI fails when it disagrees with the
source.

## The short version

**Nothing here connects unless you tell it to.** Every call site below is
behind a flag naming an address: `--base-url`, `--target`, `--otlp-endpoint`,
`--send`, `--allow-remote-refs`, or a spec given as a URL. There is no
background connection, no version check, no usage report.

<!-- generated:egress -->
Found by `scripts/generate_egress_map.py`: **24 call sites** across **18 modules** that can open a network connection.

| Module | Triggered by | Calls |
|---|---|---|
| `apiverity/cli/commands/platform.py` | `notify --send`, `freeze` against a server | `httpx.get` (platform.py:217), `httpx.post` (platform.py:1039), `httpx.post` (platform.py:228), `httpx.request` (platform.py:230) |
| `apiverity/cli/commands/runtime.py` | `capture`, `drift` | `httpx.Client` (runtime.py:767) |
| `apiverity/cli/commands/testing.py` | `test --base-url` | `httpx.Client` (testing.py:167), `httpx.Client` (testing.py:287) |
| `apiverity/exporters/otel.py` | `--otlp-endpoint` | `httpx.post` (otel.py:199) |
| `apiverity/fuzz/minimize.py` | `test --minimize` | `httpx.Client` (minimize.py:55), `httpx.Client` (minimize.py:72) |
| `apiverity/fuzz/runner.py` | `test --base-url` | `httpx.Client` (runner.py:203) |
| `apiverity/performance/engine.py` | `regression` / `baseline` with `--base-url` | `httpx.Client` (engine.py:268) |
| `apiverity/plugins/builtins.py` | the built-in httpx transport, used by the above | `httpx.Client` (builtins.py:46) |
| `apiverity/runtime/drift.py` | `drift --base-url` | `httpx.Client` (drift.py:134) |
| `apiverity/runtime/ghosts.py` | `ghosts --base-url` | `httpx.Client` (ghosts.py:178) |
| `apiverity/server/oidc.py` | — | `httpx.get` (oidc.py:152) |
| `apiverity/specs/__init__.py` | a spec given as a URL rather than a path | `httpx.get` (__init__.py:58) |
| `apiverity/specs/bundle.py` | a remote `$ref`, and only with `--allow-remote-refs` | `httpx.get` (bundle.py:510) |
| `apiverity/specs/graphql/runner.py` | `test` / `drift` against a GraphQL endpoint | `httpx.Client` (runner.py:124), `httpx.Client` (runner.py:83) |
| `apiverity/specs/mcp/runner.py` | `drift <manifest> --base-url` | `httpx.Client` (runner.py:240) |
| `apiverity/stateful/engine.py` | `workflow run --base-url` | `httpx.Client` (engine.py:247) |
| `apiverity/traffic/capture.py` | `capture` forwarding to its one `--target` | `httpx.Client` (capture.py:383) |
| `apiverity/traffic/replay.py` | `replay --send` | `httpx.Client` (replay.py:63) |

### Modules with no trigger listed

- `apiverity/server/oidc.py`

A module here is a call site nobody has said what causes. That is the gap worth closing before trusting this table.

### Network libraries imported

`http.server`, `httpx`, `socket`, `urllib.parse`, `urllib.request`
<!-- /generated:egress -->

## What this table does and does not prove

It proves where a connection **can** originate. It does not prove a given run
makes none — that depends on the flags, which is why each module carries the
thing that triggers it.

What it rules out is the failure this document exists to prevent: a call site
nobody remembered. The scan is over the AST, not over a list somebody
maintains, and a module that acquires a network call without a stated trigger
is reported by name.

An HTTP library the scanner does not know how to follow (`requests`,
`aiohttp`, and the rest) is reported as unrecognised rather than ignored,
because the alternative is a table that silently stops being complete.
