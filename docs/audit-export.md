# Tamper-evident audit export

The self-hosted server has hash-chained every audit entry into the previous one
since the beginning. Two things were missing, and both of them are the part an
auditor actually needs.

**The auditor could not run the check.** Verification lived inside the process
that wrote the log, reading the database that holds it. That is the one
arrangement that proves nothing: a party who can rewrite the entries can rewrite
the verifier too. Evidence has to be checkable *away* from the thing it is
evidence about.

**And `False` is not an answer.** A tamper-evident log that reports "invalid"
without saying which entry broke sends a responder to read ten thousand rows by
hand, and gives an auditor nothing to put in a finding.

```bash
apiverity audit export --db server.db --org-id 1 -o audit-2026-09.json
```

```bash
apiverity audit verify audit-2026-09.json --against audit-2026-08.json
```

`verify` reads the file and nothing else — no database, no server, no network.

## What the document contains

Every entry, oldest first, with no page limit. `GET /v1/audit` caps at a hundred
because it renders a screen; an export that stopped there would be a shorter
history presented as the whole one.

Alongside them, **the algorithm in words**:

| Field | Value |
|---|---|
| `hash` | `sha256` |
| `basis` | `{prev_hash}\|{ts}\|{actor}\|{action}\|{target}\|{payload_json}` |
| `encoding` | `utf-8` |
| `digest` | lowercase hex |
| `first_prev_hash` | the empty string |

That block is not decoration. It is what lets someone reimplement the check in
twenty lines of anything, which is the difference between evidence and a claim.
The entry fields carried are fixed (`id`, `ts`, `actor`, `action`, `target`,
`payload_json`, `prev_hash`, `entry_hash`) rather than "whatever columns the
table has", so a column added later cannot change the sealed bytes and make
every stored export fail to verify.

A broken chain is exported too, with `chain.valid: false` and the id of the
first entry that failed. An export that refused to write a broken chain would
let the break be hidden by exporting.

## What it proves, and what it does not

Stated here, and stated again in the `limits` array of every export document,
because an evidence artifact that overstates what it proves is worse than no
artifact.

| Attack | Detected by | Notes |
|---|---|---|
| An entry was **edited** | the chain, alone | `entry_hash` stops matching that entry's contents. Reported as `it was edited`, with the id. |
| An entry was **inserted, removed or reordered** in the middle | the chain, alone | `prev_hash` stops matching the preceding entry. Reported separately, because a broken *link* and an edited *row* mean different things. |
| Entries were **deleted from the end** | only `--against` an earlier export | A truncated chain verifies perfectly: the tail is where the chain ends, so nothing points past it. This is the failure that matters most in practice — somebody removes the last four entries, which are the interesting ones. |
| The **whole history was rebuilt** | only the seal, or `--against` | The algorithm is public, so anyone who can rewrite every row can recompute every hash. What they cannot recompute is an HMAC whose key was never in the database. |

The second and third rows are the reason exports are worth **keeping** rather
than regenerating on demand. Each export records its `last_entry_hash`, and the
next export must still contain every earlier entry, at the same index, with the
same hash. `--against` is that comparison, and it reports `continuous`,
`truncated`, `rewritten` or `different org`.

## The seal

```bash
export APIVERITY_AUDIT_KEY='...'
apiverity audit export --db server.db --org-id 1 -o audit.json \
  --hmac-key-env APIVERITY_AUDIT_KEY
```

The flag takes the **name** of an environment variable, never the value. A key
passed on the command line is in the shell history, in the CI log that echoes
the command, and in the process table for every other user on the machine. An
unset variable is a usage error rather than a silently unsealed export, because
handing somebody a document they believe is sealed is worse than refusing.

The seal is HMAC-SHA256 over the document with its `seal` member removed,
serialised with sorted keys and no whitespace between tokens — so a verifier in
another language can parse, re-serialise and reach the same digest.

`GET /v1/audit/export` deliberately does **not** offer sealing. It would mean
the server holding the key, and a key held by the system under audit seals
nothing.

Verification reports the seal in four states, because "the seal was fine" and
"nobody looked at the seal" are the two things an auditor must not confuse:

- `valid`
- `invalid` — *"the document was altered, or the key differs"*, both readings
  named, because both are real
- `present, not checked (no key supplied)`
- `expected but absent` — a key was supplied and the document carries no seal

## Exit codes

`audit export` and `audit verify` follow the [exit-code
contract](exit-codes.md): `0` when the chain holds, `1` when it does not. Exit
`0` on a broken chain would report that the export succeeded while saying
nothing about the log, which is the wrong half.

## Where this fits

The mapping from findings to SOC 2, ISO 42001, DORA and the EU AI Act is in
[compliance mapping](compliance-mapping.md); packaging a dated set of artifacts
is in [evidence packs](evidence.md). This document is about the one artifact
that has to survive being disbelieved.
