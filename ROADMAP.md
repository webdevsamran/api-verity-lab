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

## v0.2 — Deepening

- 📋 GraphQL fuzzing: argument-level case generation from SDL
- 📋 gRPC reflection-based drift checks against live servers
- 📋 AsyncAPI spec plugin
- 📋 Workflow inference from explicit OpenAPI link objects
- 📋 Drift over recorded traffic corpora at scale (streaming)
- 📋 Performance: soak profiles, per-endpoint concurrency curves
- 📋 Coverage: security-scheme exercise matrix in HTML report

## v0.3 — Ecosystem

- 📋 VS Code extension for inline breaking-change review
- 📋 SARIF ingestion into GitHub Code Scanning UI (first-class)
- 📋 Plugin marketplace documentation + example plugin repo
- 📋 OpenTelemetry trace correlation for drift findings
- 📋 Multi-contract aggregation reports (monorepo mode)

## Known v0.1 limitations

- GraphQL/gRPC are foundations: loading + structural diffing only;
  testing/fuzzing parity with OpenAPI is a v0.2 goal.
- Performance measurement is sequential; concurrency curves arrive in v0.2.
- Workflow graph rendering is tabular (step list) rather than a visual DAG.

## Non-goals

- No hosted/cloud service; api-verity-lab stays local-first.
- No exploit payload libraries or offensive security tooling.
- No unrestricted interception proxy by default.

This roadmap is synced with reality each release; see the issue tracker for
the live backlog.