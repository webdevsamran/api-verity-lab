# MCP tool poisoning: reading a description as executable text

```bash
apiverity validate tools.mcp.json
```

Every MCP manifest that goes through `validate` is scanned for content aimed at
whoever reads it next. There is no flag: these findings arrive with the rest of
the static security lint, in the same `result-v1` artifact, at the same exit
codes.

## Why a description is a security surface here and nowhere else

In OpenAPI, a description is documentation. A human reads it, and rewriting it
changes nothing about how any software behaves.

In MCP, the description **is the routing input**. An agent chooses which tool to
call, and what to put in its arguments, by reading the description and the
schema. That makes the text executable in the only sense that matters, and it
makes a silent edit to a published tool the whole shape of the attack. OWASP
lists it as **MCP03 Tool Poisoning** in the MCP Top 10, and the first public
proof of concept simply wrapped instructions in an `<IMPORTANT>` block that no
client rendered and every model read.

Nothing else in `apiverity/security/` has a subject like that. The contract
packs look for secrets a document committed by accident. This looks for text a
document is aiming at a reader.

## What is reported

| Rule | Severity | Fires on |
|---|---|---|
| `MCP-POISON-INVISIBLE-TEXT` | ERROR | Zero-width formatting, bidirectional overrides, or the Unicode tag block (U+E0000–U+E007F) in a name, title, description or schema description |
| `MCP-POISON-CREDENTIAL-PATH` | ERROR | Prose naming `~/.ssh`, `id_rsa`, `.aws/credentials`, `.env`, `/etc/passwd`, a client's own `mcp.json`, or a private-key path |
| `MCP-POISON-INSTRUCTION` | WARN | A sentence addressed to the agent rather than describing the tool |
| `MCP-POISON-HIDDEN-MARKUP` | WARN | Text inside an HTML comment, invisible in a rendered client and fully visible to the model |
| `MCP-POISON-CROSS-TOOL` | WARN | A description naming a *different* declared tool alongside an instruction |
| `MCP-POISON-DESCRIPTION-OUTSIZED` | INFO | One description both over 1,000 characters and eight times the manifest median |
| `MCP-ANNOTATION-CONTRADICTS-NAME` | WARN | `readOnlyHint: true` on a tool whose name is a mutating verb |
| `MCP-ANNOTATION-CONTRADICTORY` | WARN | `readOnlyHint: true` together with `destructiveHint: true` |
| `MCP-ANNOTATION-ABSENT` | INFO | Tools declaring no annotations at all, counted once for the manifest |

The scan reads the tool name, its title, its description, and every `title` and
`description` inside the input and output schemas. A payload in a property
description reaches the model exactly as well as one in the summary.

## What it will not claim

**It does not assert intent.** A description saying "ignore previous
instructions" may be a poisoned tool or a tool that manages prompts.
`MCP-POISON-INSTRUCTION` says the sentence addresses the agent rather than
describing the tool, which is true either way, and quotes the phrase that
matched so a reviewer can go and read it.

**Only two families are ERROR**, and both are for content with no benign
reading: characters that reach the model and cannot reach a human, and prose
pointing the agent at a credential path. Everything else is WARN or INFO,
because a governance gate that blocks a merge on a guess is a gate someone turns
off, and then it catches nothing at all.

**Annotations still authorize nothing.** The specification says a client MUST
treat annotations as untrusted unless the server itself is trusted.
[`SAFETY_MODEL.md`](safety-model.md) §11 already refuses to let `readOnlyHint`
open any gate in this tool; the annotation rules here refuse to let one close a
gate either. A tool claiming to be read-only while calling itself
`delete_account` is reported so a person decides.

## Deliberate non-detections

Two exemptions exist because a check that fires on ordinary manifests is a check
that gets disabled:

- A **zero-width joiner between two pictographs** is a family emoji, not hidden
  text. A joiner between ordinary letters still fires.
- A **uniformly long manifest** is a well-documented manifest.
  `MCP-POISON-DESCRIPTION-OUTSIZED` needs both an absolute size and a local
  outlier, and needs at least three described tools before a median means
  anything.

## What this does not cover

This is a static read of one document. It cannot tell you that a server changed
its descriptions after you captured them — that is drift, and it is
[a different command](mcp-drift.md) with a live target. Run both: the static
scan says whether the manifest you have is safe to hand an agent, and the drift
check says whether it is still the manifest the server is serving.
