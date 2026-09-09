# Capability Status

Honest classification of the transformation target list against the actual
codebase (audited 2026-08-26). "NEW" items below were implemented in this
pass; "EXISTING" items were already present and verified by tests.

Legend: EXISTING · PARTIAL (improved this pass where noted) · NEW (this pass) · BLOCKED (external validation required) 

## Core model & protocols
- Protocol v2 normalized model, stable entity IDs, canonical hashes, artifact migration — EXISTING (`core/model_v2.py`)
- Swagger 2.0 import with loss warnings; bundles + catalog index; ownership mapping — EXISTING
- AsyncAPI 2.x and 3.x adapter, registered under `apiverity.specs` — EXISTING (`specs/asyncapi.py`); direction normalized to the application's point of view so a 2.x document and its 3.x migration compare as equivalent
- OpenAPI 3.0/3.1 deepening (callbacks/webhooks/discriminators/security inheritance) — PARTIAL (parser-level support; compat coverage for callbacks is partial)
- JSON Schema 2020-12-aware comparisons — PARTIAL (shared SchemaNode semantics; `$dynamicRef` not modeled)
- GraphQL: SDL import with provenance (**fixed in an earlier pass**: a kind-casing bug that silently loaded zero operations), schema-driven query generation, persisted operation documents (`test --operations`), `{data, errors}` envelope assertions, and introspection-based drift (`drift --base-url`) — EXISTING (`specs/graphql/operations.py`, `specs/graphql/runner.py`)
- gRPC: `.proto` sources and compiled `FileDescriptorSet` input (`.desc`/`.pb`/`.protoset`) — EXISTING (`specs/grpc/descriptor.py`, no protobuf runtime dependency); streaming cardinality, explicit presence, oneof membership and reserved ranges in the diff; wire-compat metadata (`diff/protocol_compat.py`)
- SSE / WebSocket message-contract representations — EXISTING (operation kinds `EVENT`, `WS_MESSAGE`)
- MCP tool manifests (`specs/mcp/`): a saved `tools/list` — envelope, JSON-RPC
  frame or bare dump — compiled into the same contract model, so the existing
  breaking rules apply unchanged. Adds `BRK-MCP-*` for what is MCP's alone:
  the four `ToolAnnotations` hints, `outputSchema` presence, description edits
  (OWASP MCP03) and paginated captures. Cache and pagination state (`ttlMs`,
  `cacheScope`, `nextCursor`) is excluded by whitelist so it can never diff.
  Runtime drift against a live server is NOT part of this — EXISTING

## Diff / breaking / governance
- Request/response-direction rules, enum/constraint/object/composition analysis, status-code/content-negotiation/header/security/server/pagination/idempotency compat — EXISTING (`diff/compat.py`, wired into CLI **this pass**)
- GraphQL breaking rules + dangerous-change category — NEW (`diff/protocol_compat.py`)
- gRPC wire compatibility (type swaps, width changes, enum removals, field retirement guidance) — NEW
- Contract lint, policy rule packs, expiring suppressions, deprecation lifecycle, semver engine, lifecycle states/transitions — EXISTING
- Diff fingerprints dedup across revisions — EXISTING (`model_v2.fingerprint_findings`)
- Release-sequence changelog aggregation, git blame linking, PR baseline discovery — BLOCKED (needs multi-version corpus + repo context in CI; interfaces documented)
- Consumer registry & impact mapping — PARTIAL (can-i-deploy derives from verification runs; explicit per-operation consumer registry is a contributor opportunity)

## Generation & stateful testing
- Seeded positive/negative generation, boundary values, pairwise, example mutation, shrinking, corpus export/import/replay — EXISTING
- Pluggable case generators via `apiverity.generators`, invoked by `apiverity test --generator` — EXISTING (`fuzz/generators.py`); built-ins: unicode, nesting, numeric, header-safety
- Workflow engine v2 (extraction/guards/cleanup), graph validation, templates, model-based CRUD — EXISTING
- Workflow inference from OpenAPI Links (`workflow --infer`) — EXISTING (`stateful/infer.py`); links-only, every step emitted commented out, destructive steps commented twice

## Runtime: drift, replay, performance
- Drift monitor, baselines/trends, field-frequency analysis, HAR normalization with redaction DSL, replay manifests/dry-run/destructive gate — EXISTING
- MCP runtime drift (`drift <manifest> --base-url`): declared tool schema vs a
  live server over Streamable HTTP. `MCP-DRIFT-*` compares the manifest to the
  server (missing, undeclared, schema drift traced back to the `BRK-*` rule
  that classified it, contradicted annotations); `MCP-CONF-*` checks the server
  against the specification with no manifest at all, including a second
  connection to verify the tool set does not vary per connection. Silent by
  design where the run established nothing: a hit page cap suppresses every
  missing-tool finding, and a refused protocol revision stops before any
  comparison. stdio is deliberately unsupported -- `classify_target` works on
  URLs, so none of the safety gates can express a command line — EXISTING
  (`runtime/mcp_drift.py`, `specs/mcp/runner.py`)
- Corpus drift (`drift --corpus`): aggregated frequency per finding, systematic vs one-off classification, content-negotiation-aware schema selection, corpus-quality summary — EXISTING (`runtime/corpus_drift.py`)
- Shadow contract inference draft + reconciliation report — BLOCKED (requires sanitized traffic corpora at scale)
- Local reverse-proxy capture mode — BLOCKED (interface specified; socket-level work outstanding)
- Load profiles incl. Poisson + capacity search, p50–p99 metrics, budgets/regressions — EXISTING
- Response-size/bandwidth metrics, TLS timing breakdown, GraphQL op budgets, gRPC latency metrics — PARTIAL

## Mock & virtualization
- Mock v2 scenarios/state/faults/seed control; virtualization workspace from bundles; request validation mode — EXISTING

## Security & privacy
- Defensive security packs, OAuth scope coverage, sensitive-field redaction, auth profiles — EXISTING
- OTLP trace export with attribute redaction — NEW (`exporters/otel.py`)

## Self-hosted server
- Orgs/users/RBAC, contracts/findings/runs/environments/policies/approvals, hash-chained audit, signed webhooks, can-i-deploy, retention purge, health/readiness/metrics — EXISTING
- Worker enrollment + pull-based job queue with idempotency keys and backpressure — NEW (`server/jobs.py`)
- SSE run progress stream — NEW (`GET /v1/runs/<id>/events`)
- Backup/restore/export/import (+ `apiverity server-db` command) — NEW
- API rate limiting — NEW (`create_app(rate_limit_per_minute=…)`)
- OIDC/SAML concrete providers — BLOCKED behind a real IdP; `IdentityProvider` protocol + local provider exist and are tested

## Frontend
- 30-route product UI (public/local + team pages), design tokens, dark/light/system themes, virtualized tables, DEMO labeling, demo corpus generator — EXISTING. The route count is derived from `web/src/pages/index.tsx`, not asserted here

## Deliberately not pursued
See `PRODUCT_GAPS.md` ("Features deliberately not pursued").
