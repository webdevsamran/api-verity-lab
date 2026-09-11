# Product Gaps — justified by competitor evidence

Derived from `docs/competitive-analysis.md` / `data/competitive-capabilities.json` (evidence dated 2026-08-23).

## Gaps API Verity Lab closes that competitors leave open

1. **Runtime drift detection** (`apiverity drift`) — declared spec vs authorized runtime behavior, with baselines/trends. No compared tool documents this as a focus area.
2. **Safety-gated traffic replay** — replay manifests, dry-run previews, destructive-method allowlists, redaction-proven corpora. WireMock/Hoverfly record-replay without contract-aware safety gating or redaction DSL.
3. **can-i-deploy over plain contracts** — Pact requires its consumer-contract worldview; we derive deploy decisions from OpenAPI/GraphQL/gRPC contracts + verifications directly.
4. **Unified workflow across lanes** — diff → breaking → generate → test → drift → perf → decision on one shared contract/result model. Every competitor is single-lane.
5. **Contract-aware performance budgets** — k6 has generic thresholds; nobody ties budgets/regressions to operations and contract versions.
6. **Multi-protocol governance under one rule engine** — Spectral (HTTP lint), Buf (protobuf), GraphQL Inspector (GraphQL) each own one protocol's semantics; none share an engine or result format.
7. **Deterministic local-first fuzz corpus management** — seeded generation, shrinking, corpus export/import for CI regression replay (Schemathesis is close but hosted reports are the collaboration path).
8. **Self-hosted team layer without cloud lock-in** — orgs/RBAC/audit/policy/workers as OSS you can run yourself; competitors gate these behind hosted products (PactFlow, BSR, Hive, Postman).
9. **Expiring suppressions & deprecation lifecycle policy** — permanent ignore-files are the norm elsewhere; ownership/expiry metadata prevents silent rot.
10. **Consumer registry + impact mapping over normalized operations** — connects breaking changes to registered consumers without adopting a new contract format.

## Gaps this project has, and what closing them needs

Listed for the same reason the competitive table is generated rather than
typed: a gap nobody wrote down is a gap that gets described as shipped.

1. **PyPI** — `pip install api-verity-lab` does not work. The release workflow
   is wired for OIDC trusted publishing and guarded behind `PUBLISH_ENABLED`;
   registering a Trusted Publisher is a form on the PyPI account that owns the
   name and cannot be done from a repository. One step by an account owner
   unlocks `pipx`, `uvx` and `pip` at once. See `docs/install.md`.
2. **Homebrew, Scoop, winget** — these want a self-contained executable, and
   `apiverity` is a Python package with real dependencies. Serving them honestly
   needs either a per-platform frozen binary with its own test matrix, or a
   Homebrew formula carrying a checksummed `resource` block per dependency,
   regenerated on every bump. Neither exists, so neither is published: a formula
   that has never been installed is a claim.
3. **Framework adapters beyond Python** — `apiverity app module:attribute` reads
   the document a Python application object produces. Express, NestJS, Laravel,
   Spring and gin each already have a maintained OpenAPI generator, so the
   adapter for them is a shell pipeline rather than code here. `docs/framework-adapters.md`
   gives the table and the reasoning.

## Features deliberately not pursued

- Hosted SaaS collaboration platform (Postman/Hive/BSR model) — self-hosted server instead.
- Browser/UI test automation (Karate territory).
- Scripting-language load engine (k6 territory) — declarative load shapes (`regression --shape 'ramp:60s@1..20'`, open loop, Poisson arrivals optional) plus budgets and concurrency curves.
- Hand-authored stub DSLs (WireMock territory) — virtualization derives from contracts (`mock --workspace`: several services, one seed, one address table).
- API Blueprint support (Dredd legacy, archived).