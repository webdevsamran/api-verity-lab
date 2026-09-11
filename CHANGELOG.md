# Changelog

All notable changes. Format based on Keep a Changelog; versions are semver.

## [Unreleased]

### Fixed — thirty-seven rules the tool emits and `explain` said did not exist

`apiverity explain BRK-RESP-FIELD-REMOVED` has worked since the beginning,
because the breaking rules have had a catalogue since the beginning. The rules
in `diff/compat.py`, `diff/protocol_compat.py`, the protobuf parser and the
GraphQL introspection check had none — so a reader who received
`COMPAT-MEDIA-REMOVED` or `PROTO-WIRE-TYPE-CHANGED`, went to look it up, and was
told *"no rule with id ..."*, reasonably concluded the catalogue was incomplete
rather than that the rule was.

Found by the landing pages: `scripts/generate_landing_pages.py` lists the rules
observed firing for each protocol, and six of them had nothing to say.

- **`apiverity/diff/compat_catalog.py`** gives all thirty-seven a description
  and a remediation: twelve `COMPAT-*`, fourteen `GQL-*`, eleven `PROTO-*`.
  `docs/check-rules.md` grew from 90 rules to 127.

- **They are in the check catalogue rather than the breaking one, deliberately.**
  `rules/breaking.py`'s `CATALOG` doubles as the allow-list that
  `core/config.py` validates `severity_overrides` against, and `analyze_compat`
  did not apply overrides. Putting them there would have let a project write an
  override that passed validation and changed nothing.

- **So the override was made to work instead.** `--severity-override
  COMPAT-SERVER-REMOVED=ERROR` was accepted and applied to nothing, because the
  compat analysers decide severity per finding and never saw the map. They are
  now applied over the combined result, which is where the two analysers' own
  reasons for a severity can be overridden without threading the map into them.

- **And the config validation stopped calling them unknown.** It checked the
  breaking catalogue alone, so an override naming any `SEC-*`, `COMPAT-*` or
  `PROTO-*` rule was reported as naming a rule that does not exist. Those rules
  do exist; the override did nothing. That is a different sentence, and the one
  that was true is now fixed rather than reported.

- **`explain` groups them.** Every one answered `group: Other` with
  `documentation: docs/rule-catalog.md` — a page that does not have them.

- **The completeness test now covers the prefixes.**
  `tests/unit/test_check_catalog.py` matched `SEC|LIFECYCLE|SEMANTIC|SLO|GOV|LINT|SUPPRESSION|CONFIG|AUTHZ|SDK|GUARD|FED`,
  which is precisely why the gap was invisible for so long. `COMPAT`, `PROTO`
  and `GQL` are in it now, in both directions: a rule emitted without an entry
  fails, and an entry nothing emits fails too.

Several severities in this family are decided per finding —
`COMPAT-STATUS-REMOVED` is a WARN for a 2xx and INFO otherwise. The catalogue
records the **worst** each rule can produce, because a reader deciding whether
to gate on a rule needs to know what it can do rather than what it usually does.


### Added — twenty landing pages, none of them written by hand

A docs site's per-protocol and per-competitor pages are the ones written once
and never read again by their author. They go on asserting coverage the engine
lost and comparisons that stopped being true, to readers who arrived from a
search and have no other source — which is worse than having no pages at all,
because a page nobody checks still gets quoted.

- **`docs/for/<protocol>.md`**, one per format, listing the rules that
  **actually fire** there — measured by perturbing that format's own shipped
  fixture in each of several dozen ways, the same measurement
  `docs/rule-parity.md` uses. A rule listed was observed firing on that
  protocol in this build.

- **`docs/vs/<tool>.md`**, one per competitor that shares a lane, from
  `data/competitive-capabilities.json`: the other tool's **strengths first, in
  the evidence file's words**, then where it stops, then the capability matrix.
  The generator refuses to emit a page for a tool with no strengths recorded,
  and every page says plainly that nothing there argues for replacing it.

- **A tool with nothing in common gets no page.** Hoverfly does none of the
  shared lanes, so there is no page comparing a contract governance engine with
  a service virtualiser — and that is read off the matrix, not decided in
  prose.

- **The api-verity-lab column names a command.** The evidence file's matrix has
  a column per competitor and none for this project; it was gathered to
  describe them. Filling that gap with an unsourced `yes` in every row is the
  thing this repository exists to not do, so each claim names the command that
  provides it, `broker-publication` is an honest `no`, and a test asserts every
  command named there exists.

### Found — six rules fire and are in no catalogue

Building the protocol pages surfaced it: `COMPAT-MEDIA-ADDED`,
`COMPAT-MEDIA-REMOVED`, `COMPAT-STATUS-ADDED`, `COMPAT-STATUS-REMOVED`,
`PROTO-FIELD-REMOVED` and `PROTO-RPC-REMOVED` are emitted by
`apiverity/diff/compat.py` and `protocol_compat.py` and appear in neither
`docs/rule-catalog.md` nor `docs/check-rules.md`. A reader who receives one and
greps for it finds nothing — the defect this project has fixed in its own
README twice.

The pages name them rather than dropping them, under a heading saying they are
not catalogued, because a silent drop would make the page's count disagree with
the engine's. The catalogue entries themselves are the next change.


### Added — the plugin system, proved by installing a plugin

Six entry-point groups have been published since the registry existed, and
every test of them handed `discover()` a hand-built entry point. That tests the
loading logic and skips the part that has to work in the field: a distribution's
metadata being found by `importlib.metadata` at all, with nothing in this
repository knowing the plugin exists.

- **`examples/plugins/apiverity-house-rules`** is a complete rule pack as its
  own package — `pyproject.toml`, three rules, its own tests. Three rules a
  platform team would want and the engine deliberately does not ship:
  `HOUSE-PATH-CASE`, `HOUSE-LIST-PAGINATION`, `HOUSE-ERROR-SHAPE`.

  That is the line the system draws. The engine ships rules about what
  **breaks consumers**; a pack ships rules about what a **team has agreed to**.
  "Paths are kebab-case" is true for many teams and false for the ones who
  standardised on something else years ago — as a built-in it would be a false
  positive on their first run, and a false positive is what gets a rule
  switched off along with its neighbours.

- **One test installs it.** `tests/unit/test_example_plugin.py` builds the
  example, installs it into a throwaway virtualenv beside this package, and
  runs the CLI there: `rules --packs` finds it with its distribution as the
  source, and `validate` produces `HOUSE-*` findings. It is the slowest test in
  the suite and the only one that proves the plugin system is a plugin system
  rather than an interface with one implementation.

- **`docs/plugin-authoring.md`** is the guide: all six groups, a rule pack in
  full, what a rule owes its reader, how a broken pack is reported, the v2
  manifest and conformance kit, and the scaffold. A test holds the guide
  against the code — a group the code reads and the guide omits is a capability
  nobody finds, and a group the guide names and the code ignores is worse.

- **The example's own tests run in CI**, and the linters now cover `examples/`.
  `testpaths = ["tests"]` means the main run never reaches them, so an example
  whose tests nobody runs can stop working while every check stays green — and
  this one is the shape the guide tells people to copy.

- Writing it found a defect in the example itself before it shipped:
  `Operation.responses` is a list of `Response`, not a mapping keyed by status
  code, and the first `HOUSE-ERROR-SHAPE` read it as a mapping and reported
  every operation. A rule that fires on everything is a rule nobody keeps,
  which is exactly what the pack's own tests are for.


### Added — a playground that runs the real engine, in the reader's browser

Paste two contracts, get the breaking changes with rule ids. No account, no
upload, no server: Pyodide loads CPython as WebAssembly and `micropip` installs
the same wheel a `pip install` would, so what runs is `diff_services` and
`evaluate_breaking` — the functions the CLI calls, not a reimplementation of
them.

- **Nothing leaves the tab, and that is the point.** "Paste your API spec into
  our website" is a request most people should refuse, and most playgrounds are
  asking exactly that. This one cannot receive the text: there is no endpoint
  for it to be sent to.

- **Python loads on the first Compare, not on page load.** A docs page that
  pulls tens of megabytes because somebody scrolled past it is a docs page that
  is slow for everybody.

- **`httpx` and `flask` are not installed, deliberately, and the cost is
  stated.** Both are declared dependencies, and nothing on the analysis path
  imports either — every command that needs them imports them inside the
  function that uses them. Installing them would add a dozen wheels to a first
  load for code the page cannot reach. The trade is that a future import of
  something new fails at runtime rather than at install, so the page catches an
  ImportError and names the missing module, and
  `tests/unit/test_playground.py` fails the build the moment the analysis path
  imports something the playground does not have.

- **`graphql-core` *is* installed, because a test in a browser said so.**
  Without it the GraphQL plugin cannot even recognise an SDL document, so a
  pasted schema came back as "not an API contract in any recognized format" —
  wrong, and the least helpful thing the page could say. OpenAPI, Swagger 2.0,
  AsyncAPI, GraphQL SDL and an MCP tool manifest were each driven through the
  page and each produced findings.

- **A document that will not parse names which pane and why.** The first
  version showed a Python traceback, which is the wrong answer to a half-typed
  contract: the reader knows they are mid-edit, and what they need is the
  parser's own complaint with its line and column.

- **The page's Python is executed by the test suite**, against the real engine,
  with the page's own sample contracts. It is the only logic the page has, and
  a renamed function in `apiverity.diff` would otherwise leave an ImportError
  in somebody's browser and a green suite here.

- **`scripts/generate_playground.py` generates the manifest**, and `--check`
  runs in CI. The wheel filename, the pinned Pyodide release and the preloaded
  packages all have to agree, and a version bump with a hand-written manifest
  is a 404 on the wheel and a page that spins forever — for visitors, with
  nothing failing here.

- **The docs workflow now watches `apiverity/**` and builds the wheel it
  publishes.** It triggered only on markdown and `mkdocs.yml`, so the
  playground would have served whatever the code was the last time a doc
  changed. A step then checks the wheel actually reached the site, because a
  404 there is only visible after thirty seconds of loading Python.

Pinned to Pyodide 0.28.3, which bundles pydantic 2.10.6, PyYAML 6.0.2 and
packaging 24.2 — every runtime dependency the analysis path imports. `latest`
would move the Python and the pydantic under the page, for visitors, with
nobody here running anything.


### Added — a VS Code extension, deliberately thin

`editors/vscode` is a client over `apiverity lsp` and nothing more. Every rule,
severity and message comes from the server, so the extension cannot drift from
the CLI: there is nothing in it to drift. What it owns is the part an editor has
to own — finding the executable, saying something useful when it is not there,
and restarting cleanly.

- **A missing executable is reported, with the fix.** The usual failure modes
  are a silent no-op, which reads as "this contract is clean", and a spawn
  traceback, which says nothing about what to install. This runs
  `apiverity --version` first — a file-exists check passes for a stale shim
  pointing at a removed virtualenv — and on failure offers the install page and
  the setting.

- **Changing the executable restarts the server**, because leaving the old one
  running would show diagnostics from a tool the user has just replaced.

- **It does not activate on `*`.** Only the languages the server actually
  lints.

- **`xml` is one of them, which was a defect until a test said so.** `.wsdl` is
  `xml` to an editor, the server lints WSDL, and the first version of this
  extension did not list it — so the one contract format nobody thinks of would
  have got no diagnostics at all, silently: the client never starts, there is no
  error, and the absence of findings reads as the absence of problems.
  `tests/unit/test_vscode_extension.py` now holds the extension's document
  selector and activation events against the server's own file list, in both
  directions.

- **CI compiles it.** A second npm project in the repository that nobody runs
  `tsc` over is TypeScript whose first reader is whoever tries to install it.
  Three real errors were in the first version — a `vscode.DocumentSelector`
  where the client wants its own, an `OutputChannel` where version 10 requires a
  `LogOutputChannel`, an unused parameter — and none were visible without
  compiling. `npm audit` runs on it too, for the same reason it runs on `web/`.

- What CI does **not** do is launch VS Code, and `editors/vscode/README.md`
  says so: "it compiles and its document selector matches the server's file
  list" is the claim being made and it is checked; "it works in the editor" is
  not something this repository has established.


### Added — one language server, so the rules reach every editor

Editor support for a linter is usually five plugins, each reimplementing the
same checks against the same rules and each drifting from the tool at its own
speed. `apiverity lsp` speaks the Language Server Protocol on stdio, so VS Code,
Neovim, JetBrains, Helix, Zed and Emacs all get exactly what `validate` runs —
because it is that engine answering.

- **Diagnostics** on open, change and save: every rule, security checks
  included, with the rule id as the diagnostic `code` and a `codeDescription`
  link to the catalogue entry, so the id in the problem list is clickable.

- **Hover** shows the finding in full, including its hint. Editors truncate
  diagnostic text in the gutter, and the sentence saying what to do about it is
  usually the part that gets cut.

- **A document that will not parse is reported, not passed over.** An empty
  diagnostic list means "this is fine", and a file mid-edit that no longer loads
  is not fine.

- **It lints the buffer, and the scratch file goes beside your document.** A
  contract's `$ref: ./schemas/money.yaml` resolves relative to the file holding
  it, so linting a copy in the system temp directory would report every sibling
  reference as unresolvable — a wall of errors caused entirely by the linter.
  The scratch file is dot-prefixed and removed on every exit path, and there is
  a test for each half: the directory is left clean, and a sibling `$ref` still
  resolves.

- **Only files it has an opinion about get a publish.** Not even an empty one
  for the rest: publishing `[]` for a `.py` clears whatever another linter put
  in the problem list for a file this server never looked at.

- **Typing is debounced; opening and saving are not.** `didChange` fires per
  keystroke, and a file that stays blank for half a second after opening reads
  as a server that is not working.

- **`Content-Length` counts bytes, and the stream is binary.** Both are where a
  hand-rolled LSP goes wrong, and the symptom is an editor that hangs with
  nothing in any log. `json.dumps` runs with `ensure_ascii=False` on purpose:
  with escaping on, byte length and character length happen to agree, and the
  length computation would look correct while never being exercised.

- **The tests speak the protocol**, in real frames, and one of them launches
  `apiverity lsp` as a subprocess and reads stdout as frames — because stdout
  *is* the stream, a stray `print` anywhere on the import path breaks every
  client, and no amount of reading the source finds one a plugin introduced.

- `lsp` is excluded from the `--json` coverage gate through a third list rather
  than a third entry in the existing one. Parking it beside `report` would mean
  asserting it has `--format`, which it must not have, and the assertion would
  then be satisfiable by adding a flag that broke the protocol. Its own check
  asserts the opposite: that the command declares no output flags at all.

Not completion, not formatting, not go-to-definition — there are editor plugins
that already do those well for OpenAPI, and a thin one here would get in their
way for no gain. `docs/lsp.md` has the client configuration for each editor.


### Added — a verified tool surface, handed to the benchmark that can measure agents against it

This project answers "is this tool surface sound?". It cannot answer "will an
agent use it correctly?" — that is a measurement over agents, and
[tooltrace-bench](https://github.com/webdevsamran/tooltrace-bench) is the
sibling project that makes it. `apiverity agent-tasks` is the hand-off.

- **The contract is the scorer.** For each tool in a verified MCP manifest, one
  task: given the contract, write the arguments for a call to it, graded by a
  `json_schema` assertion pointed at **that tool's own `inputSchema`**. A
  hand-written expected answer would be a rubric that can disagree with what the
  service publishes, and then the benchmark measures the rubric.

- **Every task carries a reference solution**, because `tooltrace task test`
  refuses one without: nobody has shown an unproven task is solvable, and an
  unsolvable task in a benchmark is a score everybody loses for the author's
  reason. That objection is this project's own ethic arriving from the other
  side. The solution comes from `apiverity.fuzz.generate.generate_valid` — the
  generator `apiverity test` already uses — rather than a second
  schema-to-example implementation that would eventually disagree with the
  first.

- **A test checks the reference solution against the assertion that grades it.**
  That is a fidelity check on the contract model, not on the exporter: the
  solution is generated from the `SchemaNode` model and the scorer is the raw
  JSON Schema from the manifest, so any constraint the model drops appears as a
  reference answer that fails its own check.

- **It refuses to export a surface that did not pass.** Benchmarking agents
  against a contract this tool reports errors on makes every failure ambiguous
  between the agent and the manifest. `--allow-findings` overrides it and writes
  the findings into the pack's README, where whoever reads the scores will see
  them.

- **It refuses to turn a poisoned description into an instruction.** You cannot
  ask an agent to follow a description that is an injection and then score it
  for compliance — the correct behaviour is to refuse, and this task shape would
  mark that wrong. Measuring resistance is a different shape, and pretending
  this one does it would be worse than not shipping it. `--include-flagged`
  exports them with the rule id attached, for an author writing that shape by
  hand.

- **It refuses to export a task nothing can fail.** A tool declaring
  `{"type": "object", "properties": {}}` constrains nothing: every submission
  validates. `fixtures/mcp/tools_v1.json` has one, so the check is exercised
  rather than hypothetical, and the skipped tools and their reasons travel in
  the pack's README — a reader comparing tool count to task count otherwise
  assumes the difference was a bug.

- **Built against the *published* schema, not a working tree.** tooltrace-bench's
  checkout has `tool_descriptions` and `attachments`; its published schema does
  not, and `tool_descriptions` would be the obvious way to measure resistance to
  a poisoned description. Because the task schema takes
  `additionalProperties: true`, a pack using one would still validate and the
  runner would ignore it. The schema is vendored under `schemas/vendor/` with
  its digest and fetch date, the way the OAI's Arazzo schema is, and a test
  fails if either field is used — and fails the other way when one becomes
  published and the decision is worth revisiting.

- Verified end to end against tooltrace-bench 0.3.0 on 2026-09-11:
  `tooltrace task validate` returns `{'valid': 2, 'errors': []}` and
  `tooltrace task test` returns `{'passed': 2, 'problems': []}` for the pack
  generated from `fixtures/mcp/tools_v1.json`. The second line is the loop
  closing: this project's generator, graded by this project's verified contract,
  inside the sibling project's runner.


### Added — the README's headline animation is generated, not recorded

A project's demo GIF is a picture of whatever the tool printed on the author's
machine on one afternoon. It ages silently: a rule id gets renamed, output
gains a column, and the animation goes on showing the old thing to everybody
who lands on the page. This repository already fixed exactly that for the
README's text blocks, and then left the picture unguarded — by not having one.

- **`scripts/record_demo.py`** runs the demo's commands through
  `apiverity.cli.main` in process, captures stdout verbatim, and renders
  `docs/demo.svg` and `docs/demo.cast` from it. `--check` runs in CI, so the
  recording cannot keep showing output the code stopped producing.

- **An animated SVG, not a GIF or a hosted player.** It needs no player, no
  third-party host and no JavaScript; GitHub renders it inline, and an
  air-gapped clone still has it. `docs/demo.cast` is the same session as an
  asciinema v2 recording, for anyone who wants to replay or upload it.

- **The demo is `apiverity --version`, then `breaking` over two MCP tool
  manifests.** An agent's tool surface through the command an OpenAPI document
  goes through, emitting `BRK-RPC-REMOVED` next to `BRK-MCP-READONLY-HINT-CLEARED`
  — which is the project's whole claim, and the one thing a recording can show
  and a paragraph cannot.

- **Nothing in it depends on `animation-fill-mode`, because that did not work.**
  The first encoding gave each row a one-frame animation with `animation-delay`
  set to its reveal time and `forwards` to hold it. In a browser, rows past
  about two seconds reported `playState: "finished"` with a computed opacity
  still `0`, and the recording stopped three lines in — visible only by putting
  the file in front of a renderer. Every row now runs the same infinite
  animation of the full duration and flips opacity at its own keyframe, so
  there is no state to hold after it ends. It also loops, so a reader arriving
  mid-play sees it from the top rather than a finished screen.

- **`prefers-reduced-motion` shows the whole transcript at once.** An animated
  README image is exactly what that preference exists for.

- **Output wraps at the column, the way a terminal wraps it** — not on words.
  A reader of the recording runs the command themselves and sees the terminal's
  wrapping, not `textwrap`'s.

- **A transcript that outgrows the frame fails the build.** Truncating would end
  the recording mid-finding, which reads as a crash; the error names the fix
  (shorten a scene) rather than raising the cap.

- The `<desc>` carries the transcript, so a reader who cannot see the image gets
  the session rather than the words "terminal recording".


### Added — one line to install it, and an honest account of every other channel

The README's first instruction was `pip install api-verity-lab`. That does not
work: the package is not on PyPI, publishing is guarded behind a repository
variable, and the first thing a reader did with this project failed.

- **`install.sh` and `install.ps1`.** `curl -fsSL …/install.sh | sh`, or
  `irm …/install.ps1 | iex`. Each does exactly one thing — find a Python 3.11
  or newer — and then runs `scripts/install.py`, fetched from the same
  repository and ref. One installer, two bootstraps: two hand-maintained
  installers drift, and the drift is only ever found by whichever platform the
  author does not use.

- **The wheel is checksummed against the release.** `scripts/install.py`
  resolves the latest release (or `--version`), downloads the wheel, hashes it,
  and compares against the digest GitHub reports for that asset. A mismatch
  installs nothing and says so.

- **And the docs say what that check is not.** It is not a signature: GitHub
  computes that digest from the bytes it stores, so anyone able to replace the
  asset changes both. It catches truncation, a mangling proxy, and a mirror
  serving something else. The integrity story with teeth is the Sigstore
  attestation the release workflow already produces, and the installer prints
  the `gh attestation verify` line rather than implying the hash did that job.

- **A release with no declared digest still installs, and says nothing was
  compared.** The digest field postdates this project's first release. Refusing
  such a release would treat a gap in GitHub's metadata as evidence of
  tampering; installing quietly would let the absence read as a pass.

- **`pip install --user` is dropped inside a virtualenv.** Running an installer
  inside an activated venv is an ordinary thing to do, and `--user` there is a
  hard error — "User site-packages are not visible in this virtualenv" — which
  reads as the installer being broken. Found by the end-to-end test that
  installs into a throwaway venv.

- **A dropped connection is retried.** Release downloads redirect to a CDN, and
  a reset connection or a timed-out TLS handshake there happened while this was
  being written. Three attempts, spaced; an HTTP error is *not* retried, because
  a 404 is an answer.

- **The PowerShell bootstrap passed the interpreter to itself.**
  `$parts[1..($parts.Length - 1)]` is `1..0` for a one-element array, which
  PowerShell evaluates descending and which therefore yields element 0 — so
  `python` was handed its own path as an argument and tried to open a file named
  after the first letter of it. Found by running the script, not by reading it.

- **Progress output is flushed.** stdout is block-buffered when it is a pipe and
  stderr never is, so the error explaining a failure arrived *ahead* of the lines
  saying what was being attempted — backwards, in the one output somebody pastes
  into an issue.

- **`docs/install.md` lists every channel with whether it works today.** A
  published install matrix full of channels nobody can use is a worse artefact
  than a short one. PyPI is marked not-yet with the exact step that unblocks it
  (a Trusted Publisher registration, which is a form on the account that owns
  the name and cannot be done from a repository). Homebrew, Scoop and winget are
  marked absent with the reason: they want a self-contained executable, and
  serving them honestly needs either a per-platform frozen binary with its own
  test matrix or a formula carrying a checksummed resource block per dependency.
  A formula that has never been installed is a claim, and this project does not
  publish those. Both gaps are recorded in `PRODUCT_GAPS.md`.

- The installers are **run** in `tests/unit/test_install_scripts.py`, against a
  local server speaking the shape of GitHub's releases API and serving a real
  wheel: resolution, download, checksum verification, the refusal on mismatch,
  and an install into a throwaway virtualenv. The shell bootstraps are executed
  too — `sh` on ubuntu and macos, PowerShell on windows, which the
  `platform-matrix` job runs on every pull request. An installer is the one
  piece of a project whose failures the author never sees, because it runs on
  machines that do not have the project on them.


### Added — the contract read out of the application, so the file cannot go stale

Every check in this project is only as true as the document it reads, and the
document is the thing that goes stale. A service whose handlers changed and
whose committed `openapi.yaml` did not passes all seventy-four rules and
describes something that no longer exists.

- **`apiverity app module:attribute`** reads the document the application
  itself produces. The target is named the way `uvicorn` and `gunicorn` name
  it, because that string already exists in every deployment that runs the
  application.

- **`--against openapi.yaml` is the check worth having.** It answers the
  question the committed file cannot answer about itself: is it still true? A
  stale file fails the run whether or not the difference is breaking — an added
  operation breaks nobody and the file is still wrong, and a command that
  passed there would catch only the staleness that happened to be breaking,
  which is the smaller half of it.

- **Duck-typed on `openapi()`, not on `isinstance(app, FastAPI)`.** The class
  check would make FastAPI a dependency of a tool that does not need one, and
  would refuse an application that produces exactly the right document because
  its class belongs to somebody else. Any object with an `openapi()` method —
  or an `openapi` attribute holding the document — is read.

- **The document is copied before it is returned.** FastAPI builds it once and
  hands back the same object on every call, so a caller who edited what this
  returned would be editing the running application's published schema, and the
  edit would be invisible: the next read returns the object that was edited. A
  test in `tests/unit/test_app_adapter.py` found that by mutating the result and
  reading again.

- **What it does not do is stated as plainly as what it does.** It does not
  start the application, bind a port or send a request — the document is built
  in process from the route table. So the comparison is reported under
  `committed`, not `drift`: `apiverity drift --base-url` is the command for
  asking what a *running* service does, and naming this one drift would claim a
  measurement it never made. Importing an application runs its top-level code,
  which is the whole cost of the feature and is documented rather than buried.

- **One adapter ships, not six.** The roadmap entry listed FastAPI, Express,
  NestJS, Laravel, Spring and gin. An adapter is only worth writing where this
  tool shares a runtime with the framework and can hold the application object
  in memory — that is Python, and in Python one adapter covers every framework
  producing an OpenAPI document. For the rest, a maintained generator already
  exists and the "adapter" is `their-generator > openapi.json && apiverity …`,
  which needs no code here. `docs/framework-adapters.md` gives the table.
  Shipping five thin wrappers would have added five things to be out of date
  with and no capability.

- `fastapi` joins the `dev` extra, for the reason `graphql-core` and `pyjwt`
  are already there: without it the only tests that prove the adapter reads a
  real framework's document would skip, and a suite that silently skips its
  coverage of a feature is indistinguishable from one that passes it.


### Added — the gate runs where merges happen

A contract gate that runs only on `pull_request` proves something about that
branch merged into the base *as it was when the check ran*. It proves nothing
about what actually merges.

Two pull requests, each individually safe: one removes the last declared
consumer of a field, the other removes the field. Both pass, both merge, and
nothing ever evaluated the combination — because the merge queue is the only
place that combination is built.

- `ci.yml` and `api-verity.yml` run on `merge_group` as well as
  `pull_request`. Both, not one: the merge queue is the last gate, and finding
  out there is finding out after review.

- **The action can find a base ref in a merge queue.** `github.base_ref` is
  empty for a `merge_group` event — it is not a pull request — so the action
  reached its "no base ref to diff against" branch and exited 1. It could not
  be a required check in a merge queue at all: safe, in that it failed rather
  than passing vacuously, and useless. It reads
  `github.event.merge_group.base_ref` now and strips the `refs/heads/` prefix
  everything downstream does not expect.

- The PR comment step stays scoped to `pull_request`. There is no pull request
  to comment on in a queued run, and a step that tried would fail the gate for
  a reason that has nothing to do with the contract.

- **The five required job names are pinned.** Branch protection matches them
  byte for byte: rename one and the required check waits forever for a name
  nothing reports. `tests/unit/test_required_checks.py` fails in both
  directions — a required job that disappeared, and a job added to `ci.yml`
  that nobody decided about.


### Added — a real OIDC identity provider

`IdentityProvider` has been a `Protocol` with one implementation — a lookup in
the server's own token table — and a docstring saying "OIDC/SAML adapters
implement this". None did, so a team with an identity provider had an
abstraction and no way to use it.

- **Four checks, and skipping any one turns this into a base64 decoder.** The
  signature against the issuer's JWKS by `kid`; `iss`, because a correctly
  signed token from another issuer is a correctly signed token from somebody
  else; `aud`, because an access token minted for another service is the
  confused-deputy problem in its original form; and `exp`, with no grace period
  unless one is configured.

- `alg: none` is rejected before anything else, along with every algorithm
  outside the allow-list. The specification permits an unsigned token and a
  library that honours it will verify one. The defaults are asymmetric only:
  with HMAC the verification key is the signing key.

- **Roles are mapped, never defaulted.** A subject whose claim matches nothing
  gets no identity at all — not `viewer`, which would let anybody the issuer
  mints a token for read every contract in the org.

- **Signature checking is not reimplemented.** It calls PyJWT (`[oidc]` extra,
  and a dev dependency so the tests do not silently skip). A hand-rolled RSA
  check in an authentication path is the last place to be clever, and a wrong
  one fails open. The library is asked for the signature and nothing else,
  because two places checking `aud` with two notions of what it should be is
  how one of them ends up not checking.

- A token with no `kid`, or an unknown one, is rejected rather than tried
  against every key — that is how a rotated-out key stays valid. A `kid` missing
  from the cache triggers one forced refetch first, so a rotation is not an
  outage. A discovery document pointing `jwks_uri` outside the issuer is
  refused.

- **SAML is not implemented, and the reason is written down.** It is XML
  signature verification, a larger and much sharper problem, and a half-done
  one would be worse than none.

### Changed — the server is assembled in a module, not a shell string

`docker/entrypoint.sh` built the application from an inline `python -c` block:
it grew with every setting, was tested by nothing, and failed at container
start with a traceback about a heredoc. `apiverity.server.launch` is that logic
as a module, covered by tests, and the supported way to start the server
without Docker.

It **refuses to start on half an OIDC configuration.** Any `VERITY_OIDC_*`
variable commits the server to a complete one; an issuer with no audience is a
startup failure naming what is missing, rather than a fallback to local tokens
with a warning nobody reads. A server meant to use your identity provider and
quietly not using it looks exactly like a working one.

Turning local tokens off with no issuer configured is refused too: the server
would authenticate nobody.


### Added — air-gapped install, a Helm chart, and a checkable egress claim

- **`docs/egress.md` is generated from the source.** `docs/self-hosting.md` has
  said "no telemetry, no phone-home, no auto-update" since it was written, and
  that was a sentence somebody typed. `scripts/generate_egress_map.py` walks
  the package with `ast` and lists every call that can open a socket — 23 sites
  across 17 modules — with the flag that causes each. CI fails when the
  document and the code disagree.

  A module that acquires a call site with no stated trigger is named. A trigger
  naming a module that no longer has one is named too — a published explanation
  of something that does not happen is the same defect as an unexplained thing
  that does. An HTTP library the scanner cannot follow is reported as
  unrecognised rather than silently omitted, because the alternative is a table
  that quietly stops being complete.

- **A Helm chart** for the self-hosted server, with defaults that already suit
  a disconnected cluster: an image reference with no registry host, and
  `IfNotPresent` so it does not reach for a digest it already has.

- **It refuses `replicaCount > 1` rather than rendering it.** The server keeps
  everything in one SQLite file, and two replicas writing to one ReadWriteOnce
  volume is data loss — so a `--set replicaCount=3` that rendered successfully
  would be the chart agreeing to something that cannot work. The rollout
  strategy is `Recreate` for the same reason: a rolling update holds the file
  in two pods for the length of the rollout.

- **The egress NetworkPolicy is off by default**, and says why. The server
  needs no egress; the reason it is off is that a cluster whose CNI does not
  implement NetworkPolicy applies it cleanly, reports success, and enforces
  nothing. An enforcement you believe you have is worse than one you know you
  lack.

- `tests/unit/test_helm_chart.py` holds the chart against the application:
  every `VERITY_*` it sets is one the code reads, the probe path is a real
  route, and `appVersion` matches the package. That caught `VERITY_LOG_LEVEL`,
  which the first draft set and no line of the application reads.


### Added — personal data, found by shape and never reported by value

- **`security/pii.py`** recognises what has a shape worth trusting: a card
  number that passes Luhn, an IBAN that passes mod-97, an email, an IP address
  that actually parses. A sixteen-digit number failing Luhn is an order
  reference, and `999.1.1.1` is a version string.

- **Names, addresses and dates of birth are deliberately not detected**, and
  the module says so. They have no shape — "Paris" is a city and a person,
  `1990-03-14` is a birthday and a release date — so a detector for them is
  wrong most of the time, which trains people to ignore the times it is right.
  The field-name rules in `traffic/redact.py` cover the other half: a field
  *called* `date_of_birth` is redactable by name even though its value is not
  recognisable.

- **`apiverity capture` redacts it before the HAR is written**, with a
  replacement distinct from the credential one so a reader of a corpus can tell
  which rule fired.

- **`DRIFT-RESPONSE-PII`** reports personal data at a path the contract does
  not classify. Returning an email from an endpoint that says it returns one is
  the endpoint working, and firing on that would produce hundreds of findings
  per contract; the *mismatch* — `nickname: string` on the wire carrying an
  address — is the thing worth a person's attention. The kind, path and length
  reach the finding; the value never does.

### Fixed — the classification annotation did nothing

`SEC-SENSITIVE-FIELD` has always read `getattr(schema, "data_classification",
None)`, and `SchemaNode` never declared that field — so the value was
unconditionally `None`, the rule fired whatever the document said, and its own
hint told people to add an annotation that changed nothing.

Two defects, in fact. It also read the attribute off the **parent** object
rather than the sensitive property, so annotating the field itself would not
have silenced it even once the field existed.

`SchemaNode.data_classification` is declared and populated from
`x-data-classification` now, and the check reads it on the property.


### Added — `apiverity federation`

An SDL diff compares two documents. In a federated graph that is the wrong
unit: a subgraph is one contributor to the schema clients actually query.

```diff
 type Product @key(fields: "id") {
   id: ID!
-  price: Int
+  price: Int @inaccessible
 }
```

Same field, same name, same type, same subgraph. `apiverity diff` reports no
removal — and `price` is gone from the supergraph, so every client loses it.

- Six rules comparing a subgraph with its previous revision (`--against`): a
  lost or changed `@key`, `@inaccessible` added, `@shareable` removed,
  `@external` added, `@override` moved.

- Four rules over a set of subgraphs: an unshareable duplicate, an entity keyed
  in one subgraph and not another, a dangling `@external`, a `@requires` naming
  a field nothing defines.

- **It is not a composition, and says so in every run.** `rover` and
  `@apollo/composition` compose, properly; a second implementation whose output
  looked like theirs and was computed differently is what this project refuses
  to build for Spectral's rules too. So it reports preconditions, and the
  artifact carries a note that a clean result is not a claim that composition
  succeeds — because the alternative is a tool that reports nothing and gets
  read as a guarantee.

- **Key fields are exempt from the duplicate rule.** `@key` fields are
  implicitly shareable in Federation v2 and every subgraph keying the entity is
  *required* to declare them. The first version of the rule reported
  `Product.id` on every correctly federated graph there is, which is how a rule
  gets switched off before anybody reads its second finding.

- **An incomplete run looks like a broken graph**, and the findings say so.
  `FED-EXTERNAL-DANGLING` names a missing subgraph as the likelier cause in its
  hint, and `FED-REQUIRES-UNKNOWN-FIELD` is a WARN rather than an ERROR for
  exactly that reason: from inside the run, a subgraph nobody passed and a wrong
  selection are indistinguishable.


### Added — house rules in YAML, without forking

`apiverity validate openapi.yaml --policy-file house-style.yaml`.

[Rule packs](docs/rule-packs.md) are the right answer for a rule with real
logic in it and the wrong one for *"every path must be kebab-case"* — which is
most of what an organisation wants to enforce, and does not justify a Python
package, a release process and somewhere to publish it.

- **A fixed vocabulary, not an expression language.** Ten operation fields,
  five service fields, seven predicates, each reading one part of the
  normalized contract model. No `eval`, no JSONPath. That ceiling is
  deliberate: a general evaluator would be a second engine inside this one —
  the same objection the Spectral importer makes — and would let somebody write
  a rule this project cannot explain, in a tool whose claim is that every
  finding has a stable id and a reason. When it runs out, write a pack.

- **An unknown word fails at load time**, by name, with the list of what is
  available. A DSL that accepts an unrecognised selector, matches nothing and
  reports clean has handed a team a gate they believe they have. A regex that
  will not compile is refused there too, rather than at check time against the
  first contract somebody runs it on.

- **`matches` on an absent field fails.** `absent` is the predicate for asking
  about that; conflating the two would make `matches` silently pass on every
  operation that omits the field.

- **Exemptions are operation keys, not globs.** A pattern that grows to cover
  six operations nobody reviewed is the escape hatch becoming the policy. For
  an exemption with an owner, a reason and an expiry, suppressions already
  exist.

- `apiverity rules --policy-vocabulary` prints the vocabulary from the same
  tables the loader validates against, so what the documentation says is
  available cannot disagree with what is accepted. The artifact names the
  policy files that ran, because two runs over one contract reporting different
  findings should say why.

- Named `--policy-file` rather than `--policy`: `regression --policy` already
  means a performance budget, and one flag with two meanings across two
  commands is a trap.


### Added — rule packs are discovered, not hard-coded

- `apiverity rules --packs` lists every pack this installation can run, with
  the distribution and version each came from.

- **A third-party pack now reaches the engine.** The `apiverity.rules`
  entry-point group has existed since the plugin registry did, `apiverity
  plugins` listed it, and `PolicyEngine` was handed a hard-coded pair of
  built-in packs by its only caller — so a team's own pack was discoverable and
  ran nothing.

- **There is no registry to operate, deliberately.** A rule pack is Python and
  Python already has a distribution channel; a pack on PyPI declaring the entry
  point is discoverable by every installation that installs it. `source` is the
  distribution name and version, which is what a reader needs to answer "where
  did this rule come from" and exactly the field a second index would have had
  to invent.

- **Two states it will not hide.** A pack that raises on import is listed under
  `failed` with the error, because skipping it silently leaves a team believing
  their pack is running. A rule id two packs both claim is reported as data
  naming both — `PolicyEngine` raising on that is right for the engine and
  wrong for the listing whose job is to say which pack is the problem, and
  neither side is dropped, since silently keeping one would run a gate nobody
  configured. Either state exits 1.


### Decided — eBPF capture is evaluated and declined

The roadmap asked for Keploy's approach to be studied as prior art *before*
committing to anything. [`docs/ebpf-evaluation.md`](docs/ebpf-evaluation.md) is
that study, and the answer is no.

Keploy checked 2026-09-11: 18,452 stars, Apache-2.0, `v3.6.57` released that
morning, `github.com/cilium/ebpf v0.21.0` in its `go.mod`. The public tree
carries only `pkg/core/proxy/tls`, consistent with the recorded position that
its v3 parsers compile in from a private repository — so the part worth
studying is the part that is not there.

What eBPF buys is real: no client reconfiguration. What it costs here is Linux
only against a three-platform test matrix, `CAP_BPF` where nothing else in this
tool asks for more than permission to open a socket, and uprobes on every TLS
library's read/write symbols per version per build — including Go's, which
links its own.

The deciding argument is the failure mode. A probe attached to the wrong symbol
records nothing and exits zero, and an empty corpus because nothing happened is
the same file as an empty corpus because the probe saw nothing. That is the
class `SAFETY_MODEL.md` names as categorically worst. `apiverity capture`
cannot fail that way: traffic either goes through it or does not reach the
target.

The three things that would reverse the decision are written down rather than
left implicit.


### Added — the migration guide reaches the finding that blocks

A breaking-change finding says *what* broke. It does not say what to do
instead, and the person who knows that is the API owner — who very often wrote
it down next to the operation, in a field nothing read.

- `breaking` attaches the owner's guidance to every finding about that
  operation (`metadata.migration_guide`) and lists it once per operation under
  `migration_guides`. Eleven findings about one removed operation should not
  print the same link eleven times.

- `--summary` prints it **above** the generic advice, because the API owner's
  own guide beats anything this tool can say about their API.

- It is read from the **old** contract. The operation being broken is the one
  consumers wrote against; a guide added in the same change that breaks them
  was not published when they needed it.

- Both spellings are understood: the structured `x-deprecation` block and the
  flat `x-migration` / `x-sunset-link` extensions in common use.

- It is never fetched. A URL in a contract is an address somebody else
  controls, and this project does not request addresses the caller did not
  choose.

- The approvals view in the dashboard has a **Migration guide** column. The
  server has stored the field since the table existed and the frontend has
  always typed it; nothing rendered it. An approval without one reads "none
  given" rather than blank — a breaking change approved without saying what a
  consumer should do about it is a fact worth seeing.

### Fixed — two lifecycle rules fired on contracts that satisfy them

`LIFECYCLE-DEPRECATED-NO-SUNSET` and `LIFECYCLE-DEPRECATED-NO-GUIDANCE` read
only the flat extension keys. A contract using the structured form —

```yaml
x-deprecation:
  sunset: "2027-01-01"
  guide: https://docs.example.com/migrating-to-v2
```

— was told it *names no retirement date* and *points nowhere* while doing both.
That is the kind of false positive that gets a governance rule switched off
along with its neighbours. Both rules read the structured block now, and both
still fire on a contract that genuinely says nothing.


### Added — `apiverity import-rules`, for a Spectral ruleset

Spectral owns rule-catalog linting, and a team that has a ruleset has invested
in it. Migration cost is the real competitor.

- **It is a report, not a compatibility layer.** This does not run Spectral's
  rules. A Spectral rule is a JSONPath `given` plus a function over the
  document, and reimplementing that would put a second engine inside this one,
  producing findings that look like this project's and were computed by
  different code — exactly what "one contract model every engine reads" exists
  to avoid.

- **Four answers, and the useful one is not the first.** `covered` names the
  equivalent rule here. `not_covered` is the backlog, and it is what the run
  exits 1 on: a tool asking to replace another that reported only its own
  coverage would be claiming a completeness it does not have. `not_expressible`
  is the rules about the *document* rather than the contract — a description's
  wording, a path's spelling, a tagging convention — which are good rules this
  project is not behind on, because they do not survive compiling a document
  into a normalized model. `disabled` names the rules the ruleset turns off,
  since a migration that silently re-enabled one has changed somebody's gate.

- **`extends` is counted separately and said out loud.** `extends: spectral:oas`
  is sixty-odd rules the file never names; a report counting only the named ones
  describes a fraction of the gate and reads as though the migration is nearly
  done.

- **Matching errs toward the backlog.** Spectral rule names are conventional,
  not standardised, so a custom rule lands in `not_covered` even when this
  project happens to check the same thing. Over-reporting the backlog is the
  safe direction; claiming coverage of a rule nobody matched is not.

- A test asserts every rule id the mapping claims to cover actually exists, and
  that no rule is classified twice. YAML 1.1 parses a bare `off` as `False`, so
  both `operation-tags: off` and `severity: off` arrive as booleans and both are
  recognised — a check against the string `"off"` alone catches neither.


### Added — `apiverity capture`, a recording proxy

`drift --corpus` and `infer` both want real traffic, and until now the only way
to get some was to already have a HAR from somewhere else.

```bash
apiverity capture --target https://staging.example.com --out corpus.har
apiverity drift openapi.yaml --corpus corpus.har
```

- **Redaction happens before the write, not after.** A recorder that wrote the
  HAR and then sanitized it has already put an `Authorization` header on disk —
  and on a crash between the two, left it there. Headers, query strings, request
  URLs and bodies are redacted in memory; the entry appended to the log is the
  redacted one. The client still gets the real response, because it asked and
  this is a proxy.

- **What it refuses to be.** An open relay: every request goes to the one
  `--target` the run named. Reachable from the network: it binds `127.0.0.1` and
  refuses anything else without `--i-know-this-is-exposed`, because an
  unauthenticated recording proxy on a routable address is a credential
  collector that writes to a file. A TLS interceptor: there is no `CONNECT`,
  since tunnelling would either record nothing or require issuing certificates
  for hosts this process does not own.

- **Every skip is named, in the file.** Oversized bodies, non-text content
  types, an upstream that never answered, traffic that arrived after the entry
  limit — counted in the JSON output *and* written into the HAR's own
  `log.comment`. A corpus whose gaps are described only in the console output of
  the run that made it has gaps that read as facts about the service.

- An empty corpus is still written. Nobody sent anything through is a fact about
  the run; a missing file reads as a crash.

### Fixed — three things found by recording real traffic through it

- **`request.url` carried the credential that `queryString` redaction had just
  removed.** One field over, in the same entry. The URL is rebuilt from the
  redacted parameters now. Found by the test that reads the written file back.

- **A secret inside an opaque string value survived.** Field-name redaction
  cannot see into a value, so a service echoing a request body into a field put
  `{"password": "hunter2"}` in the corpus intact. JSON bodies get a second pass
  over each string value — over the *values*, not the serialized document, since
  in serialized form the escaping (`password\": \"x`) is exactly what hides it.

  `DEFAULT_PATTERNS` gained two things in the process: `password`, which
  `sensitive_body_fields` already treated as sensitive so the two lists
  disagreed about the same word; and an optional quote around the name, since a
  credential inside a string arrives as JSON or YAML where the quote sits
  between the name and the separator.

  What still cannot be caught — an unlabelled secret in free text — is stated in
  the module and pinned by a test, because a recorder claiming to catch
  everything is the claim that gets one committed.

- **`--max-entries` was a threshold, not a cap.** The poll loop notices the
  limit a tenth of a second later, by which time more requests have arrived, so
  asking for two recorded three. The cap is enforced where the entry is
  appended, and what arrives after it is counted under `skipped` rather than
  silently absent.

- `cmd_capture` installed a `SIGINT` handler unconditionally, and
  `signal.signal` raises on any thread but the main one — so running the command
  from a thread killed the run before it recorded anything and never wrote the
  corpus at all.


### Added — an onboarding tour that will not point at nothing

Four steps, on a first visit, lazily loaded — so a returning reader never
fetches the chunk at all.

- **Steps are filtered against the document before anything renders.** A step
  anchored to a selector that matches nothing would leave a highlight box at
  the top-left corner and a caption describing a control the reader cannot
  see: worse than not running, because it teaches them the tour is lying about
  the interface it exists to explain. The counter counts what survived.

- **A tour with no surviving steps does not run, and is not marked as seen.**
  Nothing was shown, so nothing was learned, and marking it seen would spend
  the one chance it has.

- **A dismissal that could not be recorded says so.** `localStorage` refuses in
  a private window or with site data blocked; the tour reports it on the step
  you dismissed from rather than silently returning every visit and leaving you
  to conclude the dashboard is broken. A *read* that throws is treated as
  already seen — an undismissable tour that returns on every load is the worse
  failure.

- **About → Take the tour again.** A tour that runs once with no way back is a
  tour nobody sees: the people most likely to skip it in their first ten
  seconds are the ones who later want it.

Arrow keys move, Escape dismisses, focus enters the panel and returns to where
it was. Entry chunk 214,396 B against the 220,000 B budget; the tour is a
3.1 kB chunk of its own.


### Added — saved views

Filters were already serialized into the URL, so a view was shareable by
copying the link. What was missing was a name for a link you want back.

- **A saved view stores a name and the hash route, and nothing else.** The URL
  already carries the whole view, so storing more would be a second
  representation of the same state — and the two would disagree the first time
  a filter was added. The default name is the page plus its filters, because
  "contract" and "contract filtered to errors" are two different views.

- **Every entry is a real link**, so middle-click opens a tab and right-click
  copies the URL. That matters: the link is the shareable form of a view, and
  the list itself is per-browser.

- **The panel says where they live.** `localStorage`, which means this browser
  and not your account or your other laptop — said in the UI rather than
  discovered by opening the dashboard somewhere else.

- **Both storage failures are handled, differently.** `localStorage` does not
  merely come back empty in a private window; the accessor throws. A read that
  fails gives an empty list and the dashboard keeps working. A write that fails
  is reported — saying nothing is how somebody finds out on their next visit
  that what they saved was never saved. A stored value this feature did not
  write is discarded rather than crashing the read.


### Added — guardrails on what a generated payload may carry out

- **`GUARD-PAYLOAD-CREDENTIAL`.** `SEC-RESPONSE-CREDENTIAL` reads what comes
  back from a service. This is the other direction, and it is the one nobody
  checks because synthetic data feels safe by construction.

  It is not. A generated payload is built from the contract, and a contract is
  a document somebody wrote: an `example`, a `default`, an `enum` member.
  `apiverity validate` reports committed secrets in examples precisely because
  they happen — and when one does, a fuzz run reads it out of the repository
  and posts it to whatever `--base-url` names. That is not a leak the tool
  found; it is one the tool performed.

  So the check runs **before** the request and the payload is not sent. A WARN
  beside a request that already went out is a finding about something nobody
  can take back. The finding names the kind and the JSON pointer, never the
  value — the same rule `security/leakage.py` follows, for the same reason.

  `--allow-credential-payloads` sends it anyway and still reports it, at WARN:
  a contract may legitimately declare a token field with a realistic example.

- **`GUARD-PAYLOAD-SIZE`.** `maxLength: 10000000` is a legal schema, and a
  boundary generator asked for the largest valid string produces ten megabytes.
  Sending it is a denial of service somebody wrote by running a test suite.
  Refused above 256 kB, raisable with `--max-payload-bytes` — and refused
  rather than truncated, because a payload silently shrunk is a case that did
  not test what it says it tested.

- A refused case is reported as `error`, not `fail`, and the run continues: a
  run of four hundred should lose the one case that is unsendable, not the
  other three hundred and ninety-nine. It establishes nothing about the target,
  which is what `error` means here.

- **Deliberately not guarded: injection payloads.** A generated value that
  looks like SQL or a shell fragment came out of the contract's own `pattern`
  or `enum`, so refusing to send it would refuse to test what the contract says
  the operation accepts — and a service that mishandles it has a bug the run
  exists to find. The guardrail is about what this tool must not *do*.


### Added — taking a view out of the dashboard

- **CSV, PNG and the browser's own PDF**, on the views that have something to
  take. The drift findings table and the performance table export to CSV; the
  blast-radius graph exports to CSV and PNG; every view prints.

- **The CSV will not execute.** Every string worth exporting here came from
  somewhere else — a finding message quotes a spec file, an operation key
  quotes a path — so "the export contains what the document said" is exactly
  the property that makes it dangerous. A cell beginning with `=`, `+`, `-`,
  `@`, a tab or a carriage return is a formula to Excel, Sheets and
  LibreOffice, and each is prefixed with an apostrophe *before* RFC 4180
  quoting. Order matters: quote first and the apostrophe lands inside the
  quotes, where the spreadsheet has already decided the cell is a formula.

- **The PNG carries the chart's appearance.** These charts are styled entirely
  by the external stylesheet — `.blast-edge`, `.blast-node`, each resolving a
  token — and a serialized SVG carries none of it. Every computed presentational
  property is inlined onto a clone before serializing, and a chart embedding an
  `<image>` or `<foreignObject>` is refused rather than exported wrong.

- **"Print / Save as PDF", not "Export PDF".** The browser renders it; this
  bundle does not. A real PDF writer is 300 kB against an entry budget of 220
  kB with nine to spare, and a button claiming a capability the code does not
  have is the thing this project exists to not do. The export module is a route
  chunk (2.8 kB); the entry grew 1.3 kB.

- The performance chart gets no PNG button: it is drawn with CSS widths, not
  SVG, and its CSV carries every number the bars encode. Offering a button that
  cannot work is worse than not offering one.

### Fixed — every exported PNG would have been transparent

Found by exporting one in a browser and reading the corner pixel.

The background rect exists so a light-on-dark chart is not invisible in a
viewer that assumes white. It took its colour from
`getComputedStyle(document.body).backgroundColor`, with `|| '#ffffff'` behind
it — and that fallback can never fire, because the value is
`rgba(0, 0, 0, 0)`, which is a non-empty string.

Two browser behaviours conspire. CSS propagates the body's background to the
canvas when `html` declares none, so `body { background: var(--bg) }` paints
the window and computes to transparent. And `body` carries a transition on
`background`, so mid-theme-switch it reports the colour it is leaving: measured
here, the same element answered `rgba(0, 0, 0, 0)` on one call and
`rgb(255, 255, 255)` on the next while the dark theme was active and `--bg` was
`#0d1117`.

The declared token is read first now. It is what the stylesheet resolved, it
does not interpolate, and it does not disappear into the canvas; the ancestor
walk remains as the fallback for a page that does not use these tokens. Exports
in both themes are now opaque and carry the right ground.

The unit test missed all of this because it asserted the fill was *truthy*, and
`rgba(0, 0, 0, 0)` is. It asserts opacity now.


### Added — `apiverity agent-setup`, and guidance that cannot go stale

- **`apiverity agent-setup --write`** installs the same body of guidance into
  four places: `AGENTS.md`, `.claude/skills/apiverity/SKILL.md`,
  `.cursor/rules/apiverity.mdc` and `.mcp.json`. An agent that does not know
  `apiverity breaking` exists will write a migration guide by comparing two
  YAML files by eye.

  Those are file formats this writes, not claims about which assistant reads
  them. The run reports what went where and says nothing about what will read
  it.

- **The body is generated, not typed.** Commands from the argument parser, MCP
  tools from `apiverity.mcp.tools.TOOLS`, exit codes from the constants, and
  the version stamped into the footer so a stale copy is detectable. A stale
  README costs a human a minute; a stale agent file costs an agent nothing at
  all — it runs `apiverity check`, gets a usage error, and invents a reason.
  Tests assert the body against those sources in both directions: every command
  listed, and no command named that does not exist.

  This repository's own `AGENTS.md` carries the block, and a test fails when it
  falls behind the CLI — the same rule every other generated document here
  already lives under.

- **It does nothing to files it did not write, unless asked twice.** Dry by
  default, like `replay` and `notify`: installing into somebody's editor
  configuration as a side effect of being run is not something a tool gets to
  do. Only the marked block moves on a re-run. An existing `AGENTS.md` gains a
  section rather than being replaced — it is a file a repository is expected to
  have. A Cursor rule or Claude skill already at its single-purpose path
  *without* the markers is refused by name, and the other targets still
  install.

- **`.mcp.json` is merged, never replaced.** The other servers in it belong to
  other integrations, and a rewrite that dropped them would break three to fix
  one. A file that is not valid JSON is refused rather than overwritten: the
  run does not get to decide somebody's unparseable config was worthless.

### Changed — the artifact-command guard now matches a key pair

`tests/unit/test_result_schema_matches_commands.py` scanned the package for
`"command": "..."`, and `agents/skill.py` writes an `.mcp.json` launch entry —
`{"command": "apiverity-mcp", ...}` — which is not a result artifact. It now
matches `"tool": "apiverity"` immediately followed by `"command"`, which drops
exactly that one string and nothing else.

Tightening a guard can hide things, so the floor beneath it was tightened too:
instead of asserting the scan found "more than fifteen" commands, it asserts
the scan found *every* command the CLI defines. The two that genuinely emit no
artifact — `watch`, which re-runs another command, and `report`, whose output
is the rendered document — are named with their reasons rather than absorbed
into a loose threshold.


### Added — `apiverity graph`: whose build goes red if I edit this

- **`apiverity graph .`** answers the question forty independent contract gates
  cannot: which contract in a tree reads whose schemas.
  `--dependents-of shared/money.yaml` is the blast radius of editing one shared
  file, transitively — so a schema no contract references *directly* still
  reports every contract that reaches it.

- **The flat dependency list could not produce it.** `Service.dependencies`
  records every location an entry document pulled and not one parent. For the
  multi-file fixture it yields `./order.yaml` — a reference made *by*
  `schemas/order.yaml`, which names nothing at all read as a child of the entry
  document — and `../shared/customer.yaml`, which resolves a directory too
  high. Every transitive dependency drawn as a direct one, at a path that does
  not resolve. The bundler records the file that carried each reference now,
  and `Service.dependency_edges` carries it to the graph.

- **Three absences that are not absences.** A reference this run did not follow
  (a remote `$ref` without `--allow-remote-refs`, an absolute path, a file that
  would not read) is drawn and marked with the reason, because dropping it
  makes a contract look like it depends on less than it does. A reference whose
  parent was never introduced goes in `unplaced` rather than being attached to
  the contract root, which is where a guess would put it. A contract that will
  not load is named, because omitting it shows every shared schema with fewer
  dependents than it has — and fails the run.

- **Cycles are named, not merely survived.** Including the self-reference in
  this repository's own multi-file fixture. Each is reported once however many
  ways there are into it, and the walk is iterative: a self-referential tree is
  exactly the input that would blow a recursive one's stack.

- `known` on a `--dependents-of` result separates "nothing depends on this" from
  "this is not in the tree", which otherwise both come back as an empty list.
  Remote nodes are a kind of their own: a URL is not a file anybody in the
  repository can edit, and a blast radius that counted the two together would
  answer the wrong question.

- `--mermaid` renders the graph, dotted for edges that were not followed, and
  says in the diagram how many it did not draw.


### Added — `breaking --sdk`: safe on the wire, broken in every client

- **Seven `SDK-*` rules.** Rename an `operationId` from `getUser` to
  `fetchUser`: the request and the response are byte-identical, every rule in
  the catalogue is silent, and `apiverity diff` reports *no change at all* —
  `operation_id` is compared by nothing, because nothing on the wire depends on
  it. Every generated client's `client.getUser(...)` stops compiling.

  Also covered: an operationId dropped or introduced, a changed first tag
  (which moves the method to a different client class), a renamed response
  schema `title`, a widened response enum, and reordered required parameters.

- **Each rule names the convention it rests on.** Nothing here is tested against
  any particular generator, so nothing here asserts anything about one. A rule
  applies only while its convention is in force — `operation-id-names`,
  `tag-namespaces`, `title-model-names`, `closed-enums`,
  `positional-parameters` — the assumption travels on the finding in
  `metadata`, and `--sdk-convention` narrows the set. Rules outside it do not
  run rather than being downgraded, and the artifact records
  `sdk_conventions`, because a narrowed run and a full one would otherwise read
  as the same run with fewer problems.

- **Two verdicts that disagree, on purpose.** A response enum gaining a value
  is `BRK-ENUM-WIDENED` at INFO — additive, nothing valid becomes invalid — and
  `SDK-ENUM-VALUE-ADDED` at WARN, because a generated closed type has no member
  for it. Both are true, and that disagreement is the point of the family.
  Where the two agree there is only one rule: see nullability below.

- **Nothing in the family is ERROR**, and it is off by default. A rule that
  outranks "you deleted a required response field" because a class got renamed
  is a rule somebody switches off along with everything near it.

- The one silent failure is named as such. `SDK-PARAMETER-ORDER-CHANGED` is the
  only rule here that is not a compile error: swap two required parameters of
  the same type, and a positional generated signature still accepts every
  existing call site with the arguments the other way round.

### Fixed — 3.1 nullability, twice over

Found while building the fixture for the above.

- **`type: [string, "null"]` did not load.** It is the only spelling OpenAPI 3.1
  has for a nullable value, and it raised a pydantic error *inside*
  `SchemaNode`'s constructor — `type` is a `str | None`. The parser's branch for
  type arrays was three lines further down, so the code written for exactly this
  case could never run for it, and the whole document failed to load. `type` is
  normalized before the model is built now.

- **`SchemaNode.nullable` was written by the parser and read by nothing.** Every
  3.0 `nullable: true` was faithfully recorded and then compared by no rule, so
  a response field that started returning null produced no change, no finding,
  and a green gate. `BRK-RESP-NULLABLE-ADDED` (WARN),
  `BRK-REQ-NULLABLE-REMOVED` (ERROR) and their INFO inverses classify it by
  direction, the way every other widening in this catalogue is classified.


### Added — `apiverity digest`, per team, and the contracts nobody swept

- **`apiverity digest`** turns a `sweep` artifact into one contract-health
  document per team. `sweep` answers the platform team's question as a single
  document covering everything; this cuts the same data the other way, so each
  team receives only what it owns and can be sent it on a schedule.

  ```bash
  apiverity sweep . --json > this-week.json
  apiverity digest this-week.json --since last-week.json --out digests/
  ```

  Teams come from the sweep's own ownership resolution, so a digest cannot
  disagree with the sweep it was built from about who owns what.

- **The comparison that produces a false all-clear.** Two sweeps are two walks
  of a tree, and the tree moves underneath them. Last week found forty
  contracts; this week's `--limit` was lower, or a service moved repositories,
  or the discovery glob changed. Twelve contracts are simply absent.

  Differenced naively, that is *twelve contracts fixed* — the report a platform
  team most wants to read and least should believe. A contract is fixed only
  when this sweep looked at it and found it clean; one absent from this sweep
  goes under **No longer swept**, which says what happened. A team that lost
  every contract still gets a digest, because the week a whole service vanished
  should not be the quietest week of the year.

- **A first digest compares nothing, and says so.** Without `--since` there is
  no previous sweep, so nothing is labelled *newly* or *still* failing — both
  are claims about a week nobody looked at. The first rendering of this said
  "Failing in the previous digest too" above a list produced by the first run
  there had ever been.

- **Standing debt is never quiet.** The inverse of `monitor`'s rule, for the
  inverse reason: a five-minute check that re-prints the standing state is
  muted, and a weekly report that surfaces it is doing its job. A contract
  failing for three weeks belongs in all three digests. What *is* dropped is a
  team with nothing at all to report — and those teams are named in `quiet`
  rather than silently omitted, because "four teams had nothing to report" and
  "four teams were missing from the sweep" are different claims.

- **Unowned contracts are a team.** Gathered under `(unowned)` rather than
  dropped: a per-team digest that reported only owned contracts would hide
  exactly the ones nobody will be asked about.

- Standing failures do not fail the run; only a contract that *started* failing
  does. A weekly report that exits non-zero every week is one nobody runs.


### Added — `apiverity monitor`, and the good news that is a lie

- **`apiverity monitor`** runs any other command on a schedule and reports what
  *changed*, not what is. Shaped like `watch` — everything after `--` is the
  command — with the clock as the trigger instead of a file:

  ```bash
  apiverity monitor --state staging.json -- drift openapi.yaml --base-url https://staging
  ```

  A cron entry that runs `drift` every five minutes and posts the result
  produces 288 identical reports a day. The channel is muted inside a week, and
  the run that finally differs arrives in a muted channel. So the output is
  `appeared` / `resolved` / unchanged, and the first run against a state file
  records a baseline and reports none of it as new — otherwise the monitor pages
  somebody about the existing state of the world.

- **The failure that makes a naive differ dangerous.** `drift` against a service
  that has stopped answering does not raise and does not exit 3. It exits
  cleanly with a `DRIFT-UNREACHABLE` finding per operation and none of the real
  findings, because there was nothing to find. Differenced against the previous
  run, that reads as *every finding resolved* — the shape of good news,
  arriving at the exact moment the service went down.

  `ghosts` already says this in the finding itself: "this run establishes
  nothing about whether it is still served". `UNOBSERVABLE_RULES` is that
  sentence made machine-readable. A finding whose operation was not measured is
  **carried forward**, not resolved; every other operation is differenced
  normally, so one dead endpoint does not silence the other thirty-nine; and a
  run that measured nothing is reported inconclusive with exit 3.

  That last one is read from the count the command reports for itself
  (`operations_checked`, `probed`) and never inferred from the findings.
  "Every finding is an unreachable one" is equally the shape of a healthy API
  with one dead endpoint and of a total outage.

- **Identity is `(rule_id, operation_key)`.** Messages carry a p95, a sample
  count, an observed status — values that move between runs — so keying on them
  would report the whole set as resolved-and-reappeared every five minutes. The
  consequence is stated rather than hidden: a finding whose message changed but
  whose identity did not is not a transition, and `message_changed` counts them.

- **Flaps are counted, not suppressed.** Each crossing increments a counter in
  the state file and `flapping` names the keys that have crossed more than once.
  Whether to page on an unstable finding is a policy decision; the count is what
  makes it possible to take one.

- **One state file, one command.** Pointing two commands at one file makes each
  one's findings read as the other's full turnover, on every alternate run. The
  second command is refused by name rather than silently reset.

- `--out` writes the transition report with the *new* findings under `findings`,
  which is the key `apiverity notify` reads — so a routed monitor run sends a
  team the new thing rather than the standing state.


### Added — pairwise cases, model-based CRUD, and an empty library-only list

- **`apiverity test --generator pairwise`** covers every *combination* of two
  parameter values at least once. Every other generator varies one thing at a
  time, so a validator that is right about `page`, right about `per_page`, and
  wrong about the two together is invisible to all of them — and "wrong
  together" is the normal shape of a paging bug.

  Five parameters with six values each: 276 cases against a Cartesian product
  of 7,776, covering all 360 pairs. Measured, not claimed, and not an optimal
  covering array — an optimal one needs about 36.

- **`apiverity test --model-based`** drives the CRUD invariants a schema check
  cannot state, because they are about sequences: can what you just created be
  read back, does an update persist, is a deleted resource actually gone. A
  service can satisfy its contract on every individual request and fail all
  three.

  Collections are discovered from the contract — a POST with a sibling `{id}`
  GET — the update verb comes from the contract, and payloads are derived from
  its request schema. A collection with no update verb is exercised without
  those transitions and the run says what it therefore did not check. It
  writes, so it needs `--include-mutations`.

- **`--list-generators` and `--list-templates` work on their own.** Both are
  documented as "list … and exit" and argparse required the positional
  argument to reach either.

### Fixed — boundary values, the mock's CRUD, and a module that shipped twice

- **`boundary_values` returned values that violate the schema it was given** —
  a length one step outside the range, the exclusive bound itself, and `"A1-"`
  for any `pattern`. Harmless while the only caller treated every value the
  same; wrong the moment a generator has to say whether a case is positive. It
  returns only permitted values now, and everything that violates a constraint
  is in `near_boundary_invalid_cases`.

- **The mock did create and read and called it CRUD.** An update returned a
  freshly generated body and stored nothing; a delete stored nothing either, so
  a resource deleted and read back came back. Every "did that take effect"
  check in this suite passed against a mock where nothing ever did. State is
  applied before the body is built now — which is where the delete was lost, a
  204 has no response schema and `_build_body` returned early — PATCH merges,
  PUT replaces, and a 204 goes out with no body instead of
  `{"error": "mock error 204"}`.

### Removed

- **`apiverity/core/model_v2.py`.** The last of the seven library-only
  capabilities, and the one where the answer was not "wire it up": its
  CODEOWNERS reader used `fnmatch` where the format is gitignore-shaped and
  would assign the wrong team, its `migrate_artifact` upgraded to a schema
  version this project does not emit, its `ContractBundle` was a second
  `sweep`, its entity ids were a third naming scheme beside `Operation.key`,
  and its `fingerprint_findings` was published as a capability and called by
  nothing. Not in `apiverity/sdk.py`, so the documented library surface is
  unchanged.

  **The library-only list is empty.** It began at seven; five were wired to a
  command and each of those turned up a defect that had been invisible for the
  same reason. The check that fails the build when a module *joins* the list
  stays.

### Added — credentials, and the graph check before a run

- **`--auth-profiles FILE --auth-profile NAME` on every command that takes
  `--base-url`** — `test`, `workflow`, `drift`, `mcp-lock`, `ghosts`, `replay`,
  `baseline`, `regression`. Bearer, API key, basic and mTLS.

  A profile names *where* a credential lives — an environment variable, or a
  file — and never holds one, so a result bundle records
  `token_env: STAGING_TOKEN` and nothing anybody who finds it could replay.
  Bundles get attached to pull requests and uploaded as CI artifacts; one
  carrying the token would be a second copy of it in all of those places.

  `apiverity/traffic/auth.py` has held the whole mechanism since the beginning
  and no flag reached it. A tool for checking APIs that could only check
  unauthenticated ones is most of a tool.

- **`--header NAME=VALUE` on the other six commands.** It existed on `drift`
  and `mcp-lock` only. A profile carries the credential and a header carries
  the tenant id beside it; they were never alternatives.

- **`workflow` validates the manifest as a graph before the first request.** A
  variable nothing fills, a duplicate step name, or cleanup deleting something
  nothing created stops the run — by the time somebody notices a literal
  `{user_id}` in a path, the steps before it have already been sent, and one of
  them is usually a POST. Warnings print and the run continues.
  `--no-preflight` skips it.

### Fixed — the workflow variable syntax, and two things in the auth module

- **Three modules agreed on a variable syntax the engine does not read.**
  `WorkflowEngine` substitutes `{name}`; `stateful/graph.py` looked for
  `{{ name }}` and `stateful/templates.py` wrote `{{ name }}`.

  So all four built-in templates were unrunnable. `apiverity workflow
  --template crud-lifecycle`, run as printed, failed on its **first request**
  with *"could not extract 'widget_id' from id"* — `extract` values were bare
  field names where the engine reads `$.id`, `assert_jsonpath` keys were the
  same mistake in the other direction, and the paths it never reached carried
  `{{ widget_id }}`.

  And the validator reported the opposite of the truth in both directions:
  `WF-MISSING-VAR` could never fire, and `WF-INCOMPLETE-CLEANUP` fired on every
  created resource — including the bundled manifest, whose cleanup deletes
  exactly the resource it was warning about. `VARIABLE_RE` and `placeholder`
  now live in `stateful/models.py`, which the engine also uses.

- **`resolve_verify` named the wrong httpx parameter.** It returned
  `(cert_file, key_file)` as httpx's `verify=`, which is the *server*
  certificate setting; a client certificate goes in `cert=`. httpx stores the
  tuple without complaint, so the certificate is never presented and the
  failure arrives somewhere that says nothing about mTLS. It is
  `resolve_client_cert` now.

- **The auth redaction redacted references and printed references.**
  `redacted_summary` blanked `password_env` and `key_file` while printing
  `token_env`, `key_env`, `username_env` and `cert_file` — all the same kind of
  thing, the name of an environment variable or a path. Nothing there is a
  secret, so nothing there is redacted, and a value that is not a valid
  environment variable name is refused when the file loads.

- **`--shape` reported an offered rate a third below what it offered.**
  `achieved_rps` divided by a window that included the response drain, so a
  two-second profile whose tail took another second looked exactly like a
  generator falling behind — the one thing that report exists to distinguish.

### Added — Arazzo, load shapes and virtualization workspaces

- **`apiverity workflow --to-arazzo`**, and an Arazzo description runs
  directly. Arazzo is the OpenAPI Initiative's workflow specification —
  version 1.1.0, released 2026-05-18 — and this project's workflow manifest is
  its own invention, which is a reason not to adopt a tool regardless of the
  engine behind it.

  Most of the work is what does *not* convert. Arazzo describes a graph:
  `goto`, `retry`, `dependsOn`, steps that are whole other workflows, and (new
  in 1.1.0) AsyncAPI steps that publish to a channel. This engine runs a
  straight line. All of it could be dropped while leaving a workflow that still
  runs, so every construct with no equivalent is reported as an `Untranslated`
  entry naming the workflow, the step, the construct and the reason.

  The export is validated against the OAI's **own published JSON Schema**,
  vendored under `schemas/vendor/` with its URL, fetch date and SHA-256. What
  is checked nowhere is the grammar inside a criterion's `condition`, because
  no Arazzo runtime is vendored here — so a condition this project writes is
  known to be structurally valid and known to round-trip, and is not known to
  have been executed by another implementation.

- **`apiverity regression --shape 'ramp:60s@1..20' --operation 'GET /users'`**
  drives one operation at a declared arrival rate. `constant`, `ramp`, `spike`
  and `soak`, each optionally `+poisson`.

  Open loop, which is the point: a request goes out when it is due, whether or
  not earlier ones came back. `regression` and `--curve` are closed loop and
  cannot answer "what happens at 200 requests a second", because a service that
  stalls simply receives less traffic and the queue never builds.

  The run reports `achieved_rps` against the rate that was asked for and how
  far behind its own schedule the generator fell — a p99 from a generator three
  seconds behind describes a load nobody asked for.

- **`apiverity mock --workspace stack.yaml`** serves several contracts at once,
  under one seed, printing the address of each before it blocks. Change a fault
  on one service and the generated data everywhere stays where it was, which is
  the only way "run the frontend with billing degraded" is a test rather than
  an anecdote.

  One run serves several contracts, so the artifact is stamped with the
  workspace file's hash and each service carries its own contract's path and
  hash.

- **`--input NAME=VALUE` on `workflow`.** `Workflow.inputs` was documented on
  the model as "variables supplied by the caller", read by the graph validator,
  parsed out of no manifest and supplied by no command.

### Fixed

- **A suppressions file could turn the gate off in one line.** The module said
  suppressions "must carry an owner and reason, and expire automatically" and
  `docs/ci.md` said "each one needs an owner, a reason and an expiry". Nothing
  enforced any of it: `{"rule_id": "BRK-RESP-FIELD-REMOVED"}` was a valid entry
  that silenced the rule across every operation, permanently, with nobody's
  name on it.

  An entry now has to be justified (`owner`, `reason`) and bounded (`expires`,
  within `suppression_max_days`, default 90) or it does not suppress — it fails
  closed, and `SUPPRESSION-INCOMPLETE` names every missing field. An expiry far
  enough away is a permanent ignore with a date on it and is treated as one.
  `approved_by` is new, required when `suppression_require_approver: true`.

- **`profile: strikt` validated clean**, from the command whose stated premise
  is rejecting a typo before it becomes a silently ignored key. `profile` was
  checked for type and not for value; the run then failed later with
  `internal error: unknown severity profile`. `CONFIG-PROFILE-INVALID`.

- **Twelve rules `explain` did not know.** Every `SUPPRESSION-*` and `CONFIG-*`
  rule was emitted, published in `docs/ci.md`, and catalogued nowhere — and
  these are the findings that appear while somebody is setting the gate up.

- **`CheckRuleSpec.family` had no reader.** Every catalogue set it; the
  document generator grouped by a hand-maintained prefix table and swept the
  rest into a heading called "Other", where two SEC rules added after that
  table was written had been sitting.

- **A load profile's shape did nothing.** `execute` computed the arrival
  schedule and discarded every offset, so a ramp, a spike, a soak and a Poisson
  process produced the same run, differing only in request count.
  `capacity_search` is deleted: it swept concurrency against a transport the
  *caller* supplied, so it never sent a request, and `regression --curve` does
  that job against a real target.

- **A virtualization workspace's seed reached a service only when that service
  had no fault override.** `faults.get(name) or FaultConfig(seed=...)` took a
  per-service config whole, and one written for latency carries the default
  seed of 0 — so configuring latency on a service silently reseeded its data,
  in a feature whose entire premise is one seed across the set.

- **The publication gate had been red for three commits.** The governance
  fixture carries a planted credential to make `SEC-SECRET-IN-CONTRACT` fire,
  and `scripts/secret_scan.py` did exactly what it should with it. The
  scanner's existing per-line `secret-scan: allow` marker is used, rather than
  weakening the scanner or exempting `fixtures/` wholesale.

- **An ignore rule was swallowing files whose names contain "fix".**
  `.gitignore` carried `*_fix*.py`, which matched `test_swagger2_fixture.py`.
  ruff honours `.gitignore`, so lint and format both reported clean while
  skipping it entirely.


### Added — plain-English summaries

- **`apiverity breaking --summary`** renders what changed, who it affects and
  what to do, in the shape of a pull request description rather than a release
  note. `changelog` lists every change grouped by operation, which is right for
  a release and wrong for a PR body where the reader wants three sentences and
  a decision.

  Deterministic templates, no model call: a summary a language model writes is
  one nobody can diff, nobody can test, and nobody can run in CI without a
  network-egress conversation — and the structured diff already contains
  everything the sentences need. Twenty findings of one kind become one counted
  sentence, not twenty lines.

  It always offers the additive alternative — deprecate with a sunset date
  instead of removing, add optional fields instead of changing required ones —
  because a tool that only blocks gets uninstalled. With `--suggest-version` it
  names the concrete version: "Release this as **2.0.0**" rather than "behind a
  major version bump".

  A rule the phrase table does not know is named by its id rather than
  paraphrased. A guessed sentence would be neither accurate nor lookup-able.

- The GitHub Action passes `--summary --suggest-version`, so every artifact it
  uploads carries prose a PR comment can quote directly.

### Fixed

- `str.capitalize()` lower-cased the rest of the string, turning the fallback
  phrase "BRK-SOMETHING-NEW fired" into "Brk-something-new fired" — destroying
  the rule id the very next sentence tells the reader to look up. Caught by its
  own test.

### Added — project configuration and onboarding

- **`.apiverity.yaml`, with a published schema.** There was no project config
  at all: every run repeated its options, `--severity-override` had to be
  retyped per invocation, and there was nowhere to record "these are our
  contracts" so that a laptop and CI agree about what is being checked.

  `schemas/config-v1.schema.json` is generated from `apiverity/core/config.py`
  by `scripts/generate_config_schema.py --check` in CI, so the validator and
  the published schema are built from one table and cannot disagree. If they
  diverged, an editor would autocomplete a key the tool rejects.

- **An unknown key is an ERROR, not a warning.** `severity_overides` (one 'r')
  is a typo someone will make, and a tool that ignores it reports that nothing
  is wrong while the override the reader believes is active does nothing at
  all. The message carries a did-you-mean. An override naming a rule that does
  not exist is reported too, for the same reason: it does nothing, and looks
  like it does something.

- **`apiverity init`**, deliberately not interactive. A wizard cannot run in
  CI, cannot be scripted, and cannot be re-run to check its own output. This
  detects the contracts actually in the repository, writes a config describing
  what it found, prints the next three commands, and is safe to run twice.

  It writes `fail_on: never`. A gate that fails on its first run against an API
  that already has history gets removed rather than adopted; read a few reports
  first, then turn it on.

### Fixed

- **`init`'s contract sniff matched the word rather than the declaration**,
  found by running it on this repository: it proposed `schemas/**` because
  `schemas/result-v1.schema.json` contains the string "openapi" inside an enum
  of protocol names. A JSON Schema that mentions OpenAPI is not an OpenAPI
  document, and a config listing the wrong files is worse than one listing
  none — it looks configured. The sniff now requires a version *declaration*.

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
