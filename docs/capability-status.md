# Capability Status

Honest classification of the transformation target list against the actual
codebase (audited 2026-08-26). "NEW" items below were implemented in this
pass; "EXISTING" items were already present and verified by tests.

Legend: EXISTING · PARTIAL (improved this pass where noted) · NEW (this pass) · BLOCKED (external validation required) 

## Core model & protocols
- Protocol v2 normalized model, stable entity IDs, canonical hashes, artifact migration — EXISTING (`core/model_v2.py`)
- Swagger 2.0 import with loss warnings; AsyncAPI adapter foundation; bundles + catalog index; ownership mapping — EXISTING
- OpenAPI 3.0/3.1 deepening (callbacks/webhooks/discriminators/security inheritance) — PARTIAL (parser-level support; compat coverage for callbacks is partial)
- JSON Schema 2020-12-aware comparisons — PARTIAL (shared SchemaNode semantics; `$dynamicRef` not modeled)
- GraphQL SDL import with provenance — EXISTING loader; **fixed this pass**: kind-casing bug that silently loaded zero operations
- gRPC descriptor import — EXISTING; wire-compat metadata NEW (`diff/protocol_compat.py`)
- SSE / WebSocket message-contract representations — EXISTING (operation kinds `EVENT`, `WS_MESSAGE`)

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
- Workflow engine v2 (extraction/guards/cleanup), graph validation, templates, model-based CRUD — EXISTING
- Workflow inference from OpenAPI Links — PARTIAL (safe deterministic subset)

## Runtime: drift, replay, performance
- Drift monitor, baselines/trends, field-frequency analysis, HAR normalization with redaction DSL, replay manifests/dry-run/destructive gate — EXISTING
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
- 31-page product UI (public/local + team pages), themes, virtualized tables, DEMO labeling, demo corpus generator — EXISTING (landed this pass as commit series)

## Deliberately not pursued
See `PRODUCT_GAPS.md` ("Features deliberately not pursued").
