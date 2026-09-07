# Changelog

All notable changes. Format based on Keep a Changelog; versions are semver.

## [Unreleased]

### Fixed
- **Console script entry point** pointed at a nonexistent symbol
  (`apiverity.cli.main:cli`); installing the package produced an `apiverity`
  command that crashed with ImportError. Now `apiverity.cli.main:main`.
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
- ARCHITECTURE.md incorrectly described the CLI as Click-based; it is
  argparse-based (doc drift).

### Changed
- Frontend restructured from a single-file app into `components/`, `hooks/`
  and domain-grouped `pages/` modules (`overview`, `contract`, `testing`,
  `runtime`, `team`) with a central page registry — same behavior, now
  maintainable and code-split-ready.
- CLI split into `apiverity/cli/commands/` grouped by product lane
  (`common`, `governance`, `testing`, `runtime`, `artifacts`, `platform`);
  `apiverity.cli.main` remains the stable entry point and re-exports all
  command functions.
- Server store schema extracted into `apiverity/server/schema.py` (DDL,
  timestamp/token helpers) and can-i-deploy / auth-fallback logic into
  `apiverity/server/decision.py`; `Store` and `create_app` keep their public
  signatures and `apiverity.server.api` re-exports the moved helpers.
- Tests organized into `tests/unit/` (pure logic) and `tests/integration/`
  (mock server + self-hosted API over live HTTP); CI coverage floor raised
  from 60% to 72% (current measured coverage: 76%).
- pre-commit ruff hook bumped to v0.16.4 to match the ruff version used for
  formatting in CI; removed dead `_start_mock` helper and stray one-off
  maintenance script.

### Added
- Release engineering: tag-triggered GitHub Actions release workflow with
  PyPI trusted publishing (OIDC, no stored tokens), signed-off GitHub
  Releases with distribution artifacts, and a GHCR container image for the
  self-hosted server; repo ships a hardened non-root `Dockerfile`
  (healthcheck on `/healthz`, volume-backed SQLite storage) plus
  `.dockerignore`.
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
