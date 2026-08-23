# Competitive Analysis — API Verity Lab

Generated: 2026-08-23 · Evidence: live GitHub API metadata (see `data/competitor-meta.json`) + documented product models. Full machine-readable matrix: `data/competitive-capabilities.json`.

## Method

- Repo license, stars, last push, archived status and latest release fetched **live on 2026-08-23** via the authenticated GitHub API for every competitor.
- Qualitative capability claims are labeled VERIFIED (fetched metadata / official docs quotes) or KNOWLEDGE-BASED (documented product understanding).
- No competitor is claimed to *lack* a feature without verification; unverified areas are `unknown`.

## Landscape snapshot (verified 2026-08-23)

| Tool | License | Stars | Last push | Latest release | Status |
|---|---|---|---|---|---|
| oasdiff | Apache-2.0 | 1,327 | 2026-08-23 | v1.29.1 (2026-08-16) | active |
| Schemathesis | MIT | 3,554 | 2026-08-23 | v4.25.0 (2026-08-20) | active |
| Spectral | Apache-2.0 | 3,186 | 2026-08-19 | v6.16.3 (2026-08-03) | active |
| Pact (pact-js) | MIT-family | 1,801 | 2026-08-21 | v17.1.2 (2026-08-11) | active |
| Optic | — | — | — | — | repo gone (404) |
| Dredd | MIT | 4,222 | 2024-05-11 | dredd@14.1.0 (2021) | **archived** |
| Prism | Apache-2.0 | 5,012 | 2026-08-13 | v5.16.0 (2026-07-17) | active |
| WireMock | Apache-2.0 | 7,342 | 2026-08-21 | 3.13.2 (2025-11-14) | active |
| Hoverfly | Apache-2.0 | 2,507 | 2026-08-19 | v1.12.11 (2026-08-05) | active |
| Karate | MIT | 8,925 | 2026-08-23 | v2.1.2 (2026-08-14) | active |
| k6 | AGPL-3.0 | 31,299 | 2026-08-23 | v2.2.0 (2026-08-10) | active |
| Newman | Apache-2.0 | 7,246 | 2026-08-05 | no release object | maintenance mode |
| GraphQL Inspector | MIT | 1,759 | 2026-08-20 | rolling release | active |
| Buf | Apache-2.0 | 11,378 | 2026-08-23 | v1.72.0 (2026-07-17) | active |

## What each one owns

- **oasdiff** — OpenAPI diff + breaking changes. Focused, fast, healthy. Nothing else.
- **Schemathesis** — schema-driven fuzzing, response validation, stateful testing via links, failure minimization. The fuzzing bar.
- **Spectral** — the linting/ruleset standard (OpenAPI/Arazzo/AsyncAPI v2 rulesets).
- **Pact (+PactFlow)** — consumer-driven contracts, provider verification, broker publication, `can-i-deploy`. The deploy-decision bar. Collaboration = self-hostable OSS Broker; RBAC/SSO in commercial PactFlow.
- **Prism** — spec-accurate mock server with request validation.
- **WireMock / Hoverfly** — service virtualization: stubbing, scenarios/state, record-replay, fault injection. JVM-centric (WireMock) / proxy-centric (Hoverfly). Cloud/Team layers are hosted-commercial.
- **Karate** — broad test automation DSL incl. mocks and Gatling-based perf.
- **k6** — load engine + thresholds (= budgets). AGPL core; Grafana Cloud commercial.
- **Newman/Postman** — collection runner; collaboration/mocks/monitors locked to hosted platform.
- **GraphQL Inspector** — reference GraphQL breaking/dangerous taxonomy, schema coverage. Hive console is the hosted layer.
- **Buf** — gold-standard protobuf lint/breaking (wire semantics); BSR registry is hosted-first.
- **Dredd/Optic** — archived/gone; instructive history only.

## Capability matrix

See `data/competitive-capabilities.json` for the full 25-dimension × 14-tool matrix with per-cell evidence notes. Highlights:

- **Drift detection**: not a documented focus area for any listed competitor → open niche.
- **Safety-gated replay w/ redaction**: WireMock/Hoverfly do record-replay but without contract-aware safety gating or redaction DSL → differentiable.
- **can-i-deploy over plain specs**: only Pact offers it, requiring its broker worldview → offering it over OpenAPI/GraphQL/gRPC contracts lowers adoption cost.
- **Unified frontend**: most OSS cores are CLI-only; rich UIs sit behind hosted products.

## Strategic conclusions for API Verity Lab

1. **The shared model is the moat.** One normalized contract graph feeding diff → breaking rules → generators → workflows → runtime → drift/perf → results → deploy decisions is something no single-lane tool provides.
2. **Match specialist depth where cheap, integrate always.** e.g., our fuzzing should be deterministic and CI-friendly (a Schemathesis complement, not clone); protobuf rules should adopt Buf's wire-compat categories conceptually.
3. **Own the uncontested niches**: drift baselines/trends, redaction-proven traffic corpora, replay dry-runs and destructive-method gates, contract-aware performance budgets.
4. **Licensing**: stay Apache-2.0. Community keeps full local capability; team/enterprise value comes from the self-hosted server (collaboration, policy-as-code, audit, workers) — the same layer competitors gate behind hosted products. No non-commercial restrictions.
5. **Do not copy**: hosted-only lock-in, AGPL constraints, JVM-centrism, or features of dead tools.

## Deliberately not copied

- Hosted-only collaboration (Postman/Hive/BSR model) — we ship a self-hosted server instead.
- k6's scripting language/AGPL — we use declarative profiles + budgets.
- WireMock's hand-authored stub DSL — our virtualization derives from contracts.
- Browser recorder ecosystems — out of scope by design.