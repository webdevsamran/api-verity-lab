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
- ✅ Full CLI with JSON output and stable exit codes. The command count is not
  written here: it is in `docs/capabilities.json`, generated from the parser,
  because it has been wrong in prose twice
- ✅ Typed SDK surface
- ✅ Plugin system (6 entry-point groups)
- ✅ Reporters: terminal/JSON/YAML/Markdown/JUnit/SARIF/HTML
- ✅ React+TS frontend with 33 routes across six page groups (Overview,
  Contract, Testing, Runtime, Agents, Team) on real generated fixture data.
  Both counts are derived from `web/src/pages/index.tsx` and pinned by
  `tests/unit/test_frontend_page_count.py`
- ✅ `apiverity serve` local bundle server
- ✅ Composite GitHub Action (`action.yml`) and a reusable workflow. Both
  exist because they are consumed differently: the action is a step in a job
  you own, the workflow is a whole job that brings the single non-spammy PR
  comment. validate/diff/breaking/semver gate either way
- ✅ Deterministic fixture APIs + integration tests

## v0.2 — Deepening (second transformation pass, 2026-08-26)

- ✅ Protocol-aware compatibility: GraphQL breaking rules + dangerous-change category; gRPC wire-compat rules; whole-contract HTTP compat findings surfaced by `apiverity breaking`
- ✅ GraphQL loader FIXED (kind-casing bug silently loaded zero operations); return types captured for nullability analysis
- 📋 GraphQL fuzzing: argument-level case generation from SDL
- 📋 AsyncAPI message/channel compatibility rules
- 📋 Workflow inference from explicit OpenAPI link objects (safe subset done)
- ✅ Shadow contract inference from sanitized traffic corpora (`apiverity infer`)
- 📋 Response-size/bandwidth metrics, TLS timing breakdown

## v0.2-server — Self-hosted team/enterprise layer

- ✅ Worker enrollment + pull-based job queue (idempotency keys, backpressure)
- ✅ SSE run progress streaming (`GET /v1/runs/<id>/events`)
- ✅ Backup/restore/export/import incl. `apiverity server-db`
- ✅ API rate limiting + job/rate-limit Prometheus counters
- ✅ Opt-in redacted OTLP trace export
- 📋 Concrete OIDC/SAML providers (IdentityProvider protocol exists; needs a real IdP)
- ✅ Per-operation consumer registry and blast radius
  (`breaking --consumers`), with softening gated behind a registry that
  declares itself complete

## v0.3 — Agent governance (third pass, 2026-09-10)

The wager: static MCP manifest diffing is already claimed by several
published packages, so it ships here as table stakes and is never the
headline. Declared-versus-live drift and fleet posture were open, and that is
what this pass built.

- ✅ MCP tool manifests as the sixth contract format, diffed by the shared
  rules
- ✅ Declared-versus-live drift over Streamable HTTP, plus spec conformance
  against a server with no manifest at all
- ✅ Tool-description poisoning and annotation integrity (OWASP MCP03), run as
  part of `validate`
- ✅ Authentication posture: what a server hands a caller with no credential
- ✅ Shadow servers, from client configuration rather than a network scan
- ✅ `mcp.lock`: a reviewed baseline for a tool surface, with a version that
  lives in the file you own because the protocol has nowhere for one
- ✅ Call budgets with sliding windows
- ✅ Credential scanning of responses and tool results, reported without ever
  recording the credential
- ✅ OWASP MCP / Agentic / API Top 10 mapping, with the controls this tool
  cannot assess named rather than omitted
- ✅ Evidence packs for SOC 2, ISO 42001, DORA and the EU AI Act: records, not
  verdicts
- ✅ Ghost routes: what the contract deleted and the deployment kept
- ✅ A non-breaking alternative published for every rule
- ✅ Agent-governance pages in the dashboard, on data a real run produced

## v0.4 — Ecosystem

- 📋 VS Code extension for inline breaking-change review
- 📋 SARIF ingestion into GitHub Code Scanning UI (first-class)
- 📋 Plugin marketplace documentation + example plugin repo
- 📋 OpenTelemetry trace correlation for drift findings, and the GenAI
  semantic conventions
- 📋 Arazzo workflow import/export; GraphQL federation; SOAP/WSDL
- 📋 Live-traffic capture (proxy/sidecar) — the interface is specified,
  the socket work is not done
- ✅ Multi-contract aggregation with CODEOWNERS-derived ownership
  (`apiverity sweep`, `--base` for a whole-repo breaking verdict)

## Known limitations

- GraphQL/gRPC testing parity with OpenAPI is partial: conformance harnesses
  exist as interfaces; live validation needs real servers (BLOCKED).
- Performance measurement is sequential; concurrency curves are not built.
- Consumer impact is per operation, not per field: a `Change` carries a field
  name only inside a human-readable description, so attributing a removed
  response field to whoever reads *that field* would mean parsing a message.
- `pip install api-verity-lab` does not work. Publishing is wired through
  OIDC and gated behind a `PUBLISH_ENABLED` repository variable that has never
  been set, which also blocks `uvx` and `pipx`. This needs the maintainer's
  PyPI account, not a code change.
- Workflow graph rendering is tabular (step list) rather than a visual DAG.

## Non-goals

- No hosted/cloud service; api-verity-lab stays local-first.
- No exploit payload libraries or offensive security tooling.
- No unrestricted interception proxy by default.

This roadmap is synced with reality each release; see the issue tracker for
the live backlog.