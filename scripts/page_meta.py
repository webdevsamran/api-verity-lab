"""The one-line description every docs page publishes to a search engine.

MkDocs Material renders `description:` front matter as
`<meta name="description">`. A page without one inherits `site_description`
from `mkdocs.yml` -- so before this file existed, ninety-five of ninety-seven
pages published the same sentence, which is the thing a search engine treats
as duplication and rewrites with an excerpt of its own choosing.

Descriptions live here rather than in the pages because twenty-seven of those
pages are generated, and a generator that rewrites a file also rewrites
anything hand-added to the top of it. The generators import `front_matter`
from here; `scripts/check_page_descriptions.py --check` holds every page to
this table, and CI runs it.

Adding a page to `docs/` without adding it here fails that check. That is
deliberate: a missing description is invisible in the rendered site and
visible only in a search result, which is the worst place to discover it.
"""

from __future__ import annotations

#: Docs-relative path -> the page's meta description.
#:
#: Kept between 70 and 165 characters: shorter says nothing, longer is
#: truncated in the result it was written for.
DESCRIPTIONS: dict[str, str] = {
    # -- Entry pages -------------------------------------------------------
    "index.md": (
        "API contract governance in one tool: breaking-change rules, drift detection, fuzzing and performance budgets for OpenAPI, AsyncAPI, GraphQL, gRPC, MCP and WSDL."
    ),
    "faq.md": (
        "Short answers about API contract governance, breaking-change detection, drift, MCP tool surfaces and CI gating, each backed by the command that proves it."
    ),
    "use-cases.md": (
        "What to switch on at your scale: one developer with one API, a team with several services, an organisation under audit, or a team shipping AI agents."
    ),
    "install.md": (
        "Every install channel for api-verity-lab -- pipx, uvx, pip, Docker, Homebrew, npm, Scoop -- what each needs, and which of them work today."
    ),
    "playground.md": (
        "Paste two versions of an OpenAPI contract and get the breaking changes with rule ids, in your browser. Nothing is uploaded; the real engine runs on Pyodide."
    ),
    "exit-codes.md": (
        "The exit codes api-verity-lab treats as a public contract, so CI gates and onboarding scripts can branch on them without breaking on an upgrade."
    ),
    "sdk.md": (
        "The Python SDK surface: Contract, Operation, SchemaNode, diff_services, evaluate_breaking and the rest, for driving contract governance from your own code."
    ),
    "ci.md": (
        "Three ways to wire API contract checks into CI -- the GitHub Action, a container step, or the raw CLI -- with suppressions that carry an owner and an expiry."
    ),
    "privacy.md": (
        "api-verity-lab is local-first: nothing leaves your machine unless you pass a URL. What is redacted, when, and what never reaches disk."
    ),
    "self-hosting.md": (
        "Running the optional self-hosted server: organisations, RBAC, approvals, hash-chained audit, signed webhooks and can-i-deploy, on Flask and SQLite."
    ),
    # -- Rules, policy and the specifications ------------------------------
    "rule-catalog.md": (
        "Every breaking-change rule this tool can emit, with severity, direction and the override syntax -- generated from the engine, so it cannot drift from the code."
    ),
    "check-rules.md": (
        "Every rule that is not a breaking-change rule: static checks over a normalized contract, plus the few that need a live service, generated from the catalogues."
    ),
    "rule-parity.md": (
        "Which breaking-change rules actually fire for OpenAPI, Swagger 2.0, AsyncAPI, GraphQL, gRPC, MCP and WSDL -- measured by making every rule fire, not asserted."
    ),
    "rule-packs.md": (
        "Publishing and discovering rule packs: house style as a versioned Python distribution your other repositories install, rather than a fork of this one."
    ),
    "policy-dsl.md": (
        "Express naming, authentication, pagination and deprecation rules as YAML, and enforce them with `apiverity validate --policy-file` without writing Python."
    ),
    "plugin-authoring.md": (
        "Writing a plugin for api-verity-lab: six versioned entry-point groups, discovered by any installation that pip-installs your distribution."
    ),
    "spectral-migration.md": (
        "Import an existing Spectral ruleset with `apiverity import-rules`, and see which rules translate, which approximate and which have no equivalent."
    ),
    "oasdiff-migration.md": (
        "Moving a CI gate from oasdiff: which of your jq filters keep matching, the change-code mapping, and `report --format oasdiff` so leaving again is cheap."
    ),
    "benchmark.md": (
        "Both engines over the same contracts, with what each reported -- including the cases where api-verity-lab loses to oasdiff. Reproducible from committed evidence."
    ),
    "competitive-analysis.md": (
        "How api-verity-lab compares with oasdiff, Schemathesis, Spectral, Pact, Prism, WireMock, Karate, k6 and Buf, rendered from dated GitHub API evidence."
    ),
    "compliance-mapping.md": (
        "Findings mapped onto the OWASP API Security Top 10, the MCP Top 10 and the Top 10 for Agentic Applications -- including what this tool cannot see."
    ),
    "spec-support.md": (
        "Which specification versions api-verity-lab reads, how a document is detected, and exactly what each format supports -- OpenAPI 3.0 to 3.2 through WSDL 1.1."
    ),
    "protocol-support.md": (
        "The protocols this tool reads and the contract model they all compile into: OpenAPI, Swagger 2.0, AsyncAPI, GraphQL, gRPC, MCP tool manifests and WSDL."
    ),
    "streaming.md": (
        "Server-Sent Events, JSON Lines and multipart streams: the OpenAPI 3.2 itemSchema, itemEncoding and prefixEncoding keywords, and the rules that diff them."
    ),
    "arazzo.md": (
        "Importing and exporting Arazzo, the OpenAPI Initiative's workflow specification, and exactly what survives the round trip into this project's workflow engine."
    ),
    "federation.md": (
        "GraphQL federation: evaluating a subgraph change against the composed supergraph, so a safe-looking subgraph edit that breaks the gateway is caught."
    ),
    "workflow-authoring.md": (
        "Authoring workflow manifests: human-authored YAML, an engine that never invents destructive sequences, and hosts refused outside `allowed_hosts`."
    ),
    # -- Agents, runtime and drift -----------------------------------------
    "mcp-drift.md": (
        "Compare a declared MCP tool manifest against a running server over Streamable HTTP: schema drift, specification conformance and an authentication posture probe."
    ),
    "mcp-poisoning.md": (
        "Detecting MCP tool-description poisoning -- hidden markup, invisible characters, cross-tool instructions and credential paths in the text an agent routes on."
    ),
    "mcp-lock.md": (
        "A signed baseline of an MCP tool surface in `mcp.lock`, so CI fails the moment the surface changes without review."
    ),
    "mcp-inventory.md": (
        "Find shadow MCP servers: what this checkout and this machine's agent clients are actually configured to reach, checked against an approved inventory."
    ),
    "mcp-exposure.md": (
        "Running api-verity-lab as an MCP server, exposing a read-only governance surface to an agent -- what it exposes and, deliberately, what it does not."
    ),
    "agent-tasks.md": (
        "Exporting a verified MCP tool surface as a task pack for tooltrace-bench, which measures whether agents can actually use the interface you proved sound."
    ),
    "agent-setup.md": (
        "Register api-verity-lab with Claude Code, Cursor, Windsurf, Codex and Aider in one command, so a coding agent knows the contract gate exists before it edits a spec."
    ),
    "call-budgets.md": (
        "Call budgets for agent traffic: declare how much an agent may use an interface, and fail when recorded calls exceed it. The most-cited worry about agent load."
    ),
    "capture.md": (
        "Record real traffic into a HAR corpus with `apiverity capture`, then run drift detection against it instead of against a synthetic probe."
    ),
    "ghost-routes.md": (
        "Ghost routes: endpoints that were deleted from the contract and still answer in production. Found by probing what the old contract declared and the new one does not."
    ),
    "behavioural-drift.md": (
        "Behavioural drift asks whether a service still matches itself: a field that stopped being populated, an enum value that stopped appearing, a latency that moved."
    ),
    "inferred-contracts.md": (
        "Draft an OpenAPI contract from recorded traffic with `apiverity infer`, for the very common case of a service that has no contract written down anywhere."
    ),
    "framework-adapters.md": (
        "Generate the contract from the running application -- FastAPI, Flask, Express, NestJS, Laravel, Spring, gin -- so the committed file cannot silently go stale."
    ),
    "monitoring.md": (
        "Synthetic monitoring: run any api-verity-lab command on a schedule against staging or production, and alert on what changed since the last run."
    ),
    "load-shapes.md": (
        "Drive one operation at a declared arrival rate for a declared duration, instead of measuring every operation a fixed number of times."
    ),
    "objectives.md": (
        "Attach latency and error-rate objectives to operations in the contract itself, so a performance budget is a declared SLO rather than a flag on a command line."
    ),
    "virtualization.md": (
        "Serve several mocked contracts from one workspace file under one seed, so a whole dependency surface comes up deterministically with one command."
    ),
    "ebpf-evaluation.md": (
        "Why eBPF zero-instrumentation capture was evaluated as prior art and deliberately not built: what it would add here, against what it would cost to maintain."
    ),
    # -- Security and compliance -------------------------------------------
    "authorization.md": (
        "BOLA and BFLA probes: what happens when a different caller asks. Authorized-testing only, driven by the stateful engine across two identities."
    ),
    "guardrails.md": (
        "Two checks that run before a generated request leaves the machine, and over the response after: payload guardrails for fuzzing and replay."
    ),
    "pii.md": (
        "Personal data and credential handling: two rules with opposite defaults, because secrets and personal data fail in opposite directions."
    ),
    "evidence.md": (
        "Dated, checksummed evidence packs for SOC 2, ISO/IEC 42001, DORA and the EU AI Act, naming the controls each artifact speaks to -- and the ones it does not."
    ),
    "audit-export.md": (
        "Export the self-hosted server's hash-chained audit log so an auditor can verify it independently, without trusting the server that produced it."
    ),
    "kill-switch.md": (
        "The emergency policy freeze auditors of agent-era systems ask for by name, as one command -- plus the activity log and permission review alongside it."
    ),
    "oidc.md": (
        "Authenticate the self-hosted server against your identity provider, with signature, issuer, audience and expiry all actually checked rather than decoded."
    ),
    "auth-profiles.md": (
        "One auth-profiles file for every command that takes a base URL, so credentials live in one place and never in a shell history or a CI log."
    ),
    "air-gapped.md": (
        "Running api-verity-lab in a disconnected network: container image, Helm chart, vendored schemas, and an egress map generated from the source rather than promised."
    ),
    "egress.md": (
        "Every place this package can open a socket, walked out of the source rather than remembered -- which is what makes the no-telemetry claim checkable."
    ),
    "supply-chain.md": (
        "What a release carries and how to verify it without trusting the builder: an SPDX SBOM, signed provenance, and the commands that check both."
    ),
    "safety-model.md": (
        "What api-verity-lab will and will not do to a live service: dry-run defaults, explicit opt-in for anything that writes, and hosts refused unless allow-listed."
    ),
    "security.md": (
        "How to report a vulnerability in api-verity-lab, what is in scope, and the response you should expect."
    ),
    # -- Teams and organisations -------------------------------------------
    "blast-radius.md": (
        "Turn `severity: ERROR` into the names of the services that break, by evaluating a breaking change against a registry of declared consumers."
    ),
    "monorepo-sweep.md": (
        "Check every contract in a monorepo against a base branch in one command, with results routed to the team that owns each file."
    ),
    "digest.md": (
        "Turn a sweep into one contract-health document per team, on a schedule -- routing is the difference between an alert and a muted channel."
    ),
    "dependency-graph.md": (
        "Map which repositories share which schemas, and find every dependent of a shared contract before you change it."
    ),
    "merge-queue.md": (
        "Why a gate that only runs on pull_request proves nothing about what merges, and how to run this one in a GitHub merge queue instead."
    ),
    "migration-guides.md": (
        "Attach the migration guide to the operation, so a breaking-change finding says what to do instead rather than only what broke."
    ),
    "saved-views.md": (
        "Every dashboard view is a URL: filters write themselves into the address bar, so sharing a view is copying a link rather than a feature to build."
    ),
    "onboarding.md": (
        "The dashboard's four-step first-run tour, shown once, and how to bring it back when you want it."
    ),
    "sdk-surface.md": (
        "Changes that are safe on the wire and breaking in every generated client -- detected by modelling what a code generator does with the contract."
    ),
    "lsp.md": (
        "One language server, so breaking-change diagnostics appear as you type in VS Code, Neovim, JetBrains, Helix, Zed and Emacs without five separate plugins."
    ),
    # -- The project itself ------------------------------------------------
    "architecture.md": (
        "How api-verity-lab is put together: one normalized contract model, one result format, six plugin entry-point groups, and where each subsystem sits."
    ),
    "contributing.md": (
        "How to contribute to api-verity-lab: the checks that must pass, the conventions that are correctness rather than style, and what a good pull request looks like."
    ),
    "code-of-conduct.md": (
        "The code of conduct for the api-verity-lab project and its community spaces."
    ),
    "changelog.md": (
        "Release notes for api-verity-lab, version by version, including every rule id added, renamed or retired."
    ),
    "roadmap.md": (
        "What is planned for api-verity-lab, and the principles that decide what gets built."
    ),
    "roadmap-status.md": (
        "All 134 planned items, each carrying evidence -- a command, a module, a rule prefix, a CI step -- that is re-checked on every build."
    ),
    "product-gaps.md": (
        "What api-verity-lab does not do, recorded deliberately: the gaps another tool covers better, and the ones nobody covers yet."
    ),
    "capability-status.md": (
        "An audited classification of every capability against the code that implements it, rather than a feature list nobody re-reads."
    ),
    "sponsors.md": (
        "What sponsoring api-verity-lab funds -- maintenance, version matrices, the quarterly competitor refresh -- and what it explicitly does not buy."
    ),
    "credits.md": (
        "The specifications, libraries and projects api-verity-lab is built on and after, named in full: committee work, dependencies and prior art."
    ),
    "awesome-list-submissions.md": (
        "Prepared awesome-list entries for api-verity-lab, plus the submission etiquette and the three claims not to make."
    ),
    # -- Generated: one page per protocol ----------------------------------
    "for/asyncapi.md": (
        "Breaking-change detection for AsyncAPI 2.x and 3.x: channels, messages and payload schemas, diffed with the direction each channel runs in."
    ),
    "for/grpc.md": (
        "Breaking-change detection for gRPC and protobuf: field numbers, presence, streaming and reserved ranges, from .proto sources or descriptor sets."
    ),
    "for/mcp.md": (
        "Breaking-change detection for MCP tool manifests: annotation hints, outputSchema presence and the tool-description edits an agent routes on."
    ),
    "for/openapi-2020-12.md": (
        "Breaking-change rules for the JSON Schema 2020-12 keywords OpenAPI 3.1 brought in: prefixItems, if/then, dependentRequired and patternProperties."
    ),
    "for/openapi.md": (
        "Breaking-change detection for OpenAPI 3.0, 3.1 and 3.2 and Swagger 2.0: paths, parameters, schemas, security schemes and the 3.2 additions."
    ),
    "for/swagger2.md": (
        "Breaking-change detection for Swagger 2.0, under the same rules as OpenAPI 3 -- including diffing a 2.0 document against a 3.x one."
    ),
    "for/wsdl.md": (
        "Breaking-change detection for WSDL 1.1 and SOAP: portTypes, bindings, SOAPAction, binding style and SOAP version -- what breaks every generated stub."
    ),
    # -- Generated: one page per competitor sharing a lane -----------------
    "vs/buf.md": (
        "api-verity-lab compared with Buf, from dated GitHub evidence: protobuf compatibility as a gate, against the same gate across seven protocols."
    ),
    "vs/dredd.md": (
        "api-verity-lab compared with Dredd, from dated GitHub evidence: the archived contract-testing workflow, and what replaced it here."
    ),
    "vs/graphql-inspector.md": (
        "api-verity-lab compared with GraphQL Inspector, from dated GitHub evidence: GraphQL schema diffing against multi-protocol contract governance."
    ),
    "vs/k6.md": (
        "api-verity-lab compared with k6, from dated GitHub evidence: a load engine against performance budgets attached to a contract."
    ),
    "vs/karate.md": (
        "api-verity-lab compared with Karate, from dated GitHub evidence: declarative API test authoring against versioned contract rules and drift."
    ),
    "vs/oasdiff.md": (
        "api-verity-lab compared with oasdiff, from dated GitHub evidence: what each covers, where oasdiff is stronger, and what migrating actually costs."
    ),
    "vs/optic.md": (
        "api-verity-lab compared with Optic, from dated GitHub evidence: traffic-driven contract inference, archived upstream and rebuilt here as `infer`."
    ),
    "vs/pact-oss.md": (
        "api-verity-lab compared with Pact, from dated GitHub evidence: consumer-driven contracts and a broker against contract diffing and runtime drift."
    ),
    "vs/postman-newman.md": (
        "api-verity-lab compared with Postman and Newman, from dated GitHub evidence: collection running against contract diffing, drift and breaking-change rules."
    ),
    "vs/prism.md": (
        "api-verity-lab compared with Prism, from dated GitHub evidence: mocking and validation proxying against breaking-change rules and drift detection."
    ),
    "vs/schemathesis.md": (
        "api-verity-lab compared with Schemathesis, from dated GitHub evidence: property-based API testing against contract governance, and where each fits."
    ),
    "vs/spectral.md": (
        "api-verity-lab compared with Spectral, from dated GitHub evidence: style linting against versioned breaking-change rules, and importing a Spectral ruleset."
    ),
    "vs/wiremock.md": (
        "api-verity-lab compared with WireMock, from dated GitHub evidence: service virtualization against contract governance, and where the two overlap."
    ),
}


#: Newline, spelled out, because this module is read far more often than a
#: backslash escape deserves in the middle of a template.
NL = chr(10)


def front_matter(page: str) -> str:
    """The YAML block that belongs at the very top of `page`.

    `page` is the path relative to `docs/`, the same key `DESCRIPTIONS` uses.
    A folded scalar (`>-`) is used so a long description can be wrapped in the
    source without the line break reaching the rendered tag.

    Raises rather than returning an empty block: a generator that quietly
    emitted no description would produce exactly the defect this file exists
    to prevent.
    """
    try:
        description = DESCRIPTIONS[page]
    except KeyError:
        raise KeyError(
            f"{page} has no entry in scripts/page_meta.py; add one so the page "
            f"publishes its own meta description rather than the site's"
        ) from None
    return NL.join(["---", "description: >-", f"  {description}", "---", "", ""])


def strip_front_matter(text: str) -> str:
    """`text` without a leading front-matter block, if it has one.

    Used by the checker to compare a generated page against what its generator
    produces, and by `--write` to replace a block rather than stack a second
    one on top of the first.
    """
    if not text.startswith("---" + NL):
        return text
    end = text.find(NL + "---" + NL, 3)
    if end == -1:
        return text
    return text[end + len(NL + "---" + NL) :].lstrip(NL)
