# Capability Status

Honest classification of the transformation target list against the actual
codebase (audited 2026-09-10). "NEW" items below were implemented in this
pass; "EXISTING" items were already present and verified by tests.

Legend: EXISTING · PARTIAL (improved this pass where noted) · NEW (this pass) · BLOCKED (external validation required) 

## Core model & protocols
- Protocol v2 normalized model, stable entity IDs, canonical hashes, artifact migration — EXISTING (`core/model_v2.py`)
- Swagger 2.0 import with loss warnings; bundles + catalog index; ownership mapping — EXISTING
- AsyncAPI 2.x and 3.x adapter, registered under `apiverity.specs` — EXISTING (`specs/asyncapi.py`); direction normalized to the application's point of view so a 2.x document and its 3.x migration compare as equivalent
- OpenAPI 3.0/3.1 deepening (callbacks/webhooks/discriminators/security inheritance) — PARTIAL (parser-level support; compat coverage for callbacks is partial)
- OpenAPI 3.2.0 (released 2025-09-19): the `query` method, `additionalOperations`
  for verbs the specification does not name, the `querystring` parameter
  location, hierarchical tags (`summary`/`parent`/`kind`) with a dangling-parent
  finding, the OAuth `deviceAuthorization` flow and `oauth2MetadataUrl` — all
  loaded into the shared model, so the existing direction-aware rules govern
  them. Fixed alongside: `SecurityScheme.scopes` was declared by the model and
  never populated, so scope coverage had no data for any contract in any
  version — EXISTING (`specs/openapi/parser.py`)
- JSON Schema 2020-12-aware comparisons — PARTIAL (shared SchemaNode semantics; `$dynamicRef` not modeled)
- Canonicalization before diffing (`core/canonical.py`): `allOf` collapsed where
  it can be collapsed without deciding anything, enums deduplicated and ordered,
  properties and `required` sorted. Conjunction semantics are honoured —
  constraints merge to the tightest bound, enums intersect. Branches that
  disagree are left composed and reported (`SPEC-ALLOF-CONFLICT`) rather than
  merged, and `oneOf`/`anyOf` are never flattened because a disjunction is not a
  conjunction. Applied in `diff_services`, not at load, so `validate` still
  reports on the document as written — EXISTING
- GraphQL: SDL import with provenance (**fixed in an earlier pass**: a kind-casing bug that silently loaded zero operations), schema-driven query generation, persisted operation documents (`test --operations`), `{data, errors}` envelope assertions, and introspection-based drift (`drift --base-url`) — EXISTING (`specs/graphql/operations.py`, `specs/graphql/runner.py`)
- gRPC: `.proto` sources and compiled `FileDescriptorSet` input (`.desc`/`.pb`/`.protoset`) — EXISTING (`specs/grpc/descriptor.py`, no protobuf runtime dependency); streaming cardinality, explicit presence, oneof membership and reserved ranges in the diff; wire-compat metadata (`diff/protocol_compat.py`)
- SSE / WebSocket message-contract representations — EXISTING (operation kinds `EVENT`, `WS_MESSAGE`)
- MCP tool manifests (`specs/mcp/`): a saved `tools/list` — envelope, JSON-RPC
  frame or bare dump — compiled into the same contract model, so the existing
  breaking rules apply unchanged. Adds `BRK-MCP-*` for what is MCP's alone:
  the four `ToolAnnotations` hints, `outputSchema` presence, description edits
  (OWASP MCP03) and paginated captures. Cache and pagination state (`ttlMs`,
  `cacheScope`, `nextCursor`) is excluded by whitelist so it can never diff.
  Runtime drift against a live server is a separate capability, described
  under *Runtime* below — EXISTING

## Diff / breaking / governance
- Request/response-direction rules, enum/constraint/object/composition analysis, status-code/content-negotiation/header/security/server/pagination/idempotency compat — EXISTING (`diff/compat.py`, wired into CLI **this pass**)
- GraphQL breaking rules + dangerous-change category — NEW (`diff/protocol_compat.py`)
- gRPC wire compatibility (type swaps, width changes, enum removals, field retirement guidance) — NEW
- Contract lint, policy rule packs, expiring suppressions, deprecation lifecycle, semver engine, lifecycle states/transitions — EXISTING
- Diff fingerprints dedup across revisions — EXISTING (`model_v2.fingerprint_findings`)
- Release-sequence changelog aggregation, git blame linking, PR baseline discovery — BLOCKED (needs multi-version corpus + repo context in CI; interfaces documented)
- Consumer registry & blast radius (`rules/consumers.py`, `breaking --consumers`)
  — NEW. A finding gains the services it breaks, and the artifact gains a
  `blast_radius` grouped by consumer and by team. Softening a finding nobody
  consumes takes two separate acts — the registry declaring `complete: true`
  and `--severity-by-consumers` — because *no consumer listed* and *no consumer
  exists* are different statements. `CONSUMER-UNKNOWN-OPERATION` catches an
  entry that can never match, validated against both contracts so a removed
  operation is not mistaken for a typo. Field granularity is out of scope and
  the docs say why: a `Change` carries a field name only inside a
  human-readable description
- Non-breaking alternatives for every rule (`rules/alternatives.py`,
  `breaking --suggest-fix`, `explain`, and an `Instead` column in the generated
  catalogue) — NEW. A gate that only says no gets switched off. Completeness is
  a test: every rule has an entry, and nothing has one for a rule the engine
  cannot emit

## Generation & stateful testing
- Seeded positive/negative generation, boundary values, pairwise, example mutation, shrinking, corpus export/import/replay — EXISTING
- Pluggable case generators via `apiverity.generators`, invoked by `apiverity test --generator` — EXISTING (`fuzz/generators.py`); built-ins: unicode, nesting, numeric, header-safety
- Workflow engine v2 (extraction/guards/cleanup), graph validation, templates, model-based CRUD — EXISTING
- Workflow inference from OpenAPI Links (`workflow --infer`) — EXISTING (`stateful/infer.py`); links-only, every step emitted commented out, destructive steps commented twice

## Runtime: drift, replay, performance
- Drift monitor, field-frequency analysis, HAR normalization with redaction DSL,
  replay manifests/dry-run/destructive gate — EXISTING
- Drift baselines reachable from the CLI (`drift --baseline` /
  `--save-baseline`) — NEW. `drift_trend.py` had the comparison from the first
  version and nothing called it. Known findings stay in the artifact and stop
  failing the run, so the gate can be adopted on a service that already drifts;
  resolved findings are named, because that half is what makes the other half
  credible
- One finding shape across all four drift modes, published in `result-v1` —
  NEW. Each mode returned a differently-shaped report nested under `report`,
  outside the contract that constrains a top-level `findings` array
- Timestamps carried through `import_har` — NEW. They were dropped before any
  analyser saw them, so a report could say a header was missing four hundred
  times and not whether that began last Tuesday
- Ghost routes (`apiverity ghosts`) — NEW. Routes a contract no longer declares
  that the deployment still answers, from a previous contract or a recorded
  corpus. Safe methods only; a removed write is reported unprobed rather than
  skipped, and no candidate is ever guessed
- Call budgets (`apiverity budget`) — NEW. Sliding windows, because a burst
  straddling a clock minute passes a tumbling bucket. The finding worth most is
  about the budget itself: a limit naming an operation nothing declares can
  never match, so the file looks like protection and is not
- MCP runtime drift (`drift <manifest> --base-url`): declared tool schema vs a
  live server over Streamable HTTP. `MCP-DRIFT-*` compares the manifest to the
  server (missing, undeclared, schema drift traced back to the `BRK-*` rule
  that classified it, contradicted annotations); `MCP-CONF-*` checks the server
  against the specification with no manifest at all, including a second
  connection to verify the tool set does not vary per connection. Silent by
  design where the run established nothing: a hit page cap suppresses every
  missing-tool finding, and a refused protocol revision stops before any
  comparison. stdio is deliberately unsupported -- `classify_target` works on
  URLs, so none of the safety gates can express a command line — EXISTING
  (`runtime/mcp_drift.py`, `specs/mcp/runner.py`)
- Corpus drift (`drift --corpus`): aggregated frequency per finding, systematic vs one-off classification, content-negotiation-aware schema selection, corpus-quality summary — EXISTING (`runtime/corpus_drift.py`)
- Shadow contract inference (`apiverity infer`) — NEW. A HAR becomes an OpenAPI
  3.1 draft that loads back through every other command. Marked as inferred in
  three places; `required` needs both universal presence and at least three
  samples; enums are off unless asked for; and a path segment becomes a
  parameter only on evidence, with the reason written into the operation's own
  description. Reconciliation is `diff` against the draft, so it needs no
  separate report
- Local reverse-proxy capture mode — BLOCKED (interface specified; socket-level work outstanding)
- Load profiles incl. Poisson + capacity search, p50–p99 metrics, budgets/regressions — EXISTING
- Response-size/bandwidth metrics, TLS timing breakdown, GraphQL op budgets, gRPC latency metrics — PARTIAL

## Mock & virtualization
- Mock v2 scenarios/state/faults/seed control; virtualization workspace from bundles; request validation mode — EXISTING

## Security & privacy
- Defensive security packs, OAuth scope coverage, sensitive-field redaction, auth profiles — EXISTING
- OTLP trace export with attribute redaction — EXISTING (`exporters/otel.py`)
- Authentication findings that can actually fire — FIXED. `SEC-AUTH-MISSING`
  and `SEC-UNAUTH-WRITE` were unreachable: an empty `global_security` default
  was read as an explicit anonymity declaration, so a spec with an
  unauthenticated `POST /orders` reported one INFO and nothing else.
  `SEC-UNAUTH-WRITE` now lands at WARN rather than the ERROR it was declared
  as, because the finding is about the document and a gateway may require a
  token the contract never mentions
- MCP tool-poisoning and annotation integrity (`security/mcp_poisoning.py`) —
  NEW. In MCP a description is the routing input, which makes it executable
  text: invisible characters, prose naming a credential path, sentences
  addressed to the agent, hidden markup, cross-tool instructions, and
  annotations contradicting the tool's own name. Two deliberate
  non-detections, because a check that fires on ordinary manifests is one
  somebody disables
- MCP authentication posture (`drift --base-url`) — NEW. With credentials, one
  extra `tools/list` goes out with them stripped: the answer that matters is
  not *anonymous access is refused* but *anonymous access returns the same
  twenty tools*, and no authenticated probe can tell those apart
- Shadow MCP servers (`apiverity mcp-inventory`) — NEW. Read from client
  configuration rather than scanned for: a sweep is a scanner, and the case
  that actually happens is a developer adding a server to their own editor
- Credential scanning of responses (`security/leakage.py`) — NEW. Live
  responses, recorded corpora and MCP tool results. A finding carries the kind,
  the pointer and the length; never the value
- `mcp.lock` (`apiverity mcp-lock`) — NEW. A reviewed baseline for a tool
  surface, carrying the whole surface so `check` can say *what* changed, with
  an optional HMAC whose limits are stated rather than implied
- OWASP MCP / Agentic / API Top 10 mapping, and evidence packs
  (`report --format owasp-*`, `apiverity evidence`) — NEW. Every control
  appears in every report, including the ones this tool cannot assess, and
  nothing is ever graded

## Self-hosted server
- Orgs/users/RBAC, contracts/findings/runs/environments/policies/approvals, hash-chained audit, signed webhooks, can-i-deploy, retention purge, health/readiness/metrics — EXISTING
- Worker enrollment + pull-based job queue with idempotency keys and backpressure — NEW (`server/jobs.py`)
- SSE run progress stream — NEW (`GET /v1/runs/<id>/events`)
- Backup/restore/export/import (+ `apiverity server-db` command) — NEW
- API rate limiting — NEW (`create_app(rate_limit_per_minute=…)`)
- OIDC/SAML concrete providers — BLOCKED behind a real IdP; `IdentityProvider` protocol + local provider exist and are tested

## Frontend
- 33-route product UI (public/local + team pages), design tokens,
  dark/light/system themes, virtualized tables, DEMO labeling, demo corpus
  generator — EXISTING. The route count is derived from
  `web/src/pages/index.tsx`, not asserted here
- Agent-governance pages (MCP fleet posture, tool poisoning, call budgets) —
  NEW. Every number on them came off a socket: the demo generator starts three
  mock MCP servers with deliberately different postures and probes them
- The committed demo artifact had been stale since August, because the
  generator raised on a renamed field and nothing runs it in CI, so six pages
  rendered *Loading...* on the public demo. Fixed, regenerated, and guarded by
  a test binding the artifact to every section the types declare — FIXED
- Tables scroll themselves at narrow widths. `.table-wrap` has been in the
  stylesheet since the first version and no page used it, so at 375px the
  *document* was 576px wide and the whole app slid sideways — FIXED

## Distribution
- `docs/llms.txt` and `docs/capabilities.json`, generated from the code and
  checked in CI — NEW. What this tool is and what it can do, for a model and
  for a machine
- Every command has a one-line help. Eighteen of thirty had none, including
  `validate`, `diff`, `breaking`, `drift` and `test`, so `apiverity --help`
  described the newest twelve and listed the rest as bare names — FIXED
- A non-ASCII contract title exited 4 on a Windows console, and so did
  `changelog` and `breaking --summary` against this repository's own fixtures
  — FIXED
- PyPI publishing is still switched off, so `pip install api-verity-lab` 404s
  and `uvx`/`pipx` cannot work — BLOCKED on registering a Trusted Publisher and
  setting the `PUBLISH_ENABLED` repository variable, both of which need the
  maintainer's account

## Deliberately not pursued
See `PRODUCT_GAPS.md` ("Features deliberately not pursued").
