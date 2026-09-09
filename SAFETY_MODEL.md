# Safety Model

How API Verity Lab prevents an analysis tool from becoming an attack tool.
These controls are implemented in code and enforced by default.

## Target authorization

1. **Explicit targets only.** No command sends traffic anywhere unless a base
   URL/target is explicitly provided by the operator (`--base-url`,
   replay manifest `target`, environment registry entry).
2. **Host allowlists.** Replay requires `--allow-host` entries; the safety
   gate rejects targets outside them (`traffic/safety.py`).
3. **Production opt-in.** Non-local targets require an explicit
   `--i-know-this-is-production` acknowledgment for destructive-capable runs;
   environment records carry `safety_class` (`dev|staging|prod`) and
   `allowed_modes` (`read-only` default).

## Replay & load protections

4. **Dry-run first.** `apiverity replay` defaults to dry-run: it reports
   exactly which methods/URLs *would* be sent without sending anything.
5. **Destructive-method gate.** POST/PUT/PATCH/DELETE replay requires both an
   allowlist and explicit confirmation; GET-only corpora replay safely by default.
6. **Rate ceilings.** Constant/ramp/spike/soak/Poisson profiles are bounded
   by manifest-declared rates; capacity search runs only against targets
   classified as test/dev.
7. **No transparent interception.** Local capture mode is an explicitly
   configured reverse proxy for development services — never silent traffic
   redirection.

## MCP tool invocation

8. **Reads by default, always.** `apiverity drift <manifest> --base-url` calls
    only `server/discover` and `tools/list`. Nothing invokes a tool unless
    `--invoke-tool NAME` names one.
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

## Server hardening (self-hosted)

16. Hashed tokens at rest; RBAC role matrix; multi-tenant isolation tests.
17. Fixed-window API rate limiting (opt-in `rate_limit_per_minute`), health
    endpoint exempt.
18. Append-only hash-chained audit events; tampering is detectable
    (`store.audit_verify_chain`).
19. Job queue backpressure returns clean 409s instead of unbounded work;
    idempotency keys make CI retries safe.
20. Backups exclude credential hashes; org exports never contain token hashes.

## What we do not claim

- No automatic legal compliance (GDPR/PCI) from PII annotations — they are
  classification hooks for humans.
- Fuzz/load/replay against any target you are not explicitly authorized to
  test remains your responsibility; the gates above make accidents harder,
  not permission.
