# MCP drift: declared tool schema vs a running server

```bash
apiverity drift manifest.json --base-url http://127.0.0.1:3000/mcp --json
```

Compares a saved `tools/list` manifest against what an MCP server actually
serves. It is read-only: `server/discover` and `tools/list` are reads, and
nothing here invokes a tool.

## Why this leg and not the other one

Diffing two *versions* of a manifest is well served — several published
packages do it, and this project does it too, through
[the shared rule catalogue](rule-catalog.md). Comparing a **declared** schema
against a **running** server is not, and it is the question that actually
breaks agents in production: the manifest an agent was generated from and the
server it is calling are two different artifacts that drift apart.

That comparison is what this engine has been doing for five other protocols
since v0.1, so MCP inherits it rather than reimplementing it.

## What it reports

Two families, deliberately separate because they answer different questions.

**`MCP-DRIFT-*` — the manifest against the server.** Needs a manifest.

| Rule | Severity | Fires when |
|---|---|---|
| `MCP-DRIFT-TOOL-MISSING` | ERROR | Declared but not served. An agent generated from this manifest will call it and fail. |
| `MCP-DRIFT-TOOL-UNDECLARED` | WARN | Served but not declared. Agents discover it and may call a capability nobody agreed to support. |
| `MCP-DRIFT-SCHEMA` | ERROR | The served schema differs in a way the shared catalogue grades breaking. Carries the `CHG-*` id and the `BRK-*` rule that classified it. |
| `MCP-DRIFT-SCHEMA-COMPATIBLE` | WARN/INFO | The same comparison, where the change is not breaking. |
| `MCP-DRIFT-ANNOTATION` | WARN | A declared hint disagrees with the served one. An agent that planned around the declared value planned wrong. |
| `MCP-DRIFT-PROTOCOL-UNSUPPORTED` | ERROR | The server refused the protocol revision. No tools were compared — see below. |
| `MCP-DRIFT-LEGACY-SERVER` | INFO | No `server/discover`. Compared anyway; the revision is not claimed. |
| `MCP-DRIFT-PAGINATION-CAPPED` | WARN | The page cap was reached. Missing-tool findings are suppressed — see below. |

**`MCP-CONF-*` — the server against the specification.** Needs no manifest, so
this half runs against a server nobody has captured yet:

```bash
apiverity drift any-manifest.json --base-url http://127.0.0.1:3000/mcp
```

It checks that `tools/list` carries the `ttlMs` and `cacheScope` a modern list
result requires, that every served tool has the `name` and object-typed
`inputSchema` the specification mandates, and — by opening a **second
connection** — that the tool set does not vary per connection, which the
specification says it MUST NOT. A tool set that changes is an error; an order
that changes is `INFO`, because deterministic ordering is only a SHOULD.

## Three places it deliberately says nothing

Each of these is a case where reporting would mean asserting something the run
did not establish.

**The page cap.** `--max-list-pages` (default 50) bounds how far `nextCursor`
is followed. If the cap is hit, *no* missing-tool finding is emitted at all: a
tool on page fifty-one is not a tool that was removed. The report says the cap
was reached instead.

**A refused protocol revision.** If the server answers `server/discover` with
`-32022`, the run stops before any tool comparison. We never obtained a tool
list, so every declared tool would otherwise read as missing — a confident lie
built on a request that failed.

**A legacy server.** A server with no `server/discover` is compared normally,
because `tools/list` has the same shape in both eras. What is *not* recorded is
a protocol revision: observing the absence of a method is evidence about that
method, not about a version. `protocol_revision` stays `unknown` with a reason.

## Transports

Streamable HTTP only. **stdio is not supported, and that is a decision rather
than a gap.**

[`SAFETY_MODEL.md`](safety-model.md) §1 is "explicit targets only", and every
gate beneath it is expressed over a URL — `classify_target` derives
local/dev/staging/production from `urlparse(base_url).hostname`. It cannot
classify `npx -y some-mcp-server`. Supporting stdio would mean spawning a
command read out of a config file, which is arbitrary code execution and a
categorically different hazard from sending an HTTP request, and doing it
before any of the existing controls can express it. Run a stdio server behind a
Streamable HTTP bridge, or wait for the gate to exist first.

## Authorization

The specification allows a server's tool set to vary by the authorization
presented. `--header NAME=VALUE` (repeatable) is sent on every request, and the
report records `authorization_presented` and the header *names* — never the
values, which do not reach the artifact. A report claiming a tool is missing,
gathered from an unauthenticated probe, has to say it was unauthenticated.

## Authentication posture

Roughly seven thousand internet-exposed MCP servers had been catalogued by
early 2026, and about half of them required no authentication at all. Every
`drift` run against a live server now records what it established about who
that server will talk to, in `auth_posture`, whether or not anything is wrong
-- a posture report that only speaks when something is broken cannot be used as
evidence that nothing is.

What the run does depends on what you supplied:

* **No credentials.** Nothing extra is sent. The `tools/list` that already
  succeeded *is* the evidence: an anonymous caller gets the inventory.
* **Credentials.** One more `tools/list` goes out with them stripped. This is
  the only way to learn whether the credentials were doing anything, and the
  answer that matters is not "anonymous access is refused" but "anonymous
  access returns the same twenty tools". No amount of authenticated probing can
  tell those apart.

`--skip-auth-probe` turns the second one off.

| Rule | Fires on |
|---|---|
| `MCP-AUTH-ANONYMOUS-LIST` | The tool inventory came back to a request carrying no credential |
| `MCP-AUTH-ENFORCED` | It did not -- recorded as INFO, because it is the evidence |
| `MCP-AUTH-NO-CHALLENGE` | A 401 or 403 with no `WWW-Authenticate`, so a client has no way to discover where to authenticate |
| `MCP-AUTH-INDETERMINATE` | The unauthenticated probe did not complete; a failed connection is not evidence of enforcement |
| `MCP-AUTH-PLAINTEXT-TRANSPORT` | Plain HTTP to a target that does not classify as local |

`MCP-AUTH-ANONYMOUS-LIST` is graded by target: INFO for a local host, WARN for
dev, staging and unknown, ERROR for one the classifier calls production. The
fact is identical in all five cases and the consequence is not, and grading a
laptop the same as a public host is how a check earns being ignored on the one
host where it mattered. The classifier is the same
`traffic/safety.py::classify_target` the replay gate uses, and every finding
names the classification it applied so a reader can disagree with it.

None of these cite a specification clause. The MCP authorization story has
moved more than once; what is reported is what the run observed -- which
request, which status, which headers came back. "A 401 with no
`WWW-Authenticate` leaves a client no way to discover where to obtain a
credential" is true regardless of what any revision says about it.

## Calling tools, if you ask for it

`tools/call` has side effects, so it is opt-in and gated the way
`apiverity replay` is:

```bash
# prints the plan -- every tool, every generated argument -- and sends nothing
apiverity drift manifest.json --base-url http://127.0.0.1:3000/mcp \
    --invoke-tool search_orders

# actually sends
apiverity drift manifest.json --base-url http://127.0.0.1:3000/mcp \
    --invoke-tool search_orders --execute
```

* **Exact names only, never globs.** A pattern matched against a live tool list
  hands the *server* the choice of what runs. Names resolve against the
  declared manifest, so a server cannot offer a name and have it called.
* **`--execute` with no `--invoke-tool` is a usage error**, not a wildcard.
* A target that does not classify as local/dev/staging needs
  `--i-know-this-is-production`.
* **Annotations authorize nothing.** `readOnlyHint` is attacker-controlled
  data, and the specification says clients MUST treat annotations as untrusted;
  a tool claiming to be read-only is no easier to invoke than any other. They
  are reported as findings and never consulted by the gate.

Arguments are generated from the **declared** input schema and seeded
(`--seed`, recorded in the artifact) — declared rather than served, because the
question is whether the server honours what it published.

What comes back is checked against the declared `outputSchema`:
`MCP-DRIFT-CALL-OUTPUT-SCHEMA` when `structuredContent` does not conform,
`MCP-DRIFT-CALL-NO-STRUCTURED-CONTENT` when a tool declares a schema and
returns nothing, `MCP-DRIFT-CALL-ERROR-SHAPE` when a tool failure arrives as a
JSON-RPC error rather than a successful result with `isError: true`.

**Findings never quote the value a tool returned.** They carry the JSON
pointer, the declared constraint and the observed *type* —
`"/hits: expected array, got string"` — because a tool result is arbitrary
production data and `docs/privacy.md` promises it does not reach an artifact.
