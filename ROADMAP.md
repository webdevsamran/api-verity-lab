# Roadmap

Status legend: ✅ shipped · 🚧 in progress · 📋 planned

## v0.1 — Foundations (current release)

- ✅ Normalized contract model with source locations
- ✅ OpenAPI 3.0/3.1 spec plugin (files + URLs), ref/validation findings
- ✅ Semantic diff with stable change IDs
- ✅ Direction-aware breaking rules catalog (ERROR/WARN/INFO)
- ✅ Semver policy engine
- ✅ Changelog generation (Markdown/HTML)
- ✅ Schema-driven test generation + failure minimization
- ✅ Stateful workflow engine (YAML manifests)
- ✅ Deterministic mock server with fault modes
- ✅ Contract coverage measurement
- ✅ Runtime drift detection
- ✅ HAR import + central redaction
- ✅ Sanitized replay with allowlists and production opt-in
- ✅ Performance budgets, baselines, regression gates
- ✅ Defensive security contract checks
- ✅ Auth profiles (env-referenced, never persisted)
- ✅ GraphQL foundation (load + structural diff)
- ✅ gRPC foundation (proto load + RPC/field-number checks)
- ✅ Versioned result artifacts + .apiverity bundles
- ✅ Full CLI (18 commands) with JSON output + stable exit codes
- ✅ Typed SDK surface
- ✅ Plugin system (6 entry-point groups)
- ✅ Reporters: terminal/JSON/YAML/Markdown/JUnit/SARIF/HTML
- ✅ React+TS frontend with all 15 pages (Home, Contract Explorer, Diff
  Review, Breaking Changes, Rules, Test Runs, Fuzz Failures, Workflows,
  Runtime Drift, Performance, Coverage, Result Detail, Docs,
  Contributors, About) on real generated fixture data
- ✅ `apiverity serve` local bundle server
- ✅ Reusable GitHub Action / PR summary experience (single non-spammy
  comment, updated on push; validate/diff/breaking/semver gate)
- ✅ Deterministic fixture APIs + integration tests

## v0.2 — Deepening (second transformation pass, 2026-08-26)

- ✅ Protocol-aware compatibility: GraphQL breaking rules + dangerous-change category; gRPC wire-compat rules; whole-contract HTTP compat findings surfaced by `apiverity breaking`
- ✅ GraphQL loader FIXED (kind-casing bug silently loaded zero operations); return types captured for nullability analysis
- 📋 GraphQL fuzzing: argument-level case generation from SDL
- 📋 AsyncAPI message/channel compatibility rules
- 📋 Workflow inference from explicit OpenAPI link objects (safe subset done)
- 📋 Shadow contract inference from sanitized traffic corpora
- 📋 Response-size/bandwidth metrics, TLS timing breakdown

## v0.2-server — Self-hosted team/enterprise layer

- ✅ Worker enrollment + pull-based job queue (idempotency keys, backpressure)
- ✅ SSE run progress streaming (`GET /v1/runs/<id>/events`)
- ✅ Backup/restore/export/import incl. `apiverity server-db`
- ✅ API rate limiting + job/rate-limit Prometheus counters
- ✅ Opt-in redacted OTLP trace export
- 📋 Concrete OIDC/SAML providers (IdentityProvider protocol exists; needs a real IdP)
- 📋 Per-operation consumer registry over the existing can-i-deploy data

## v0.3 — Ecosystem

- 📋 VS Code extension for inline breaking-change review
- 📋 SARIF ingestion into GitHub Code Scanning UI (first-class)
- 📋 Plugin marketplace documentation + example plugin repo
- 📋 OpenTelemetry trace correlation for drift findings
- 📋 Multi-contract aggregation reports (monorepo mode)

## Known limitations

- GraphQL/gRPC testing parity with OpenAPI is partial: conformance harnesses
  exist as interfaces; live validation needs real servers (BLOCKED).
- Performance measurement is sequential; concurrency curves arrive in v0.2.
- Workflow graph rendering is tabular (step list) rather than a visual DAG.

## Non-goals

- No hosted/cloud service; api-verity-lab stays local-first.
- No exploit payload libraries or offensive security tooling.
- No unrestricted interception proxy by default.

This roadmap is synced with reality each release; see the issue tracker for
the live backlog.