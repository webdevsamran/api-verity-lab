# Changelog

All notable changes. Format based on Keep a Changelog; versions are semver.

## [Unreleased]

### Fixed
- GraphQL spec plugin silently loaded **zero operations** from valid SDL:
  graphql-core node kinds are snake_case (`object_type_definition`) while the
  loader compared camelCase strings. Root-type fields now normalize correctly
  and are covered end-to-end by tests.
- Whole-contract compatibility findings (`diff/compat`) were computed but
  never surfaced by `apiverity breaking`; they are now merged into the report.
- Demo data loading cached failed fetches permanently in the frontend;
  failures now retry on next load.
- CI dependency audit no longer hides failures behind `|| true`.
- Lint/format drift under ruff 0.16 normalized; pytest-asyncio loop-scope
  configured explicitly.

### Added
- Protocol-aware compatibility analysis: GraphQL breaking rules plus a
  distinct *dangerous-change* category (field additions, return-type
  relaxation); gRPC/protobuf wire-compatibility rules (RPC removal, message
  type swaps, scalar wire-type changes, integer-width changes, enum-value
  removal). Wired into `apiverity breaking`.
- GraphQL loader captures return types so nullability evolution is analyzable.
- Self-hosted server: worker enrollment (`POST /v1/workers`), pull-based job
  queue with idempotency keys and backpressure (`POST /v1/jobs`,
  `/v1/jobs/claim`), SSE run progress (`GET /v1/runs/<id>/events`),
  backup/restore/export/import (`Store.backup_to/restore_from/export_org/
  import_org`, CLI `apiverity server-db`), fixed-window API rate limiting,
  new Prometheus counters (jobs enqueued/rejected, rate-limited).
- Opt-in OTLP/JSON trace export with mandatory attribute redaction
  (`apiverity.exporters.otel`).
- Docs: PROTOCOL_SUPPORT.md (verified levels per protocol), SAFETY_MODEL.md,
  capability status matrix, self-hosting guide.

## [0.1.0]
Initial public release: contract diffing, direction-aware breaking rules,
semver policy, schema-driven testing with shrinking, stateful workflows,
deterministic mock server, coverage, drift detection, HAR redaction,
safety-gated replay, performance baselines/regression gates, reporters
(JSON/YAML/Markdown/JUnit/SARIF/HTML), GitHub Action, React frontend.
