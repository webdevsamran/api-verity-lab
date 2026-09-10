# Capability Status

Honest classification of the transformation target list against the actual
codebase (audited 2026-09-10). "NEW" items below were implemented in this
pass; "EXISTING" items were already present and verified by tests.

Legend: EXISTING · PARTIAL (improved this pass where noted) · NEW (this pass) · BLOCKED (external validation required) 

## Core model & protocols
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
- JSON Schema 2020-12-aware comparisons — PARTIAL (`prefixItems`, `contains`,
  `patternProperties`, `propertyNames`, `dependentRequired`, `dependentSchemas`,
  `if`/`then`/`else` and `const` are modelled, diffed and enforced; the two
  `unevaluated*` and two `$dynamic*` keywords are not, and are named with the
  reason in [spec support](spec-support.md))
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
- Seeded positive/negative generation, example mutation, shrinking, corpus export/import/replay — EXISTING
- Boundary values and pairwise parameter coverage (`test --generator pairwise`): every *combination* of two parameter values at least once, where every other generator varies one thing at a time — EXISTING (`fuzz/boundary.py`)
- Pluggable case generators via `apiverity.generators`, invoked by `apiverity test --generator` — EXISTING (`fuzz/generators.py`); built-ins: unicode, nesting, numeric, header-safety, pairwise
- Workflow engine v2 (extraction/guards/cleanup), templates — EXISTING
- Model-based CRUD (`test --model-based`): create a resource, read it back, update it, read it again, delete it, check it is gone. Collections are discovered from the contract and payloads derived from it. These are the questions a per-request check cannot ask, because they are about sequences — EXISTING (`stateful/model_based.py`)
- Graph validation before a run: `workflow` checks the manifest for variables nothing fills, duplicate step names and cleanup that deletes what it did not create, and refuses to send anything when it finds one (`--no-preflight` overrides) — EXISTING (`stateful/graph.py`)
- Workflow inference from OpenAPI Links (`workflow --infer`) — EXISTING (`stateful/infer.py`); links-only, every step emitted commented out, destructive steps commented twice
- Arazzo 1.1.0 import and export (`workflow --to-arazzo`; an Arazzo description runs directly) — EXISTING (`stateful/arazzo.py`); the export is validated against the OAI's own published JSON Schema, and every construct with no equivalent in this engine — `goto`, `retry`, nested workflows, AsyncAPI channel steps — is reported rather than dropped. See [Arazzo workflows](arazzo.md)

## Runtime: drift, replay, performance
- Drift monitor, field-frequency analysis, HAR normalization with redaction DSL,
  replay manifests/dry-run/destructive gate — EXISTING
- Behavioural drift: one corpus against another, for the changes a schema check
  cannot see -- an optional field that stopped being populated, a value that
  stopped appearing, a null rate that jumped (`drift --against-corpus`) — NEW.
  Every finding carries its sample sizes and the comparison declines to speak
  below twenty responses a side; see [behavioural drift](behavioural-drift.md)
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
- Declarative load shapes -- constant, ramp, spike, soak, each optionally with Poisson arrivals -- driven **open loop** at one named operation (`regression --shape ramp:60s@1..20 --operation 'GET /users'`) — EXISTING (`performance/profiles.py`); the run reports how far behind its own schedule the generator fell, because a p99 from a generator that could not keep up describes a load nobody asked for. See [Load shapes](load-shapes.md)
- Closed-loop concurrency sweeps (`regression --curve`), p50–p99 metrics, budgets/regressions — EXISTING
- Concurrent measurement and concurrency curves (`regression --concurrency N`,
  `regression --curve 1,2,4,8`) — NEW. `measure` accepted a `concurrency`
  argument from the beginning and never read it, so every report described a
  service under a load of one. The curve reports where throughput stops rising
  and where latency starts climbing, and names a plateau at the top of the
  sweep as a sweep that did not go far enough rather than as the service's
  ceiling
- Response-size and bandwidth metrics — NEW. Every request already read a body
  and nothing counted it, so a report could say an operation answered in 12 ms
  and not that it answered with four megabytes. `bytes_p50`/`bytes_p95`/
  `bytes_max` are percentiles rather than a mean, because the response that
  hurts is the largest one a client hit. Budgetable like latency
  (`GET /users bytes_p95 <= 256KB`), since a measurement nothing can gate on is
  a measurement nobody reads. Counted after decoding, which is the number a
  payload budget is about and is *larger* than what crossed the wire
- TLS timing breakdown — NEW, and deliberately not per-request. `httpx` exposes
  no hook between resolving and handshaking, and the load run pools connections
  on purpose, so for every request after the first the handshake costs nothing;
  amortising it into a p95 would describe a service nobody runs. It is one cold
  connection probed before the run — DNS, TCP, TLS, and what the handshake
  negotiated — reported beside the percentiles with a sentence in the artifact
  saying it is not inside them
- GraphQL operation budgets, gRPC latency metrics — PARTIAL (the measurement
  loop speaks HTTP; neither has a client here)

## Mock & virtualization
- Mock v2 scenarios/state/faults/seed control; request validation mode — EXISTING. Stateful across the whole of CRUD: a create is stored, an update persists (PATCH merges, PUT replaces), a delete removes, and a read of a deleted resource is a 404
- Virtualization workspace: several contracts served together from one file, under one seed, with per-service faults and the address of each printed before the servers block (`mock --workspace`) — EXISTING (`mock/virtualization.py`). See [Virtualization workspaces](virtualization.md)

## Library-only capabilities

Every entry above is graded EXISTING when the capability is implemented and
tested. A capability can be implemented, tested, and **reachable from no
command** -- importable from Python, absent from the CLI. That is a different
thing from EXISTING and a reader will not distinguish them unless told, so any
that are get listed here.

**The list is empty.** It began at seven, found by a reachability walk that
went looking. Five were wired to a command -- `--auth-profile`,
`mock --workspace`, `regression --shape`, `test --generator pairwise`,
`test --model-based`, and the graph check `workflow` now runs before its first
request -- and one, `core.model_v2`, was deleted: every part of it was a
parallel implementation of something this project already ships, and its
CODEOWNERS reader used glob semantics where the format uses gitignore ones, so
it would have assigned the wrong team.

An empty list is not the end of the check. It is found mechanically --
`tests/unit/test_check_catalog.py` walks imports from `apiverity.cli.main` and
`apiverity.mcp.server`, and `tests/unit/test_library_only.py` pins this section
against that walk -- and the build fails when a module joins it. That is a
feature written and never connected, which is how four published rules came to
be unreachable and how "Lint -- VERIFIED" came to be published about an engine
nothing ran.

Two notes for the next entry, written while there is none.

**"Import only" is not "broken".** Anything listed here has tests that run in
CI, and the SDK is a supported surface. What it means is that no flag on any
command reaches it.

**A list here is not a plan.** An entry should be wired up or deleted, and
deciding which is a judgement about the product rather than a fact about the
code -- one that needs evidence, which is what the walk produces. Publishing
the list is what stops the question being invisible.

## Security & privacy
- SBOM, SLSA provenance and release checksums — NEW. A tagged release now
  writes `SHA256SUMS` and an SPDX SBOM beside the distributions, attests both
  through Sigstore, and attests the container image **by digest** — a tag can
  be moved onto different bytes, and an attestation naming one would describe
  an image nobody is running. Verified with `gh attestation verify`. The honest
  caveat is on [the page itself](supply-chain.md): these steps are on the
  tag-push path and no tag has been cut since they were added, so they are
  configured and unexercised
- Defensive security packs, OAuth scope coverage, sensitive-field redaction — EXISTING
- Auth profiles on every command that takes `--base-url` (`--auth-profiles FILE --auth-profile NAME`): bearer, API key, basic and mTLS, each naming an environment variable or a file rather than carrying a credential, so a bundle records `token_env: STAGING_TOKEN` and nothing replayable — EXISTING (`traffic/auth.py`). See [Auth profiles](auth-profiles.md)
- BOLA and BFLA probes between two identities (`test --authz --auth-profile alice --as bob`): create a resource as one identity and try to read, update and delete it as another; call operations the contract says need a scope the second identity does not hold. OWASP API1 and API5, neither of which a schema check or a single-identity run can see — EXISTING (`security/authz.py`). See [Authorization probes](authorization.md)
- OTLP trace export with attribute redaction — EXISTING (`exporters/otel.py`),
  reachable from the CLI since 2026-09-10 (`drift --otlp-endpoint`) and following the
  OpenTelemetry GenAI conventions for MCP (`exporters/semconv.py`). Before that the
  recorder was library-only, and its OTLP output carried no end timestamp
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
- 34-route product UI (public/local + team pages), design tokens,
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
