# Architecture

api-verity-lab is a **local-first API reliability laboratory**. It unifies
contract governance, breaking-change analysis, schema-driven testing, runtime
drift detection, traffic replay and performance regression behind one data
model, one CLI, one result format, one plugin system and one frontend.

## Design principles

1. **One normalized contract model.** Every supported spec format (OpenAPI,
   GraphQL SDL, protobuf) is compiled into a single internal model with
   preserved source locations. All downstream engines operate on this model,
   never on raw spec documents.
2. **Versioned artifacts everywhere.** Every command emits a versioned result
   artifact (`result-v1`) carrying tool version, contract hash, seed, timing,
   findings and redaction state. Artifacts are stable inputs for CI gates,
   bundles and the frontend.
3. **Safety by default.** Explicit targets only; localhost-only mock;
   centralized redaction; production replay opt-in; no auto-generated
   destructive workflows.
4. **Plugin-first extensibility.** Six entry-point groups with versioned
   contracts: `apiverity.specs`, `apiverity.rules`, `apiverity.checks`,
   `apiverity.generators`, `apiverity.exporters`, `apiverity.transports`.
5. **Determinism.** Case generation is seeded; identical inputs produce
   byte-identical artifacts (modulo timing fields).

## Module map

```
apiverity/
├── core/          Normalized contract model + source locations + hashing
├── specs/         Spec plugins: openapi/, graphql/, grpc/ → core model
├── diff/          Semantic differ producing stable change IDs
├── rules/         Breaking rules (direction-aware), semver policy, security checks
├── fuzz/          Schema-driven deterministic case generation + minimization
├── stateful/      Workflow engine (YAML manifests, extraction, assertions)
├── traffic/       HAR/log import + central redaction pipeline
├── runtime/       Drift detection: declared contract vs actual responses
├── mock/          Deterministic localhost mock server with fault modes
├── performance/   Budgets, percentiles, baselines, regression gates
├── reports/       terminal/json/yaml/markdown/junit/sarif/html reporters
├── exporters/     .apiverity bundle writer with checksums
├── plugins/       Plugin loader + versioned plugin API protocols
├── security/      Defensive security checks + rule packs
├── server/        Self-hosted Flask monolith: api.py (route factory),
│                  store.py (SQLite persistence), schema.py (DDL + helpers),
│                  decision.py (can-i-deploy), auth/jobs/webhooks
└── cli/           argparse-based CLI: parser in main.py, implementations in
                    commands/ grouped by lane (governance, testing, runtime,
                    artifacts, platform) with shared plumbing in commands/common
```

## Data flow

```
                 ┌─────────────┐
  OpenAPI ──────▶│             │
  GraphQL ──────▶│ specs/*     │──▶ Contract (normalized model)
  proto    ──────▶│             │        │
                 └─────────────┘        ▼
                              ┌──────────────────┐
   old.yaml + new.yaml ──────▶│ diff/            │──▶ DiffResult (changes)
                              └──────────────────┘        │
                                                          ▼
                              ┌──────────────────┐   BreakingResult
                              │ rules/breaking   │◀── (findings)
                              │ rules/semver     │──▶ SemverResult
                              └──────────────────┘
Contract ─▶ fuzz/generators ─▶ TestCases ─▶ runner ─▶ TestResult
Workflow YAML ─▶ stateful/engine ─▶ WorkflowResult
HAR/logs ─▶ traffic/redact ─▶ corpus ─▶ runtime/drift ─▶ DriftFinding
Budgets ─▶ performance/harness ─▶ PerformanceResult vs baseline
All results ─▶ reports/* ─▶ terminal/JSON/YAML/MD/JUnit/SARIF/HTML
All results ─▶ exporters/bundle ─▶ .apiverity bundle (checksummed)
Bundles ─▶ cli serve / web frontend
```

## The normalized contract model

Core entities (see `apiverity/core/model.py`):

| Entity            | Purpose                                                        |
|-------------------|----------------------------------------------------------------|
| `Service`         | Top-level container: title, version, protocol, servers         |
| `Operation`       | method+path (HTTP), field (GraphQL), RPC (gRPC)                |
| `Parameter`       | path/query/header/cookie parameters                            |
| `RequestBody`     | content-type keyed bodies                                      |
| `Response`        | status-keyed responses with headers and schemas                |
| `SchemaNode`      | Recursive JSON-Schema-like type tree                           |
| `SecurityScheme`  | auth declarations                                              |
| `SourceLocation`  | file + line/column for precise findings                        |
| `Example`         | named examples per media type                                  |

Every entity carries a `source_location` so findings can link to the exact
line in the original spec.

## Change identity

Diff changes get **stable IDs**: `CHG-{kind}-{operation-hash}-{index}` where
the operation hash is derived from the canonical operation key
(`METHOD /path` or GraphQL type.field). IDs survive reordering of spec
documents but intentionally change when the underlying change moves to a
different operation.

## Direction-aware compatibility

Breaking rules distinguish **request** from **response** compatibility:

- Removing an optional request parameter → safe.
- Making a request parameter required → breaking (ERROR).
- Adding a new response field → safe (consumers ignore unknown fields).
- Removing a response field → breaking (ERROR).
- Narrowing a response enum → risky (WARN); narrowing a request enum →
  breaking for clients that send old values (ERROR).
- Type widening in a response → WARN; type narrowing in a request → ERROR.

The full catalog lives in `docs/rules.md` and is introspectable via
`apiverity rules`.

## Result artifact schema

All artifacts conform to `schemas/result-v1.schema.json`:

```jsonc
{
  "artifact": "diff | breaking | test | workflow | drift | replay | performance",
  "artifact_version": "1",
  "tool_version": "0.1.0",
  "protocol": "openapi | graphql | grpc",
  "contract_hash": "sha256:...",
  "target": { "base_url": "...", "environment": "..." },
  "seed": 42,
  "timing": { "started_at": "...", "duration_ms": 123 },
  "redaction": { "enabled": true, "rules_applied": ["..."] },
  "findings": [ /* Finding objects */ ],
  "summary": { /* artifact-specific */ }
}
```

## Bundles

`.apiverity` bundles are directories containing `result.json`, the contract
snapshot + hash, config, sanitized failing cases, workflow manifests,
performance summary and a `CHECKSUMS` manifest — everything needed to review
a run offline via `apiverity serve` or the web UI.

## Prior art & credit

This project is an independent implementation. Design inspiration was drawn
from (and credit is due to):

- **oasdiff / openapi-diff** — spec diffing problem framing
- **Schemathesis** — property/schema-driven API testing
- **Dredd** — contract-testing workflow shape
- **Spectral** — rule-catalog linting architecture
- **Tavern / Karate** — declarative workflow authoring
- **HAR 1.2 specification** — traffic interchange format
- **SARIF 2.1.0 (OASIS)** — static-analysis result interchange

No code is copied from these projects; the unified data model, drift engine,
performance budgets, bundle format and frontend are original to this project.

## Frontend

`web/` is a React 18 + TypeScript + Vite SPA consuming only real generated
fixture data (produced by running the bundled example APIs through the CLI).
It renders diff reviews, breaking-change cards, test runs, drift tables,
latency charts and coverage charts, with shareable filter URLs and
downloadable reports. See `web/README.md`.