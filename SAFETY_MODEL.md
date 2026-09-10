# Safety Model

How API Verity Lab prevents an analysis tool from becoming an attack tool.
These controls are implemented in code and enforced by default.

Every numbered control below has a test in
`tests/unit/test_safety_model_claims.py`, and a numbered control with no test
fails the build. That is not decoration: controls 2, 4 and 5 lived in
`traffic/safety.py` and `apiverity replay` called none of them for as long as
both existed, so this page described a gate no command went through.

## Target authorization

1. **Explicit targets only.** No command sends traffic anywhere unless a base
   URL/target is explicitly provided by the operator (`--base-url`,
   replay manifest `target`, environment registry entry).
2. **Host allowlists.** Replay requires `--allow-host` entries; the safety
   gate rejects targets outside them (`traffic/safety.py`).
3. **Production opt-in for writes.** A corpus containing POST/PUT/PATCH/DELETE
   is refused against a target that classifies as `production` -- or as
   `unknown`, because a host this cannot classify is not one it should assume
   is safe to write to -- unless `--i-know-this-is-production` is given. A
   read-only corpus replays anywhere in the allowlist: GET, HEAD and OPTIONS
   change nothing, and refusing them is what made the earlier version of this
   gate unadoptable.

   Classification is a heuristic over the hostname (`traffic/safety.py`), which
   is why `unknown` fails closed.

   Self-hosted environment records additionally carry `safety_class`
   (`dev|staging|prod`) and `allowed_modes` (`read-only` default). **These are
   stored and returned; no run consults them.** They are metadata for the
   people reading the registry, not a control, and this page used to imply
   otherwise.

## Replay & load protections

4. **Dry-run first.** `apiverity replay` defaults to dry-run: it reports
   exactly which methods/URLs *would* be sent without sending anything.
5. **Destructive-method gate.** A corpus containing POST/PUT/PATCH/DELETE needs
   each method named (`--allow-method DELETE`) *and* the confirmation token the
   dry run prints — derived from the target, the methods and the corpus size,
   so it cannot be reused for a different run. GET-only corpora replay without
   either.
6. **Declared rates only.** A load shape states its own rate and duration
   (`regression --shape 'ramp:60s@1..20'`) and sends nothing beyond the
   schedule that spec produces; a shape it cannot read is refused rather than
   defaulted. There is no rate this tool picks for you.
7. **No traffic interception, of any kind.** There is no capture proxy, no
   sidecar and no transparent redirection in this project — the only traffic it
   reads is a corpus you exported and passed it. This entry used to describe a
   "local capture mode" that does not exist; if one is ever added, it will be
   an explicitly configured reverse proxy for development services and this
   line will say so about something real.

## MCP tool invocation

8. **Reads by default, always.** `apiverity drift <manifest> --base-url` calls
    only `server/discover` and `tools/list`. Nothing invokes a tool unless
    `--invoke-tool NAME` names one. When credentials are supplied, one extra
    `tools/list` runs with them stripped -- still a read, and the only way to
    learn what the server hands a caller who has none. `--skip-auth-probe`
    turns it off.
9. **Exact names, never globs.** A pattern matched against a live tool list
    would hand the *server* the choice of what runs. Names resolve against the
    declared manifest, so a server cannot offer a name and have it called.
10. **Dry run first, and `--execute` needs a target.** `--invoke-tool` alone
    prints the plan — every tool, every generated argument — and sends nothing.
    `--execute` with no named tool is a usage error, not a wildcard. A target
    that does not classify as local/dev/staging additionally requires
    `--i-know-this-is-production`.
11. **Annotations never authorize anything.** `readOnlyHint` and
    `destructiveHint` are attacker-controlled data — the specification says
    clients MUST treat annotations as untrusted unless the server is trusted —
    so they are reported as findings and are never consulted by the gate. A
    tool claiming to be read-only is no easier to invoke than any other, or the
    safest-looking tool would be the easiest to abuse.
12. **stdio is not supported, deliberately.** Every gate above is expressed
    over a URL: `classify_target` derives local/dev/staging/production from a
    hostname and cannot classify `npx -y some-mcp-server`. Supporting stdio
    would mean spawning a command read out of a config file — arbitrary code
    execution — before any of these controls could express it.

## Data protection

13. **Redaction before persistence.** HAR import and all captured traffic pass
   a configurable redaction DSL (headers, cookies, JSON pointers, query
   params, regex patterns) before anything touches disk
   (`traffic/redact.py`). Reports record `redaction.applied`.
14. **Secret hygiene.** Auth credentials live in env-referenced profiles and
   are never persisted into results, bundles, logs or traces; OTLP trace
   attributes matching authorization/token/secret/password/body keys are
   replaced with `[REDACTED]` before spans materialize (`exporters/otel.py`).
15. **Defensive scanning of contracts themselves** flags embedded secrets,
    sensitive example data and insecure server URLs (`security/packs.py`).
16. **Responses are scanned for credentials, and the credential is never
    recorded.** A live response, a recorded HAR entry and an MCP tool result
    all pass `security/leakage.py`. A finding carries the *kind* of secret, the
    JSON pointer, and its length -- never the value, because a scanner that
    quotes the token it found has copied a live credential into a file, a log
    and a CI annotation.

## Server hardening (self-hosted)

17. Hashed tokens at rest; RBAC role matrix; multi-tenant isolation tests.
18. Fixed-window API rate limiting (opt-in `rate_limit_per_minute`), health
    endpoint exempt.
19. Append-only hash-chained audit events; tampering is detectable
    (`store.audit_verify_chain`).
20. Job queue backpressure returns clean 409s instead of unbounded work;
    idempotency keys make CI retries safe.
21. Backups exclude credential hashes; org exports never contain token hashes.

## Authorization probing

22. **Two identities, one object, and reads only where it counts.**
    `test --authz` creates one resource per collection as the first identity
    and attempts to read, update and delete it as the second. It needs
    `--include-mutations`. It escalates nothing and chains nothing: a finding
    records the operation, the status and which identity called, and there is
    no payload in it. A BFLA probe issues only `GET`, `HEAD` and `OPTIONS` --
    one that issued the `DELETE` it was testing for would be indistinguishable
    from the attack, so an operation that changes state is listed as not
    probed, with that reason.

## What we do not claim

- No automatic legal compliance (GDPR/PCI) from PII annotations — they are
  classification hooks for humans.
- Fuzz/load/replay against any target you are not explicitly authorized to
  test remains your responsibility; the gates above make accidents harder,
  not permission.
