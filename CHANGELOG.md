# Changelog

All notable changes. Format based on Keep a Changelog; versions are semver.

## [Unreleased]

### Fixed

- **The competitive table was not generated, in three places that said it was.**
  `README.md` claimed "the table is generated from that file, so it cannot
  drift"; `docs/index.md` claimed twice that it is "rendered from committed API
  data" by "a checked-in script". No such script existed, no CI step checked it,
  and the table was typed by hand -- which the test guarding it admitted in its
  own docstring. In a repository whose rule is "documented output is captured,
  never written", the document making that claim was the one not honouring it.

  `scripts/generate_competitive_table.py` now renders the provenance line, the
  method date and the landscape table from `data/competitor-meta.json`, with a
  `--check` step in CI. Its first run changed only two values, both stale dates:
  the document had been headed "Generated: 2026-08-23" directly above a table
  headed "verified 2026-09-09", describing the same artifact seventeen days
  apart. Every one of the fourteen rows was already correct, and is now rendered
  rather than retyped.

- **Two of the fourteen rows were never actually checked.**
  `test_competitive_table_matches_data.py` mapped a row to its data entry by
  repository basename and skipped any row it could not map, deferring to "the
  count test" -- which did not exist in that module. "Pact (pact-js)" and
  "GraphQL Inspector" both missed, so their licence, stars and last-push cells
  were unverified. The licence assertion had a third hole: guarded by
  `if want_lic`, a null licence let the table print anything. The comparison is
  now whole-document against the generator, which cannot skip a row.

- **Optic's entry still carried the fabrication it was supposed to have fixed.**
  `data/competitive-capabilities.json` recorded Optic's repository as
  `useoptic/optic`, all its metrics as `null`, a weakness reading "Project no
  longer published under useoptic org (repo 404 verified 2026-08-23)", and an
  evidence item asserting that 404 as `VERIFIED`. The project is `opticdev/optic`
  -- archived and public, MIT, 1,534 stars -- and `useoptic/optic` 404s because
  it never existed: the repository's own fetcher was asking for the wrong name.
  A tool failure wearing a `VERIFIED` label, in the file that defines what
  `VERIFIED` means. Corrected from the fetched artifact, and a new test binds
  every curated `github_repo` to a repository the fetch actually covered.

- **`result-v1` rejected artifacts from a protocol it shipped.** The published
  `protocol` enum listed `openapi | graphql | grpc` while
  `apiverity.core.model.Protocol` had six members and the AsyncAPI adapter had
  been shipping since 0.2.0, so `apiverity validate events.yaml --json` emitted
  `"protocol": "asyncapi"` and violated the project's own schema on the happy
  path. The enum now carries every `Protocol` member.

  Nothing caught it because `scripts/validate_result_artifacts.py` ran
  `validate` -- the only command that writes that field -- against a single
  OpenAPI fixture, so exactly one of the enum's values was ever exercised. The
  script now also validates an AsyncAPI contract
  (`fixtures/asyncapi/events-v1.yaml`), and
  `tests/unit/test_result_schema_matches_protocols.py` binds the enum to the
  `Protocol` enum in both directions, so neither a new protocol nor an invented
  schema value can drift again. The enum change is additive: no artifact that
  validated before stops validating.

## [0.2.0] - 2026-09-07

Ten open issues closed. The theme running through them is that several
documented capabilities were declared and never wired up, and several rules
reported the opposite of what had happened.

### Added — protocols

- **AsyncAPI 3.x** (#18). The adapter handled 2.x only. Direction is now
  normalized to the application's point of view, because the two versions'
  words are inverted -- AsyncAPI 2's `publish` describes what the application
  *consumes* and `subscribe` what it *produces*, while 3's `send`/`receive`
  read from the application's side. Storing the raw word made a 2.x document
  and its own 3.x migration compare as two unrelated contracts. The adapter is
  also registered under the `apiverity.specs` entry point, which it was not.
- **Compiled gRPC descriptor sets** (#17): `.desc`/`.pb`/`.protoset` load,
  decoded from the protobuf wire format with no protobuf runtime dependency.
  For a proto with imports this is the only input that can be correct.
- **GraphQL operation testing** (#16): schema-driven query generation,
  persisted operation documents via `test --operations`, `{data, errors}`
  envelope assertions, and introspection-based drift via `drift --base-url`.
  GraphQL cannot go through the HTTP runner -- a server answers a malformed
  query with 200 and an `errors` array, so a status-code verdict marks every
  failure a pass.

### Added — analysis

- **Corpus drift** (#21): `drift --corpus traffic.har` aggregates findings with
  a frequency per operation and separates systematic drift from one-offs. A
  thousand entries against a service missing one declared header used to
  produce a thousand identical findings.
- **Statistically sound performance gates** (#24): bootstrap confidence
  intervals for percentiles and throughput, a Wilson interval for error rate,
  `--warmup`, and per-metric `--tolerance`. A change must clear the tolerance
  *and* have non-overlapping intervals before it is called a regression; where
  they overlap the run is reported inconclusive rather than passed. Measured
  against a fixed local target over ten runs, this took asserted regressions
  from 22 to 8 -- all of them false by construction, because nothing changed.
- **Pluggable case generators** (#19): the `apiverity.generators` entry point
  was declared, documented and never read. Four strategies ship with it --
  unicode, nesting, numeric boundaries and defensive header safety.
- **Workflow inference** (#20): `workflow --infer` drafts a manifest from the
  `links` a spec declares, and only from those. Every step is emitted
  commented out; destructive steps are commented twice, so uncommenting the
  file wholesale does not arm them.
- Seven protobuf compatibility rules and the rest of the request/response
  requiredness catalog (#15, #17). The catalog is 44 rules, generated.

### Fixed — rules that reported the opposite of what happened

- A field **becoming required** in a request body was reported as
  `BRK-PARAM-OPTIONALIZED` at INFO. Requiredness was only compared in one
  direction and passed no new value, so a breaking change passed a CI gate as
  informational. A response field becoming optional was not detected at all.
- Dropping a required field from an AsyncAPI message the application **sends**
  was reported as a request relaxation -- "senders are unaffected" -- when the
  application is the sender and the consumers break.
- A **unary gRPC RPC becoming bidirectional** produced zero changes. The
  `stream` markers were captured by the parser and discarded.
- A protobuf field **renamed at the same number** is wire-compatible and is now
  reported as such at WARN; only a number whose type changed is an error.
  Reporting every rename as data corruption trains people to ignore the rule
  that catches actual corruption.

### Fixed — checks that were never reached

- `PROTO-FIELD-NUMBER-REUSE` was constructed on every duplicate field number
  and then dropped: the function returned only the schema.
- `detect_drift` accepted `forbid_undeclared_fields` and passed a hardcoded
  `True`.
- `EXIT_UNREACHABLE` was unreachable. `measure` catches connection errors per
  request, so a target with nothing listening produced a clean report and
  exit 0.
- `import_har` called `json.loads` on every postData; one HTML error page took
  down the import of an entire corpus.

### Fixed — reports

- **SARIF carries locations** (#22). Findings have always had file, line,
  column and JSON pointer; the renderer emitted none of it, so GitHub code
  scanning annotated the repository rather than the line. Adds rule metadata
  and `partialFingerprints` that exclude the message, so an alert is not
  retired and re-raised when a number in its text changes.
- **JUnit emits testcases.** It declared `tests="N"` over an empty testsuite,
  so every consumer read zero tests.
- **HTML escapes spec content** and is fully self-contained, with filter state
  in the URL hash. Messages carry field names straight out of a user's
  document and were interpolated raw.
- `apiverity report` no longer carries its own copy of every renderer; the two
  had already diverged.

### Changed

- The demo app loads page groups as separate chunks (#23): 224 kB in one file
  to a 198 kB entry plus 31 kB across six lazy chunks.
- Docs corrected where they described capabilities that did not exist:
  AsyncAPI was "planned" while a 2.x adapter shipped, gRPC descriptor import
  was "EXISTING" with nothing in the plugin mentioning descriptors, and
  workflow inference was "PARTIAL" with no inference of any kind.
- README count claims are re-derived and tested, not restated.

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
