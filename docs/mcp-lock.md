---
description: >-
  A signed baseline of an MCP tool surface in `mcp.lock`, so CI fails the moment the surface changes without review.
---

# `mcp.lock`: a reviewed baseline for a tool surface

```bash
# capture what a server exposes today, and commit the result
apiverity mcp-lock write --base-url http://127.0.0.1:3000/mcp

# in CI: fail if it moved
apiverity mcp-lock check --base-url http://127.0.0.1:3000/mcp
```

## What this is for

`drift` answers "does this server still match the manifest", which requires a
manifest somebody captured and kept. Most teams have neither. Their agent talks
to a server they do not control, its tool surface changes whenever the operator
ships, and the first sign of it is behaviour.

A lockfile changes who has to notice. The surface is captured once, committed,
and CI fails on **any** change until a human edits the file in a pull request —
the same bargain `package-lock.json` makes, for the same reason.

That "any" is deliberate and is where this differs from every other gate in
this tool. Elsewhere, exit `1` means findings at or above WARN. Here it means
the surface moved. An added tool breaks nothing and the rule catalogue rightly
grades it INFO; against a baseline it is a capability an agent can now reach
that nobody reviewed, which is the case worth stopping on.

## What is in the file

```json
{
  "lock_version": 1,
  "surface_version": "1.0.0",
  "surface_hash": "sha256:...",
  "tools": { "search_orders": "sha256:..." },
  "surface": { "tools": [ /* the normalized tools */ ] }
}
```

The whole surface, not only a hash. A hash can say *that* something changed;
the question in the pull request is which tool, and whether the change breaks a
caller, and answering it means still having the old surface. `check` rebuilds
it through the same `load_manifest` a fresh capture goes through, so the two
sides handed to the differ were built the same way — otherwise the differences
reported include the ones the loader invented.

So the diff is not this command's opinion. A newly-required argument fires
`BRK-PARAM-ADDED-REQUIRED`; a narrowed enum fires `BRK-ENUM-NARROWED-REQUEST`;
a silently edited description fires `BRK-MCP-TOOL-DESCRIPTION-CHANGED`. Each
finding carries the id you can look up with `apiverity explain`.

The hash is built from the per-tool hashes, sorted by name, so a server that
reorders `tools/list` between calls — which the specification permits, since it
only *SHOULD*s a deterministic order — does not produce a different baseline
every run.

## Where the version lives

An MCP tool carries no version field, and SEP-1575 *Tool Semantic Versioning*
is an open, unsponsored proposal. Rather than invent a field in someone else's
protocol, the version lives in the file you own:

```bash
apiverity mcp-lock write --base-url ... --surface-version 2.1.0
```

`check` runs that version and the classified changes through the same
`suggest_bump` the OpenAPI advisor uses, so the recommendation and the rule ids
behind it come from the shared policy rather than a second implementation:

```
advice: {"required_bump": "major", "suggested_version": "3.0.0",
         "reasons": ["BRK-RPC-REMOVED (ERROR)", "BRK-PARAM-ADDED-REQUIRED (ERROR)"]}
```

A run can report an ERROR *and* recommend a minor bump. That is not a
contradiction: the finding answers "should this have been reviewed", the advice
answers "what does SemVer call it", and adding a tool is a yes to the first and
a minor to the second.

## Signing

```bash
export APIVERITY_LOCK_KEY=...
apiverity mcp-lock write --base-url ... --sign
```

Be precise about what this buys. It is an HMAC over the canonical lock body,
and it detects an edit made by something that did not hold the key. It is not
provenance and it is not a public-key signature — anyone who can run CI can
compute a new one.

`check` reports three states and only one of them is silent:
`MCP-LOCK-SIGNATURE-INVALID` (ERROR) when the contents no longer match,
`MCP-LOCK-SIGNATURE-UNVERIFIED` (WARN) when the lock is signed but the key is
not available here — an unchecked signature is not a passed check — and
`MCP-LOCK-UNSIGNED` (INFO) when there is nothing to check at all.

## Capturing

Both `write` and `check` take either a saved manifest or `--base-url`. The live
path is read-only: it calls `tools/list` and nothing else. If pagination is
capped before the cursor runs out, `write` refuses — a baseline built from part
of a tool list would report every tool on a later page as removed, forever.

## Exit codes

| Code | When |
|---|---|
| `0` | the surface matches the baseline |
| `1` | it changed, or a signature failed |
| `2` | no lockfile, an unreadable one, or a source that is not a manifest |
| `3` | `--base-url` could not be reached |
