# api-verity-lab for VS Code

Contract-governance diagnostics in the editor: breaking-change rules, security
lint, MCP tool-poisoning checks and the rest, on OpenAPI, AsyncAPI, GraphQL,
gRPC, WSDL and MCP tool manifests.

## What this extension is

A thin client over `apiverity lsp`, and thin is the design. Every rule, every
severity and every message comes from the server, so this extension cannot
drift from the CLI — there is nothing here to drift. What it owns is the part
an editor has to own: finding the executable, saying something useful when it
is not there, and restarting cleanly.

The engine is [api-verity-lab](https://github.com/webdevsamran/api-verity-lab),
and [`docs/lsp.md`](https://github.com/webdevsamran/api-verity-lab/blob/main/docs/lsp.md)
describes the server, including the same setup for Neovim, Helix, Emacs and
JetBrains.

## Requirements

`apiverity` on `PATH`, or an absolute path in `apiverity.serverPath`.

```bash
curl -fsSL https://raw.githubusercontent.com/webdevsamran/api-verity-lab/main/install.sh | sh
```

Every other install channel is in
[`docs/install.md`](https://github.com/webdevsamran/api-verity-lab/blob/main/docs/install.md).

If the executable cannot be run, the extension says so with a link to that
page. It does not fail silently: "no diagnostics" and "the linter never
started" look identical to a reader, and only one of them means the file is
fine.

## Settings

| Setting | Default | |
|---|---|---|
| `apiverity.enable` | `true` | Run the language server. |
| `apiverity.serverPath` | `apiverity` | The executable — a virtualenv's `bin/apiverity`, for instance. |
| `apiverity.args` | `["lsp"]` | How the server is started. |
| `apiverity.trace.server` | `off` | Log the traffic, in the **apiverity** output channel. |

Changing any of the first three restarts the server, because leaving the old
one running would show diagnostics from a tool you have just replaced.

## Commands

- **apiverity: Restart the language server**
- **apiverity: Show the server log**

## Building it from the repository

```bash
cd editors/vscode
npm ci
npm run compile
```

`npm run compile` runs in CI, so the extension cannot be committed in a state
that does not build. What CI does **not** do is launch VS Code, so "it
compiles and its document selector matches the server's file list" is the
claim being made, and it is checked; "it works in the editor" is not something
this repository's CI has established.
