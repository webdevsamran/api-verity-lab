# Changelog

All notable changes. Format based on Keep a Changelog; versions are semver.

## [Unreleased]

### Added — canonicalization before diffing

- **`allOf` is collapsed, enums are deduplicated, and everything is ordered**
  before two contracts are compared (`apiverity/core/canonical.py`, applied in
  `diff_services`).

  The differ compares `allOf` branches *positionally* — it zips the two lists,
  and only when their lengths match. Three consequences, and the third is not
  cosmetic:

  * `allOf: [Base, {extra}]` and the same schema written inline were completely
    different documents, so refactoring a spec without changing its meaning
    reported as a rewrite;
  * reordering branches renumbered every nested comparison, though `allOf` is a
    conjunction and order carries no meaning;
  * **two `allOf` lists of different lengths were skipped entirely and
    silently**, so adding a branch hid every change inside the ones that
    remained. A reviewer read a clean diff and concluded nothing had changed.

  Conjunction semantics are honoured rather than approximated: constraints
  merge to the tightest bound (largest minimum, smallest maximum) and enums
  intersect, because a value must satisfy every branch.

- **What it refuses to do is half the design.** Branches that disagree about a
  type are left composed and reported as `SPEC-ALLOF-CONFLICT`: an `allOf` of
  `{type: string}` and `{type: integer}` is unsatisfiable, and silently picking
  a winner would turn a broken contract into a plausible-looking one.
  `oneOf`/`anyOf` are never flattened — a disjunction is not a conjunction.

  It runs in `diff_services`, not the loader, so `validate` still reports on the
  document as written, source locations and all. `canonical=False` compares the
  documents as text when the question really is about the document.

### Fixed

- **`_stable_unique` dropped enum members**, found by its own test. Python
  considers `True == 1`, so a plain membership check discarded one of them, and
  an enum declaring both `1` and `true` — different values under JSON Schema —
  would silently lose a member. Narrowing an enum is a breaking change;
  doing it by accident inside the tool that detects breaking changes is worse.
  Deduplication now keys on `(type, value)`.

### Added — OpenAPI 3.2

- **OpenAPI 3.2.0 (released 2025-09-19) loads and is governed.** The version
  gate accepted 3.0 and 3.1 only, so the current release reported as an
  unsupported version and every construct it added was invisible.

  * the `query` method — a payload-carrying read, formalised because APIs were
    already tunnelling large filters through POST;
  * `additionalOperations`, for verbs the specification does not name (WebDAV's
    `PROPFIND`, a bespoke `PURGE`). They have real request and response shapes,
    so removing one is breaking like any other operation;
  * the `querystring` parameter location — the whole query string as one Schema
    Object, distinct from `query` because a change to it changes every filter
    at once;
  * hierarchical tags (`summary`/`parent`/`kind`), which move navigation from
    the `x-tagGroups` vendor extension into the contract. A `parent` naming no
    declared tag is reported rather than repaired: guessing which tag was meant
    would invent structure the document does not have;
  * the OAuth `deviceAuthorization` flow and `oauth2MetadataUrl`.

  The tests assert *governance*, not parsing: a removed `query` operation fires
  `BRK-OP-REMOVED`, a tightened `query` body fires
  `BRK-REQ-FIELD-BECAME-REQUIRED`, a removed `querystring` parameter fires
  `BRK-PARAM-REMOVED`. A construct that loads and then cannot be reported on is
  worse than one that never loaded, because it looks covered.

  A 3.3 document is still refused. Parsing an unpublished format on the
  assumption it resembles 3.2 produces a contract that looks parsed and is wrong.

### Fixed

- **`SecurityScheme.scopes` was declared by the model and never populated.**
  The parser read `flows` for nothing, so OAuth scope coverage had no data to
  work from — for any contract, in any version, since the field existed. Flows
  are now captured per-flow *and* unioned into `scopes`, because dropping a
  whole flow is breaking in a way that dropping one scope from one flow is not.
  An OAuth flow no OpenAPI version defines is reported.

### Added — bundle integrity and scriptable output

- **`apiverity verify <bundle>`.** `export` has always written `SHA256SUMS`
  and nothing has ever read it, which made the checksum decorative: a bundle
  emailed between machines, or pulled from a CI artifact store, could be
  altered in any way and nothing would notice.

  Three failure modes, reported separately because they call for different
  responses: a digest that no longer matches (tampered or corrupted), a listed
  file that is gone (truncated), and a file present that the manifest never
  listed (added). "The bundle is wrong" is not an actionable sentence. A
  directory that was never a bundle is a *usage* error, distinct from a bundle
  that fails verification.

- **`--json` on `changelog`, `mock` and `serve`**, which were unscriptable: a
  CI step wanting the changelog had to parse markdown, and one wanting the
  mock's address had to scrape a log line.

  Adding the flag everywhere would have been wrong, and two commands show why.
  `report` keeps `--format json|sarif|junit|html|yaml`, which is strictly more
  expressive, and a test asserts that any command excluded from `--json` really
  does have something better — so the exclusion list cannot become a place to
  park an oversight. `mock` and `serve` block forever, so they emit the bound
  address *before* serving; a `--json` that produced nothing until Ctrl+C would
  be a flag that does nothing. `changelog` puts the rendered document *inside*
  the artifact rather than printing it alongside, because a caller asking for
  JSON is parsing stdout.

### Added — governance UX

- **`apiverity explain <rule-id>`.** The catalogue already carried a
  description; what it did not carry was *where to look next*, which is the
  question someone reaching for `--severity-override` actually has. `explain`
  prints the rule, its severity, its group, the documentation section, and the
  exact override and suppression syntax. A typo gets a did-you-mean rather than
  a dead end. A rule nobody understands gets suppressed rather than fixed —
  ESLint's whole adoption story.

  Two tests keep it honest: every rule in the catalogue must be explainable,
  and none may fall into the unclassified "Other" bucket, so a new rule family
  added without a guide entry fails rather than silently pointing readers at
  the top of the catalogue.

- **`apiverity breaking --suggest-version`.** The semver policy has always held
  every input needed to say what the next version should be, and only ever said
  whether the one you picked was wrong. It now answers the other question, and
  reports the rule ids that forced the answer — a recommendation with nothing
  behind it is an opinion, not a verdict.

  An unparseable current version still yields a bump (which the findings
  determine) but never a made-up number (which they do not). Pre-1.0 is not
  special-cased into "anything goes": a project that publishes 0.4.0 and breaks
  its consumers has still broken them.

### Fixed

- `explain` writes a `command` value into its artifact, and that field is
  enum-constrained — the same trap as the AsyncAPI `protocol` gap. Added to the
  schema *and* to `validate_result_artifacts.py`, so the next command to emit
  an artifact is caught by CI rather than by a user.
- `docs/mcp-exposure.md` said "of the nineteen commands" when there are twenty.
  Both numbers in that sentence are now derived from the code.

### Added — apiverity as an MCP server

- **`apiverity-mcp --root .`** exposes the read-only subset
  `docs/mcp-exposure.md` specified: `validate`, `diff`, `breaking`,
  `changelog`, `coverage`, `rules`, `plugins`. An agent editing a spec can ask
  whether the change is breaking and get an answer with a rule id behind it,
  rather than a plausible one.

  Newline-delimited JSON-RPC over stdio, and **no new dependency**: the framing
  is about fifty lines, and adding an SDK to a package whose entire runtime is
  httpx, flask, pydantic, PyYAML and packaging would cost more than it saves.
  The document's third prerequisite — "a decision about who ships it" —
  dissolved rather than being answered.

- **What is not exposed is the point**, and the boundary is the one
  `SAFETY_MODEL.md` already draws: `drift`, `replay`, `baseline` and
  `regression` contact a target, and a model must not be able to send traffic
  to an arbitrary base URL because a prompt told it to; `mock`, `serve` and
  `server-db` hold state, and a tool call that leaves a process running is not
  a tool call; `export` writes to disk. A parametrised test asserts each stays
  absent.

- **Three server-shaped hazards the CLI does not have**, each with a test:

  * *Provenance leaking between calls.* `cli/commands/common.py` keeps
    `_LAST_SPEC` and `_LAST_PROTOCOL` in process globals set as a side effect of
    `_load`. A `rules` call, which loads no contract, would have reported the
    previous caller's spec as its own. Handlers call `core.artifact.enrich`
    directly with per-call arguments and never touch `_emit` — which also
    prints to stdout, and stdout *is* the frame stream.
  * *Confinement that stops at the check.* `detect_and_load` reads the caller's
    string twice, so the **resolved** path is what reaches it. `http(s)://` is
    refused outright: `specs.read_source` would fetch it, which is SSRF through
    an argument a model chooses, in a server documented as making no network
    calls.
  * *Errors disclosing the filesystem.* Loader failures embed the full resolved
    path, so nothing echoes `str(exc)`; messages name paths relative to the root.

- `MCP_TOOLS_SCHEMA_VERSION` versions the tool surface independently of the
  package, which moves for unrelated reasons.

- The server's own `tools/list` is parsed by this project's MCP manifest
  loader in a test — the cheapest possible check that what it advertises is
  well-formed, and it emits the `ttlMs`/`cacheScope` its own drift checker
  reports other servers for omitting.

### Fixed

- `docs/mcp-exposure.md` said "Nine of the nineteen commands" directly above a
  table of seven, for its whole life, in a repository whose rule is that counts
  are derived. Bound to `len(TOOLS)` and the table's own row count.

### Added — MCP tool invocation, behind a gate

- **`--invoke-tool NAME` calls a tool and checks the result against its
  declared `outputSchema`.** Gated the way `apiverity replay` is, because
  replay already answers "how do we let someone send real traffic without
  letting them do it by accident" and a second vocabulary would be worse than
  reusing the first:

  * exact names only, never globs — a pattern matched against a live tool list
    hands the *server* the choice of what runs, and names resolve against the
    declared manifest so a server cannot offer a name and have it called;
  * dry run by default: `--invoke-tool` alone prints the plan, every tool and
    every generated argument, and sends nothing;
  * `--execute` with no named tool is a usage error, not a wildcard;
  * a target that does not classify as local/dev/staging needs
    `--i-know-this-is-production`.

- **Annotations authorize nothing.** `readOnlyHint` and `destructiveHint` are
  attacker-controlled data — the specification says clients MUST treat
  annotations as untrusted unless the server is trusted — so the gate never
  consults them. `test_read_only_hint_does_not_authorize_a_call` is the
  inversion test: a tool claiming to be read-only must be no easier to invoke
  than any other, or the safest-looking tool becomes the easiest to abuse.

- **Findings never quote what a tool returned.**
  `core/validation.py::validate_value` embeds the offending value in its
  message, so routing live `structuredContent` through it would write real
  response data into a committed artifact — the opposite of what
  `docs/privacy.md` promises. This path reports the JSON pointer, the declared
  constraint and the observed *type* (`"/hits: expected array, got string"`),
  and a test asserts a synthetic secret in a tool result never reaches the
  serialised report.

- Arguments come from the **declared** input schema, seeded and recorded,
  because the question is whether the server honours what it published.

- `SAFETY_MODEL.md` gained five numbered controls for this path. Its list had
  also drifted out of sequence and is renumbered contiguously.

### Fixed

- `pytest -m integration`, advertised in `CONTRIBUTING.md` and registered under
  `--strict-markers`, selected **zero** tests: no file in `tests/integration/`
  carried the marker. It now selects 106.

### Added — MCP runtime drift

- **`apiverity drift <manifest> --base-url <endpoint>`** compares a declared
  MCP tool manifest against what a live server actually serves, over Streamable
  HTTP. Read-only: `server/discover` and `tools/list` are reads, and nothing
  invokes a tool.

  This is the leg the market leaves open. Version-to-version manifest diffing
  is shipped by several projects; declared-vs-running is the question that
  breaks agents in production, and it is what this engine has been doing for
  five other protocols since v0.1.

  `MCP-DRIFT-*` covers the manifest against the server — declared but not
  served, served but not declared, schema drift, contradicted annotations.
  Schema drift runs through `diff_services` and the shared catalogue rather
  than a bespoke comparator, so every finding carries the `CHG-*` id and the
  `BRK-*` rule that classified it. `MCP-CONF-*` covers the server against the
  specification and needs no manifest at all, including a second connection to
  check that the tool set does not vary per connection (a MUST) separately from
  its ordering (only a SHOULD, so `INFO`).

- **Three places it deliberately reports nothing**, because the run established
  nothing: a hit `--max-list-pages` cap suppresses every missing-tool finding
  (a tool on page fifty-one was not removed); a server that refuses the
  protocol revision stops the run before any comparison rather than reporting
  every declared tool as missing; and a server with no `server/discover` is
  compared normally but never has a protocol revision recorded for it, because
  observing the absence of a method is evidence about that method.

- **stdio is unsupported, deliberately.** `SAFETY_MODEL.md` §1 is "explicit
  targets only" and every gate under it is expressed over a URL —
  `classify_target` derives local/dev/staging/production from a hostname and
  cannot classify `npx -y some-mcp-server`. Shipping stdio would mean spawning
  a command read out of a config file, before any existing control can express
  it. `docs/mcp-drift.md` states this as a decision with its reason.

- `--header NAME=VALUE` is supported because the specification lets a tool set
  vary by the authorization presented; the report records
  `authorization_presented` and the header *names*, never the values.

- `apiverity/mock/mcp_server.py` is a deterministic in-process MCP server for
  the tests, including the misbehaviours a well-behaved server will not produce
  on demand: a tool set that changes between connections, a missing
  `inputSchema`, a refused protocol version. It is threaded, because the
  per-connection stability check opens a second connection while the first is
  still held by keep-alive.

### Added — MCP tool manifests as a contract format

- **`apiverity validate|diff|breaking|changelog` now work on an MCP
  `tools/list` manifest.** A saved list result, a whole JSON-RPC response, or a
  bare `{"tools": [...]}` dump all compile into the same `Service` every other
  format produces, so no new CLI flag and no new dependency are involved.

  The point is what falls out for free. A removed tool fires `BRK-RPC-REMOVED`;
  a newly-required argument fires `BRK-PARAM-ADDED-REQUIRED`; a narrowed enum
  fires `BRK-ENUM-NARROWED-REQUEST`; a dropped output field fires
  `BRK-RESP-FIELD-REMOVED` — all from the existing catalogue, all landing in
  the same `result-v1` artifact as an OpenAPI change. Those are assertions in
  `tests/unit/test_mcp_manifest.py`, because they are the evidence for the
  "one contract model, one rule engine" claim rather than a side effect of it.

- **Thirteen `BRK-MCP-*` rules** for what is genuinely MCP's alone: the four
  `ToolAnnotations` hints, `outputSchema` presence, tool-description edits, a
  suspected rename, and a paginated capture. Catalogue 44 → 57.

  MCP defines no breaking-change semantics for a tool manifest — tools carry no
  version field and SEP-1575 is an open, unsponsored proposal — so this
  taxonomy is the project's own, and `docs/rule-catalog.md` now says exactly
  that above the group. `scripts/generate_rule_catalog.py` grew a per-group
  note slot so the disclaimer reaches the published document instead of living
  in a source comment nobody reads.

  The four annotation rules are WARN, not ERROR. The specification says clients
  MUST treat annotations as untrusted unless the server is trusted, and a rule
  cannot rest the catalogue's highest severity on a field the protocol itself
  declines to trust. `--severity-override` is one flag away for anyone treating
  a manifest as supply chain.

  A description edit is a finding at WARN, unlike every other protocol, because
  for an MCP tool the description *is* the routing input the model reads — a
  silent edit is the documented tool-poisoning vector (OWASP MCP03).

- Three deliberate non-decisions, each of which would have been a fabrication:
  the response status is `"result"` and not an invented `"200"` (a JSON-RPC
  result has no status code, and `compat.py` classifies on `startswith("2")`);
  `idempotentHint` is *not* mapped onto `Operation.idempotent`, whose other
  populators are authoritative declarations; and a bare tools dump never claims
  to be from the legacy era, because it is byte-identical from either.

- `ttlMs`, `cacheScope` and `nextCursor` are excluded by whitelist rather than
  by a drop-list, so cache state can never reach the diff — pinned by a
  Hypothesis property rather than one hand-picked pair of values.

### Added — dashboard

- **A design system.** `web/src/styles.css` had six variables, and
  `components/ui.tsx` then hard-coded hexes beside them (`#e5484d` for ERROR,
  `#2ea043` for pass) which no theme could reach -- the same red on a white page
  and a near-black one. Colour, type, space, radius, elevation and motion are
  tokens now, and the fourteen raw hexes across four page modules are gone.

- **Motion that exists.** The only motion rule in the stylesheet was the
  `prefers-reduced-motion` reset, disabling transitions the file never defined.
  There are now staggered card entrances, growing chart bars, a self-drawing
  line, skeleton shimmer, press states, a sliding nav marker and a theme
  cross-fade through the View Transitions API -- and the reset still comes last
  and still wins.

- **A command palette** (⌘K or `/`), lazily loaded into its own 2 kB chunk so
  the sessions that never open it never pay for it. Subsequence matching, so
  "brk" finds Breaking Changes.

- **A skip link, focus management and keyboard paths** throughout. Thirty nav
  items used to sit between the top of the page and the content.

- **`StatCard`, `Skeleton`, `LineChart`, `Sparkline`, `SeverityBar`.** Charts
  are hand-drawn SVG with a real table beside each one -- an `aria-label` can
  say "latency over time" but cannot tell anyone what p95 was on Tuesday. No
  charting dependency: the entry chunk is budgeted at 210 kB and a library
  would cost more than every page in the app combined.

### Fixed — dashboard

- **A stale chunk blanked the whole app.** A lazily-imported module that 404s
  unmounts the React tree, and that happens routinely: the site is redeployed
  while someone has it open, so their HTML asks for a filename the server no
  longer has. Pressing ⌘K after a rebuild produced a blank page.
  `ChunkBoundary` offers a reload instead, and distinguishes a stale chunk from
  a genuine render error rather than blaming everything on the deploy.

- **Rapid theme presses were lost.** `setTheme` ran inside
  `startViewTransition`; three presses from "system" landed on "light", a net
  movement of one. The state update is outside the transition now and only the
  attribute write is cross-faded, so every press counts.

- **Unhandled promise rejections from the theme switch.** Every promise a
  `ViewTransition` exposes rejects when the transition is abandoned, which is a
  normal outcome, and three `InvalidStateError`s reached the console for it.

- **A flash of unstyled content.** Tokens were defined only under
  `[data-theme=...]` and the attribute was set in an effect, so the first paint
  had no variables at all. `:root` carries the light theme, and `index.html`
  resolves a stored preference before the stylesheet parses. The choice also
  persists now, which it did not.

- **`--faint` failed WCAG AA at 3.04:1** on white, and it is what the 11px nav
  group labels and chart ticks are drawn in -- none of them large text. Every
  text token now clears 4.5:1 in both themes, measured in the browser and
  pinned by `tests/unit/test_frontend_contrast.py`.

- **"4/17 passed" rendered as one 30px string**, wrapped onto two lines and
  pushed its card taller than the rest. The unit is typographically separate
  now, and takes a space before a word but not before "%".

- **Three different page counts, none right.** `ROADMAP.md` said 15,
  `docs/capability-status.md` said 31, and the router defines 30.
  `tests/unit/test_frontend_page_count.py` derives it, and also checks that no
  nav link is a dead end and no route is unreachable.

- **`scripts/check-bundle.mjs`** still passes: the entry chunk went from
  197.7 kB to 205.4 kB against its 210 kB budget, and the palette and every
  page group remain separate chunks.

### Added

- **A real GitHub Action** (`action.yml`). The README advertised "GitHub Action
  (included)" when what existed was `.github/workflows/api-verity.yml`, a
  reusable *workflow*. The two are not interchangeable -- a workflow is consumed
  as a whole job and brings its own runner, checkout and Python; an action is a
  step inside a job the caller owns -- so anyone who followed that line with the
  syntax it implies got "Can't find 'action.yml'". Both exist now, and
  `docs/ci.md` says which to reach for.

  It installs the exact revision the caller pinned with `uses:` rather than
  reaching for PyPI, so the action and the tool cannot disagree about what a
  flag means -- and it works today, which a PyPI default would not, since the
  distribution is not published yet.

  `fail-on` accepts `error`, `warn` and `never`, and all three do something.
  `apiverity breaking` exits 1 on ERROR findings only, so a gate built on exit
  codes could not express `warn` at all; `scripts/count_findings.py` reads
  severities out of the emitted `result-v1` artifacts instead. `never` reports
  without failing, which is how you adopt the gate on an API that already has
  history. A malformed artifact fails the step rather than counting zero.

  The gate also reports `specs-checked`, so a run that examined nothing says so
  instead of reporting a pass -- which is how a mistyped `spec-dirs` would
  otherwise go unnoticed.

- `scripts/check_action_pins.py` now scans `action.yml` as well as the
  workflows. A composite action pins third-party actions in the same `uses:`
  syntax and ships to every consumer, so leaving it unscanned put the
  least-reviewed pin in the most widely executed file.

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
