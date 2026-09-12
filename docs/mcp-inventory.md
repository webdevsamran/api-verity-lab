---
description: >-
  Find shadow MCP servers: what this checkout and this machine's agent clients are actually configured to reach, checked against an approved inventory.
---

# Shadow MCP servers: what is this machine configured to reach?

```bash
apiverity mcp-inventory                      # this checkout
apiverity mcp-inventory --include-home       # and the developer's clients
apiverity mcp-inventory --inventory approved.yaml
```

## Why this reads files instead of scanning a network

OWASP MCP09 is *Shadow MCP Servers*: an agent reaching a server nobody
approved. The obvious implementation is a port sweep, and it is wrong twice
over.

[`SAFETY_MODEL.md`](safety-model.md) §1 is "explicit targets only". A tool that
sweeps a network when asked is a tool that sweeps a network, and shipping one
would mean shipping an attack capability alongside a governance capability.

And a scan cannot find the case that actually happens. Shadow servers do not
appear on a subnet; they appear in a developer's editor config, one `npx` line
at a time. That list — what the client will start or connect to — is the ground
truth about what an agent on this machine can reach. Nothing here opens a
socket.

## What it reads

| Client | Path | Provenance |
|---|---|---|
| Claude Code | `.mcp.json` | convention |
| Cursor | `.cursor/mcp.json` | docs.cursor.com (project-scoped) |
| VS Code | `.vscode/mcp.json` | convention |
| Claude Desktop | `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS), `%APPDATA%\Claude\claude_desktop_config.json` (Windows) | modelcontextprotocol.io |
| Cursor | `~/.cursor/mcp.json` | docs.cursor.com (global) |
| Windsurf | `~/.codeium/windsurf/mcp_config.json` | convention |
| Continue | `~/.continue/config.json` | convention |

Provenance is recorded per path and printed in the report: a first-party URL
where one exists, "convention" where the location is widely used but was not
verified against a first-party document. Both are useful. Presenting the second
as the first is not.

The last four are read only with `--include-home`. A project checkout is what a
CI run is entitled to look at; a developer's home configuration is a different
thing to go reading, and it should take a flag. `--config PATH` reads anything
else.

## What it will not claim

**A count of zero is never rendered as "you have none."** The report lists
every path it considered, whether the file was there, and how many servers it
held, and closes with a sentence naming how many of the known locations were
actually read. A client this build has not heard of is a gap the reader can
see, not a silence they cannot.

A config that exists but does not parse is reported at WARN rather than
skipped. Skipping it would quietly report fewer servers than exist, which is
the opposite of what an inventory is for.

## Findings

| Rule | Severity | Fires on |
|---|---|---|
| `MCP-SHADOW-SERVER` | ERROR | a configured server absent from `--inventory` |
| `MCP-SHADOW-INLINE-CREDENTIAL` | ERROR | an `env` value that is the credential rather than `${A_REFERENCE}` |
| `MCP-SHADOW-FETCHED-AT-LAUNCH` | WARN | a server started with `npx`/`uvx`/`pipx` — a dependency with no lockfile in front of it (OWASP MCP04) |
| `MCP-SHADOW-PLAINTEXT-URL` | WARN | plain HTTP to a non-local host |
| `MCP-INVENTORY-CONFIG-UNREADABLE` | WARN | a config file that exists and could not be parsed |
| `MCP-INVENTORY-UNCONFIGURED` | INFO | approved, and not found in anything this run read |

`MCP-SHADOW-INLINE-CREDENTIAL` names the key and never the value. Reporting a
leaked credential by copying it into a result artifact is not a fix.

## The inventory file

```yaml
version: 1
servers:
  - name: orders
  - name: reporting
```

A bare list of names works too. Matching is by name, which is what the client
config keys on. An unreadable inventory is an ERROR rather than an empty list —
an empty approved list would silently turn every configured server into a
shadow one.

## After the inventory

`mcp-inventory` says which servers exist. The other two commands say whether
each one is behaving:

- [`apiverity drift`](mcp-drift.md) — does a server still serve what it
  declared, and will it talk to a stranger?
- [`apiverity mcp-lock`](mcp-lock.md) — did its tool surface move without
  review?
