# Playground

Paste two versions of a contract. Get the breaking changes, with rule ids.

No account, no upload, no server. This page loads CPython as WebAssembly and
installs the same wheel a `pip install` would, so what runs is
`diff_services` and `evaluate_breaking` — the functions the CLI calls, not a
reimplementation of them.

!!! note "Nothing leaves this tab"

    "Paste your API spec into our website" is a request most people should
    refuse, and most playgrounds are asking exactly that. This one cannot
    receive the text: the analysis happens in your browser, and there is no
    endpoint for it to be sent to.

    The first run downloads Python and pydantic from jsDelivr, which takes a
    few seconds and tens of megabytes. It happens on the first **Compare**, not
    on page load.

<link rel="stylesheet" href="app.css">

<div class="pg">
  <div class="pg-panes">
    <div class="pg-pane">
      <label for="pg-old">Old contract</label>
      <textarea id="pg-old" spellcheck="false" aria-label="the old contract"></textarea>
    </div>
    <div class="pg-pane">
      <label for="pg-new">New contract</label>
      <textarea id="pg-new" spellcheck="false" aria-label="the new contract"></textarea>
    </div>
  </div>
  <div class="pg-controls">
    <button id="pg-run" type="button">Compare</button>
    <button id="pg-sample" type="button" class="pg-secondary">Reset to the sample</button>
    <span id="pg-status" role="status" aria-live="polite"></span>
  </div>
  <div id="pg-output" aria-live="polite"></div>
</div>

<script src="app.js"></script>

## What it runs, and what it leaves out

Everything on the analysis path: the loader, every breaking-change rule, and
the security checks on the new contract. OpenAPI 3.0/3.1/3.2, Swagger 2.0,
AsyncAPI, GraphQL SDL and MCP tool manifests are all recognised by content, so
pasting a GraphQL schema works without changing anything.

What it leaves out is everything that needs the network or the filesystem —
`drift --base-url`, `test`, `replay`, `regression`, the server. A browser tab
cannot probe your staging environment, and a page that pretended to would be
lying about where the answer came from.

Two dependencies the package declares are **not** installed here: `httpx` and
`flask`. Nothing on this path imports them — every command that needs them
imports them inside the function that uses them — and installing them would add
a dozen wheels to a first load for code this page cannot reach. The cost is
that a future import of something new fails at runtime rather than at install
time, so the page catches that and names the missing module instead of showing
a blank result.

## Getting the same answers locally

```bash
curl -fsSL https://raw.githubusercontent.com/webdevsamran/api-verity-lab/main/install.sh | sh
apiverity breaking old.yaml new.yaml
```

The CLI has the rest of it: semver policy, consumer impact, suppressions,
runtime drift, the CI gate. [Installing](install.md) lists every channel.
