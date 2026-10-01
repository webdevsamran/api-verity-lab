---
description: >-
  How api-verity-lab compares with oasdiff, Schemathesis, Spectral, Pact, Prism, WireMock, Karate, k6 and Buf, rendered from dated GitHub API evidence.
---

# Competitive Analysis — API Verity Lab

<!-- generated:provenance -->
Generated: 2026-10-01 · Evidence: live GitHub API metadata (see `data/competitor-meta.json`) + documented product models. Full machine-readable matrix: `data/competitive-capabilities.json`.
<!-- /generated:provenance -->

## Method

<!-- generated:method -->
- Repo license, stars, last push, archived status and latest release fetched **live on 2026-10-01** via the authenticated GitHub API for every competitor.
<!-- /generated:method -->
- Qualitative capability claims are labeled VERIFIED (fetched metadata / official docs quotes) or KNOWLEDGE-BASED (documented product understanding).
- No competitor is claimed to *lack* a feature without verification; unverified areas are `unknown`.
- The numbers above are what these projects looked like **on the date named**,
  and that stays true however old it gets. What decays is usefulness: a rival's
  star count and last release from eighteen months ago are accurate history and
  a misleading comparison, and this page cannot tell you which you are reading.
  So a scheduled job re-fetches monthly and opens a pull request when anything
  moved, `generate_competitive_table.py` prints the evidence's age on every run,
  and `--max-age-days` fails when it passes a quarter. That check is not in the
  pull-request gate on purpose: blocking an unrelated contributor because a
  quarter rolled over punishes the wrong person and gets the check deleted.

<!-- generated:landscape -->
## Landscape snapshot (verified 2026-10-01)

| Tool | License | Stars | Last push | Latest release | Status |
|---|---|---|---|---|---|
| oasdiff | Apache-2.0 | 1,398 | 2026-10-01 | v1.32.1 (2026-09-15) | active |
| Schemathesis | MIT | 3,643 | 2026-10-01 | v4.28.0 (2026-09-22) | active |
| Spectral | Apache-2.0 | 3,220 | 2026-10-01 | v6.17.0 (2026-10-01) | active |
| Pact (pact-js) | NOASSERTION | 1,817 | 2026-10-01 | v17.1.4 (2026-09-07) | active |
| Optic | MIT | 1,533 | 2026-01-08 | v1.0.9 (2025-08-10) | **archived** |
| Dredd | MIT | 4,223 | 2024-05-11 | dredd@14.1.0 (2021-11-16) | **archived** |
| Prism | Apache-2.0 | 5,047 | 2026-10-01 | v5.16.0 (2026-07-17) | active |
| WireMock | Apache-2.0 | 7,386 | 2026-09-29 | 3.13.2 (2025-11-14) | active |
| Hoverfly | Apache-2.0 | 2,523 | 2026-09-28 | v1.12.15 (2026-09-21) | active |
| Karate | MIT | 8,972 | 2026-10-01 | v2.1.3 (2026-09-27) | active |
| k6 | AGPL-3.0 | 31,739 | 2026-10-01 | v2.3.0 (2026-09-21) | active |
| Newman | Apache-2.0 | 7,256 | 2026-09-30 | — | active |
| GraphQL Inspector | MIT | 1,768 | 2026-10-01 | release-1790861621711 (2026-10-01) | active |
| Buf | Apache-2.0 | 11,468 | 2026-09-30 | v1.73.0 (2026-09-11) | active |
<!-- /generated:landscape -->

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
- **Dredd** — archived (last push 2024-05-11); instructive history only.
- **Optic** — archived 2026-01 at 1,534 stars, in precisely this domain. An
  earlier revision of this file recorded it as "repo gone (404)". It is not
  gone: `opticdev/optic` is archived and public. The 404 came from this
  repository's own fetcher asking for `useoptic/optic`, which does not
  exist, and the null being written into the table as a finding. Fixed at
  the source -- the fetcher now raises on a failed lookup instead of
  recording it as data.

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
