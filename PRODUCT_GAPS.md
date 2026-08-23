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

## Features deliberately not pursued

- Hosted SaaS collaboration platform (Postman/Hive/BSR model) — self-hosted server instead.
- Browser/UI test automation (Karate territory).
- Scripting-language load engine (k6 territory) — declarative profiles + budgets.
- Hand-authored stub DSLs (WireMock territory) — virtualization derives from contracts.
- API Blueprint support (Dredd legacy, archived).