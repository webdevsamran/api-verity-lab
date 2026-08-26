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

## Data protection

8. **Redaction before persistence.** HAR import and all captured traffic pass
   a configurable redaction DSL (headers, cookies, JSON pointers, query
   params, regex patterns) before anything touches disk
   (`traffic/redact.py`). Reports record `redaction.applied`.
9. **Secret hygiene.** Auth credentials live in env-referenced profiles and
   are never persisted into results, bundles, logs or traces; OTLP trace
   attributes matching authorization/token/secret/password/body keys are
   replaced with `[REDACTED]` before spans materialize (`exporters/otel.py`).
10. **Defensive scanning of contracts themselves** flags embedded secrets,
    sensitive example data and insecure server URLs (`security/packs.py`).

## Server hardening (self-hosted)

11. Hashed tokens at rest; RBAC role matrix; multi-tenant isolation tests.
12. Fixed-window API rate limiting (opt-in `rate_limit_per_minute`), health
    endpoint exempt.
13. Append-only hash-chained audit events; tampering is detectable
    (`store.audit_verify_chain`).
14. Job queue backpressure returns clean 409s instead of unbounded work;
    idempotency keys make CI retries safe.
15. Backups exclude credential hashes; org exports never contain token hashes.

## What we do not claim

- No automatic legal compliance (GDPR/PCI) from PII annotations — they are
  classification hooks for humans.
- Fuzz/load/replay against any target you are not explicitly authorized to
  test remains your responsibility; the gates above make accidents harder,
  not permission.
