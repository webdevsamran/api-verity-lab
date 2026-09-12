---
description: >-
  One language server, so breaking-change diagnostics appear as you type in VS Code, Neovim, JetBrains, Helix, Zed and Emacs without five separate plugins.
---

# Editor diagnostics, from one language server

Editor support for a linter is usually five plugins, each reimplementing the
same checks against the same rules, each drifting from the tool at its own
speed. `apiverity lsp` is the alternative: one server, speaking the Language
Server Protocol on stdio, running exactly the rules `apiverity validate` runs —
because it is that engine answering.

```bash
apiverity lsp
```

Nothing is printed. stdout *is* the protocol stream, and a single line of
anything else desynchronises every frame after it.

## Setting it up

### VS Code

The extension in [`editors/vscode`](https://github.com/webdevsamran/api-verity-lab/tree/main/editors/vscode)
is a thin client around this server. Build it from the repository with
`npm ci && npm run compile`; CI compiles it on every pull request, and a test
holds its document selector against this server's own file list, because a
client that never activates for a format looks exactly like a clean file.

### Neovim (0.11+)

```lua
vim.lsp.config.apiverity = {
  cmd = { 'apiverity', 'lsp' },
  filetypes = { 'yaml', 'json', 'graphql', 'proto' },
  root_markers = { '.apiverity.yaml', '.git' },
}
vim.lsp.enable('apiverity')
```

### Helix — `languages.toml`

```toml
[language-server.apiverity]
command = "apiverity"
args = ["lsp"]

[[language]]
name = "yaml"
language-servers = ["yaml-language-server", "apiverity"]
```

### Emacs — `eglot`

```elisp
(add-to-list 'eglot-server-programs
             '((yaml-mode yaml-ts-mode) . ("apiverity" "lsp")))
```

### JetBrains

Via the LSP4IJ plugin, as a "Command line" server with `apiverity lsp`.

## What it does

**Diagnostics** on open, change and save. Every rule `validate` runs, security
checks included, with the rule id as the diagnostic `code` and a
`codeDescription` link to the catalogue entry — so the rule id in the problem
list is clickable.

**Hover** over a diagnostic's line, showing the finding in full including its
hint. Editors truncate diagnostic text in the gutter, and the sentence saying
what to do about it is usually the part that gets cut.

**A parse error is reported as a finding**, not as silence. An empty diagnostic
list means "this is fine", and a document that will not load is not fine.

## What it deliberately does not do

Completion, formatting and go-to-definition. A spec-aware completion provider
is real work, and there are editor plugins that already do it well for OpenAPI;
a thin one here would get in their way for no gain. This server does the thing
no other plugin does — it runs *these* rules.

## Three decisions worth knowing about

**It lints the buffer, not the file.** That is the point of a language server,
and it means the text on screen is written to a scratch file and loaded through
the ordinary loader. One loader, one model: a second parse path would be a
second thing that can disagree with the CLI.

**The scratch file goes beside your document.** A contract's
`$ref: ./schemas/money.yaml` resolves relative to the file holding it, so
linting a copy in the system temp directory would report every sibling
reference as unresolvable — a wall of errors caused entirely by the linter. The
file is dot-prefixed, and removed on every exit path including the failure ones.

**Typing is debounced by 400 ms.** `didChange` fires per keystroke; loading a
contract and running every rule on each one would keep a core busy while you
type. Opening and saving are not debounced, because a file that stays blank for
half a second after opening reads as a server that is not working.

## Only files it has an opinion about

`.yaml`, `.yml`, `.json`, `.graphql`, `.gql`, `.graphqls`, `.proto`, `.wsdl`.
Anything else gets no publish at all — not an empty one, which would clear
another linter's diagnostics from the problem list for a file this server never
looked at.

## Line zero

Some findings are about the document rather than a place in it — "this contract
declares no security schemes at all". Those carry no line, and land on line 1,
which is the closest true thing an editor can show. They are not silently
dropped: a finding nobody can see is a finding nobody has.
