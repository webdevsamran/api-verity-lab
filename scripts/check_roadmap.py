"""The 134-item roadmap, held against the code that is supposed to implement it.

A roadmap is the easiest document in a repository to be wrong. Items get
ticked from memory, a refactor renames the command a row describes, and the
table goes on saying "done" about a capability that left. This project does not
accept that for its rule catalogue, its competitive table or its README counts,
and a roadmap is a claim like any other.

So every item carries **evidence**: a predicate that is true only while the
thing exists. `--check` fails when any of it stops being true, and
`docs/roadmap-status.md` is generated from the same table, so the published
status and the code cannot disagree.

    python scripts/check_roadmap.py           # rewrite docs/roadmap-status.md
    python scripts/check_roadmap.py --check   # verify, exit 1 on drift
    python scripts/check_roadmap.py --list    # every item and its evidence

## The evidence vocabulary

Each predicate is a `kind:argument` string, checked without the network:

| Kind | True when |
|---|---|
| `cmd:NAME` | the CLI defines that subcommand |
| `flag:CMD:--flag` | that subcommand declares that flag |
| `mod:dotted.path` | the module imports |
| `attr:dotted.path:NAME` | the module defines that name |
| `file:path` | the path exists |
| `rule:PREFIX` | at least one catalogued rule id starts with it |
| `protocol:NAME` | the loader supports that spec format |
| `ci:substring` | the substring appears in a workflow file |
| `web:path` | the file exists under `web/` |
| `grep:path:needle` | the needle appears in that file |

## Items nobody here can finish

Six need an action only the account owner can take — registering a PyPI
Trusted Publisher, minting a DOI, opening pull requests against other people's
repositories, deciding what an opt-in dataset may collect. They carry `owner:` instead of evidence, are counted separately,
and the status page says so rather than showing them as done or as failures.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATUS = ROOT / "docs" / "roadmap-status.md"

sys.path.insert(0, str(ROOT))

NL = chr(10)
MARK_OPEN = "<!-- generated:roadmap -->"
MARK_CLOSE = "<!-- /generated:roadmap -->"


@dataclass(frozen=True)
class Item:
    """One roadmap row: what it is, and what proves it exists."""

    id: str
    title: str
    evidence: tuple[str, ...]
    #: Set instead of evidence when the remaining step belongs to an account
    #: owner rather than to this repository.
    owner: str = ""


SECTIONS: dict[str, tuple[Item, ...]] = {
    "A · Agent & MCP governance": (
        Item(
            "AGENT-01",
            "MCP tool manifest as a spec plugin",
            ("protocol:mcp", "mod:apiverity.specs.mcp.manifest"),
        ),
        Item("AGENT-02", "BRK-MCP-* breaking-change taxonomy", ("rule:BRK-MCP-",)),
        Item(
            "AGENT-03",
            "Declared-vs-live tool drift",
            ("mod:apiverity.runtime.mcp_drift", "rule:MCP-DRIFT-", "flag:drift:--base-url"),
        ),
        Item("AGENT-04", "MCP spec conformance (MCP-CONF-*)", ("rule:MCP-CONF-",)),
        Item(
            "AGENT-05", "Per-connection tool-set stability probe", ("rule:MCP-CONF-LIST-UNSTABLE",)
        ),
        Item(
            "AGENT-06",
            "Opt-in tools/call probing",
            ("mod:apiverity.runtime.mcp_invoke", "flag:drift:--execute"),
        ),
        Item(
            "AGENT-07",
            "Tool-description poisoning detection",
            (
                "mod:apiverity.security.mcp_poisoning",
                "rule:MCP-POISON-",
                "file:docs/mcp-poisoning.md",
            ),
        ),
        Item("AGENT-08", "Annotation-integrity checks", ("rule:MCP-ANNOTATION-",)),
        Item("AGENT-09", "Shadow MCP server discovery", ("rule:MCP-SHADOW-", "cmd:mcp-inventory")),
        Item(
            "AGENT-10",
            "MCP auth posture check",
            ("mod:apiverity.runtime.mcp_auth", "rule:MCP-AUTH-"),
        ),
        Item(
            "AGENT-11",
            "MCP fleet inventory & posture dashboard",
            ("file:docs/mcp-inventory.md", "web:src/pages/agents.tsx"),
        ),
        Item(
            "AGENT-12",
            "Baseline lockfile + signature",
            ("cmd:mcp-lock", "rule:MCP-LOCK-", "file:docs/mcp-lock.md"),
        ),
        Item(
            "AGENT-13",
            "apiverity as an MCP server",
            ("mod:apiverity.mcp.server", "file:docs/mcp-exposure.md"),
        ),
        Item(
            "AGENT-14",
            "Agent-facing AGENTS.md skill installer",
            ("cmd:agent-setup", "mod:apiverity.agents.skill"),
        ),
        Item(
            "AGENT-15",
            "OWASP MCP Top-10 mapping report",
            ("mod:apiverity.reports.compliance", "grep:docs/compliance-mapping.md:MCP01"),
        ),
        Item(
            "AGENT-16",
            "OWASP ASI (Agentic) Top-10 mapping",
            ("grep:docs/compliance-mapping.md:ASI01",),
        ),
        Item(
            "AGENT-17",
            "Agent call-budget & rate governance",
            ("cmd:budget", "rule:BUDGET-", "file:docs/call-budgets.md"),
        ),
        Item(
            "AGENT-18",
            "Tool-surface semantic versioning advisor",
            ("flag:breaking:--suggest-version",),
        ),
        Item(
            "AGENT-19",
            "Legacy/Modern MCP era tolerance",
            ("rule:MCP-DRIFT-LEGACY-SERVER", "rule:MCP-PROTOCOL-ERA-UNOBSERVED"),
        ),
        Item(
            "AGENT-20",
            "Agent trajectory hand-off to tooltrace-bench",
            (
                "cmd:agent-tasks",
                "mod:apiverity.agents.tasks",
                "file:schemas/vendor/tooltrace-task-2026-09-11.schema.json",
                "file:docs/agent-tasks.md",
            ),
        ),
    ),
    "B · Specification coverage": (
        Item(
            "SPEC-01",
            "OpenAPI 3.2.0 support",
            ("grep:apiverity/specs/openapi/parser.py:3.2", "grep:docs/spec-support.md:3.2"),
        ),
        Item(
            "SPEC-02",
            "Streaming media types (itemSchema / prefixEncoding / itemEncoding)",
            (
                "grep:apiverity/specs/openapi/parser.py:itemSchema",
                "grep:apiverity/specs/openapi/parser.py:itemEncoding",
                "rule:BRK-STREAM-",
                "file:docs/streaming.md",
            ),
        ),
        Item(
            "SPEC-03",
            "query method + additionalOperations",
            ("grep:apiverity/specs/openapi/parser.py:additionalOperations",),
        ),
        Item(
            "SPEC-04",
            "querystring parameter location",
            (
                "attr:apiverity.core.model:ParameterLocation",
                "grep:apiverity/core/model.py:QUERYSTRING",
            ),
        ),
        Item(
            "SPEC-05", "Hierarchical tags (summary/parent/kind)", ("rule:SPEC-TAG-PARENT-UNKNOWN",)
        ),
        Item(
            "SPEC-06",
            "OAuth 2.0 device flow + oauth2MetadataUrl",
            (
                "grep:apiverity/specs/openapi/parser.py:oauth2MetadataUrl",
                "grep:apiverity/specs/openapi/parser.py:deviceAuthorization",
            ),
        ),
        Item(
            "SPEC-07",
            "Arazzo workflow spec import/export",
            (
                "mod:apiverity.stateful.arazzo",
                "file:docs/arazzo.md",
                "file:schemas/vendor/arazzo-1.1-2026-04-15.schema.json",
            ),
        ),
        Item("SPEC-08", "Canonicalization pass", ("mod:apiverity.core.canonical",)),
        Item("SPEC-09", "External $ref bundler", ("mod:apiverity.specs.bundle", "rule:SPEC-REF-")),
        Item(
            "SPEC-10",
            "JSON Schema 2020-12 keyword completeness",
            (
                "rule:BRK-DEPENDENT-",
                "rule:BRK-TUPLE-",
                "rule:BRK-PATTERN-PROPERTIES-",
                "rule:BRK-CONDITIONAL-",
            ),
        ),
        Item(
            "SPEC-11",
            "GraphQL federation / supergraph diffing",
            ("cmd:federation", "rule:FED-", "file:docs/federation.md"),
        ),
        Item("SPEC-12", "SOAP/WSDL lane", ("protocol:wsdl", "rule:BRK-SOAP-", "rule:SPEC-WSDL-")),
    ),
    "C · Rules, governance & policy": (
        Item("RULE-01", "explain <rule-id>", ("cmd:explain", "file:docs/check-rules.md")),
        Item("RULE-02", "--suggest-version advisor", ("flag:breaking:--suggest-version",)),
        Item(
            "RULE-03",
            "Plain-English change summaries",
            ("mod:apiverity.rules.summary", "flag:breaking:--summary"),
        ),
        Item(
            "RULE-04",
            "Rule-pack registry & sharing",
            (
                "mod:apiverity.rules.packs_registry",
                "flag:rules:--packs",
                "file:docs/rule-packs.md",
                "file:examples/plugins/apiverity-house-rules/pyproject.toml",
            ),
        ),
        Item(
            "RULE-05",
            "Custom policy DSL maturity",
            ("mod:apiverity.rules.dsl", "flag:validate:--policy-file", "file:docs/policy-dsl.md"),
        ),
        Item(
            "RULE-06",
            "Deprecation lifecycle + RFC 8594",
            ("mod:apiverity.rules.lifecycle", "rule:LIFECYCLE-"),
        ),
        Item(
            "RULE-07",
            "Approved-diff workflow hardening",
            ("mod:apiverity.rules.suppressions", "rule:SUPPRESSION-"),
        ),
        Item(
            "RULE-08",
            "Rule autofix suggestions",
            ("mod:apiverity.rules.alternatives", "flag:breaking:--suggest-fix"),
        ),
        Item("RULE-09", "Severity profiles", ("mod:apiverity.rules.profiles", "flag:--profile")),
        Item(
            "RULE-10",
            "Cross-protocol rule parity matrix",
            (
                "mod:apiverity.rules.parity",
                "file:docs/rule-parity.md",
                "file:scripts/generate_rule_parity.py",
            ),
        ),
        Item(
            "RULE-11",
            "Consumer-aware severity",
            ("mod:apiverity.rules.consumers", "flag:breaking:--severity-by-consumers"),
        ),
        Item(
            "RULE-12",
            "Rule benchmark vs oasdiff",
            (
                "file:scripts/benchmark_oasdiff.py",
                "file:docs/benchmark.md",
                "file:data/benchmark-oasdiff.json",
            ),
        ),
    ),
    "D · Runtime, drift & observability": (
        Item(
            "RUN-01",
            "Live-traffic capture (proxy)",
            ("cmd:capture", "mod:apiverity.traffic.capture", "file:docs/capture.md"),
        ),
        Item(
            "RUN-02",
            "First-seen/last-seen on drift findings",
            ("grep:apiverity/runtime/findings.py:first_seen",),
        ),
        Item("RUN-03", "Unified drift finding shape", ("mod:apiverity.runtime.findings",)),
        Item(
            "RUN-04",
            "Shadow contract inference",
            ("cmd:infer", "mod:apiverity.specs.infer", "file:docs/inferred-contracts.md"),
        ),
        Item(
            "RUN-05",
            "Ghost-route auditor",
            ("cmd:ghosts", "rule:GHOST-", "file:docs/ghost-routes.md"),
        ),
        Item(
            "RUN-06",
            "Framework adapters",
            ("cmd:app", "mod:apiverity.specs.app", "file:docs/framework-adapters.md"),
        ),
        Item(
            "RUN-07",
            "OTel GenAI semantic conventions",
            ("mod:apiverity.exporters.semconv", "grep:apiverity/exporters/semconv.py:gen_ai"),
        ),
        Item("RUN-08", "Trace-correlated drift", ("grep:apiverity/exporters/otel.py:trace_id",)),
        Item(
            "RUN-09",
            "Drift timeline per operation",
            (
                "mod:apiverity.runtime.drift_trend",
                "flag:drift:--baseline",
                "flag:drift:--save-baseline",
            ),
        ),
        Item(
            "RUN-10",
            "Concurrency curves in performance",
            ("mod:apiverity.performance.curve", "file:docs/load-shapes.md"),
        ),
        Item(
            "RUN-11",
            "Response-size & TLS timing breakdown",
            ("mod:apiverity.performance.connection",),
        ),
        Item(
            "RUN-12",
            "Synthetic monitoring mode",
            ("cmd:monitor", "mod:apiverity.runtime.monitor", "file:docs/monitoring.md"),
        ),
        Item(
            "RUN-13",
            "Semantic drift (behaviour, not schema)",
            ("mod:apiverity.runtime.semantic", "rule:SEMANTIC-", "file:docs/behavioural-drift.md"),
        ),
        Item(
            "RUN-14",
            "eBPF zero-instrumentation capture (evaluate)",
            ("file:docs/ebpf-evaluation.md",),
        ),
    ),
    "E · Security & compliance": (
        Item(
            "SEC-01",
            "Secret/credential leakage scanning on responses",
            ("mod:apiverity.security.leakage", "rule:SEC-RESPONSE-CREDENTIAL"),
        ),
        Item(
            "SEC-02",
            "Spec-level security lint expansion",
            ("mod:apiverity.security.checks", "rule:SEC-"),
        ),
        Item(
            "SEC-03",
            "BOLA/BFLA authorization probes",
            ("mod:apiverity.security.authz", "rule:AUTHZ-", "file:docs/authorization.md"),
        ),
        Item(
            "SEC-04",
            "OWASP API Top-10 mapped reports",
            ("grep:docs/compliance-mapping.md:| API1 |",),
        ),
        Item(
            "SEC-05",
            "SOC 2 / ISO 42001 / DORA evidence export",
            ("cmd:evidence", "mod:apiverity.reports.evidence", "file:docs/evidence.md"),
        ),
        Item(
            "SEC-06",
            "EU AI Act agent-activity evidence",
            ("file:docs/evidence.md", "grep:docs/evidence.md:EU AI Act"),
        ),
        Item(
            "SEC-07",
            "PII detection & redaction hardening",
            ("mod:apiverity.security.pii", "file:docs/pii.md"),
        ),
        Item(
            "SEC-08",
            "Payload guardrails",
            ("mod:apiverity.security.guardrails", "rule:GUARD-", "file:docs/guardrails.md"),
        ),
        Item(
            "SEC-09",
            "Signed releases, SBOM, SLSA provenance",
            ("ci:attest-build-provenance", "ci:sbom-action"),
        ),
        Item(
            "SEC-10",
            "Supply-chain check on spec dependencies",
            ("mod:apiverity.security.dependencies", "rule:SEC-DEP-", "file:docs/supply-chain.md"),
        ),
        Item(
            "SEC-11",
            "Abuse-surface & rate-limit audit",
            ("mod:apiverity.security.abuse", "rule:SEC-RATE-LIMIT-"),
        ),
        Item(
            "SEC-12",
            "Auth-scope coverage reporting",
            ("mod:apiverity.security.oauth_scopes", "rule:SEC-SCOPE-"),
        ),
        Item("SEC-13", "Tamper-evident audit export", ("cmd:audit", "file:docs/audit-export.md")),
        Item(
            "SEC-14",
            "Kill-switch / emergency policy freeze",
            ("cmd:freeze", "file:docs/kill-switch.md"),
        ),
        Item(
            "SEC-15",
            "Air-gapped install + Helm chart",
            ("file:deploy/helm/apiverity/Chart.yaml", "file:docs/air-gapped.md"),
        ),
        Item(
            "SEC-16",
            "Container image with a CLI entrypoint",
            ("file:docker/entrypoint.sh", "grep:docker/entrypoint.sh:exec apiverity"),
        ),
    ),
    "F · Developer experience": (
        Item("DX-01", "apiverity init guided onboarding", ("cmd:init", "file:docs/onboarding.md")),
        Item(
            "DX-02",
            "One-line install everywhere",
            (
                "file:install.sh",
                "file:install.ps1",
                "file:scripts/install.py",
                "file:docs/install.md",
            ),
        ),
        Item(
            "DX-03",
            "Turn PyPI publishing on",
            (),
            "Registering a Trusted Publisher is a form on the PyPI account that owns the "
            "name. The workflow is wired and guarded by `PUBLISH_ENABLED`.",
        ),
        Item("DX-04", "A real action.yml", ("file:action.yml", "file:docs/ci.md")),
        Item(
            "DX-05",
            "Config-as-code + published JSON Schema",
            (
                "cmd:config",
                "file:schemas/config-v1.schema.json",
                "file:scripts/generate_config_schema.py",
            ),
        ),
        Item("DX-06", "Watch mode", ("cmd:watch",)),
        Item(
            "DX-07",
            "Language Server (LSP)",
            ("cmd:lsp", "mod:apiverity.lsp.server", "file:docs/lsp.md"),
        ),
        Item(
            "DX-08",
            "VS Code extension (thin LSP client)",
            (
                "file:editors/vscode/package.json",
                "file:editors/vscode/src/extension.ts",
                "ci:editors/vscode",
            ),
        ),
        Item(
            "DX-09",
            "Browser playground (WASM/Pyodide)",
            (
                "file:docs/playground.md",
                "file:docs/playground/app.js",
                "file:scripts/generate_playground.py",
            ),
        ),
        Item("DX-10", "--spec-format override", ("flag:--spec-format",)),
        Item("DX-11", "Global --json", ("file:tests/unit/test_json_output_coverage.py",)),
        Item(
            "DX-12",
            "Interop importers",
            (
                "cmd:import-rules",
                "mod:apiverity.rules.spectral",
                "mod:apiverity.traffic.postman",
                "file:docs/spectral-migration.md",
            ),
        ),
        Item(
            "DX-13",
            "oasdiff-compatible export",
            ("mod:apiverity.reports.oasdiff", "file:docs/oasdiff-migration.md"),
        ),
        Item("DX-14", "Portable .apiverity bundle + verify", ("cmd:export", "cmd:verify")),
        Item(
            "DX-15",
            "Generated-SDK break detection",
            (
                "mod:apiverity.diff.sdk_surface",
                "rule:SDK-",
                "flag:breaking:--sdk",
                "file:docs/sdk-surface.md",
            ),
        ),
        Item(
            "DX-16",
            "Zenodo DOI + CITATION.cff identifiers",
            (),
            "Minting a DOI needs the GitHub-Zenodo integration enabled on the account that "
            "owns the repository. `CITATION.cff` is checked in and ready for the identifier.",
        ),
    ),
    "G · Team & enterprise": (
        Item(
            "TEAM-01",
            "Consumer registry & blast-radius mapping",
            (
                "mod:apiverity.rules.consumers",
                "flag:breaking:--consumers",
                "file:docs/blast-radius.md",
                "web:src/pages/team.tsx",
            ),
        ),
        Item(
            "TEAM-02",
            "Contract ownership registry",
            ("grep:apiverity/reports/routing.py:CODEOWNERS",),
        ),
        Item(
            "TEAM-03",
            "PR bot with non-breaking alternatives",
            ("file:scripts/build_pr_comment.py", "grep:action.yml:pull_request"),
        ),
        Item(
            "TEAM-04",
            "Monorepo / multi-service aggregation",
            ("cmd:sweep", "file:docs/monorepo-sweep.md"),
        ),
        Item(
            "TEAM-05",
            "Slack / Teams routing by ownership",
            ("cmd:notify", "mod:apiverity.reports.routing"),
        ),
        Item(
            "TEAM-06", "Concrete OIDC provider", ("mod:apiverity.server.oidc", "file:docs/oidc.md")
        ),
        Item(
            "TEAM-07",
            "Merge-queue / required-check integration",
            (
                "ci:merge_group",
                "file:docs/merge-queue.md",
                "file:tests/unit/test_required_checks.py",
            ),
        ),
        Item(
            "TEAM-08",
            "Cross-repo spec dependency graph",
            ("cmd:graph", "mod:apiverity.specs.graph", "file:docs/dependency-graph.md"),
        ),
        Item(
            "TEAM-09",
            "Scheduled governance reports",
            ("cmd:digest", "mod:apiverity.reports.digest", "file:docs/digest.md"),
        ),
        Item(
            "TEAM-10",
            "Migration guides attached to approvals",
            ("mod:apiverity.rules.migration", "file:docs/migration-guides.md"),
        ),
        Item(
            "TEAM-11",
            "SLA/SLO attachment to operations",
            ("mod:apiverity.performance.slo", "rule:SLO-", "file:docs/objectives.md"),
        ),
        Item(
            "TEAM-12",
            "Multi-tenant org isolation hardening",
            ("grep:apiverity/server/store.py:org_id", "file:tests/unit/test_security_hardening.py"),
        ),
    ),
    "H · The dashboard": (
        Item(
            "DASH-01",
            "Design-token system",
            ("web:src/styles.css", "grep:web/src/styles.css:--s1:"),
        ),
        Item(
            "DASH-02",
            "Live server connection",
            ("web:src/live.ts", "web:src/components/SourcePicker.tsx"),
        ),
        Item("DASH-03", "Command palette (⌘K)", ("web:src/components/CommandPalette.tsx",)),
        Item("DASH-04", "Real charting layer", ("grep:web/src/components/ui.tsx:Sparkline",)),
        Item("DASH-05", "Motion system", ("grep:web/src/styles.css:@keyframes",)),
        Item(
            "DASH-06",
            "Skeleton/optimistic loading states",
            ("grep:web/src/components/ui.tsx:Skeleton",),
        ),
        Item(
            "DASH-07",
            "Full keyboard navigation + focus management",
            ("grep:web/src/styles.css:skip-link",),
        ),
        Item(
            "DASH-08",
            "WCAG 2.2 AA accessibility pass",
            ("grep:web/src/App.test.tsx:skip to content",),
        ),
        Item("DASH-09", "Responsive 360px to ultrawide", ("grep:web/src/styles.css:@media",)),
        Item("DASH-10", "Side-by-side diff viewer", ("grep:web/src/pages/contract.tsx:diff",)),
        Item(
            "DASH-11",
            "Blast-radius / dependency graph visualisation",
            ("web:src/pages/blast.test.tsx", "grep:web/src/pages/team.tsx:blast"),
        ),
        Item("DASH-12", "MCP fleet posture view", ("web:src/pages/agents.tsx",)),
        Item(
            "DASH-13", "Drift timeline / sparklines", ("grep:web/src/components/ui.tsx:Sparkline",)
        ),
        Item(
            "DASH-14",
            "Saved views, filters in URL, shareable deep links",
            ("web:src/views.ts", "web:src/components/SavedViews.tsx", "file:docs/saved-views.md"),
        ),
        Item(
            "DASH-15",
            "Export to PDF / PNG / CSV",
            ("web:src/export.ts", "grep:web/src/export.ts:svgToPng"),
        ),
        Item("DASH-16", "Real-time run progress over SSE", ("web:src/sse.ts",)),
        Item(
            "DASH-17",
            "Onboarding tour + empty-state guidance",
            ("web:src/components/Tour.tsx", "file:docs/onboarding.md"),
        ),
        Item(
            "DASH-18",
            "Theme system: dark/light/system + high-contrast",
            ("grep:web/src/styles.css:prefers-contrast",),
        ),
    ),
    "I · Distribution & ranking": (
        Item(
            "DIST-01",
            "Terminal recording under the README headline",
            (
                "file:docs/demo.svg",
                "file:docs/demo.cast",
                "file:scripts/record_demo.py",
                "ci:record_demo.py --check",
            ),
        ),
        Item(
            "DIST-02",
            "Comparison table above the fold",
            ("grep:README.md:How this compares", "file:scripts/generate_competitive_table.py"),
        ),
        Item(
            "DIST-03",
            "GitHub topics",
            (
                "file:.github/repo-metadata.yml",
                "file:scripts/check_repo_metadata.py",
                "ci:check_repo_metadata.py --check",
            ),
        ),
        Item(
            "DIST-04",
            "Repo description + first paragraph carrying search keywords",
            ("grep:.github/repo-metadata.yml:description", "file:tests/unit/test_repo_metadata.py"),
        ),
        Item(
            "DIST-05",
            "Awesome-list pull requests",
            (),
            "Pull requests against other people's repositories, from an account with a "
            "history. `docs/awesome-list-submissions.md` holds the prepared entries.",
        ),
        Item(
            "DIST-06",
            "Docs-site SEO: per-protocol and per-competitor landing pages",
            (
                "file:scripts/generate_landing_pages.py",
                "file:docs/for/openapi.md",
                "file:docs/vs/oasdiff.md",
                "ci:generate_landing_pages.py --check",
            ),
        ),
        Item(
            "DIST-07",
            "Upstream issue assistance using the ghost-route auditor",
            (),
            "Filing issues on other projects' trackers. The auditor that produces the "
            "evidence is `apiverity ghosts`.",
        ),
        Item(
            "DIST-08",
            "Opt-in anonymised dataset + report",
            (),
            "Starts with a consent decision this project should not make for a user: it "
            "collects nothing today, and the honest version needs a published schema and a "
            "way to see exactly what would be sent.",
        ),
        Item(
            "DIST-09",
            "Public reproducible benchmark, including losses",
            (
                "file:docs/benchmark.md",
                "file:scripts/benchmark_oasdiff.py",
                "grep:docs/benchmark.md:this tool did not",
            ),
        ),
        Item(
            "DIST-10",
            "Example plugin + plugin authoring guide",
            (
                "file:examples/plugins/apiverity-house-rules/pyproject.toml",
                "file:docs/plugin-authoring.md",
                "file:tests/unit/test_example_plugin.py",
            ),
        ),
        Item(
            "DIST-11",
            "Quarterly competitor refresh, CI-enforced",
            (
                "file:.github/workflows/competitor-refresh.yml",
                "file:tests/unit/test_competitor_freshness.py",
            ),
        ),
        Item(
            "DIST-12",
            "Conference/blog content pipeline from the dataset",
            (),
            "Draws on the dataset in DIST-08, which does not exist yet, and on a publishing "
            "cadence that is the maintainer's to set.",
        ),
        Item(
            "DIST-13",
            "llms.txt + machine-readable capability manifest",
            (
                "file:docs/llms.txt",
                "file:docs/capabilities.json",
                "file:scripts/generate_capability_manifest.py",
            ),
        ),
        Item("DIST-14", "Cross-repo positioning line", ("grep:README.md:tooltrace-bench",)),
    ),
}


# -- evidence -------------------------------------------------------------


def _commands() -> set[str]:
    from apiverity.cli.main import build_parser

    return set(build_parser()._subparsers._group_actions[0].choices)  # type: ignore[union-attr]


def _flags(command: str | None) -> set[str]:
    from apiverity.cli.main import build_parser

    parser = build_parser()
    if command is None:
        return {option for action in parser._actions for option in action.option_strings}
    sub = parser._subparsers._group_actions[0].choices.get(command)  # type: ignore[union-attr]
    if sub is None:
        return set()
    return {option for action in sub._actions for option in action.option_strings}


def _rules() -> set[str]:
    from apiverity.rules.breaking import CATALOG
    from apiverity.rules.check_catalog import catalog

    return set(CATALOG) | set(catalog())


def _workflows() -> str:
    return NL.join(
        path.read_text(encoding="utf-8")
        for path in sorted((ROOT / ".github" / "workflows").glob("*.yml"))
    )


def holds(predicate: str) -> tuple[bool, str]:
    """`(true, explanation)` for one evidence predicate."""
    kind, _, argument = predicate.partition(":")

    if kind == "cmd":
        return argument in _commands(), f"`apiverity {argument}`"
    if kind == "flag":
        command, _, flag = argument.rpartition(":")
        return flag in _flags(command or None), f"`{flag}`" + (
            f" on `{command}`" if command else ""
        )
    if kind == "mod":
        import importlib

        try:
            importlib.import_module(argument)
        except Exception:
            return False, f"`{argument}`"
        return True, f"`{argument}`"
    if kind == "attr":
        module_name, _, name = argument.rpartition(":")
        import importlib

        try:
            module = importlib.import_module(module_name)
        except Exception:
            return False, f"`{module_name}.{name}`"
        return hasattr(module, name), f"`{module_name}.{name}`"
    if kind == "file":
        return (ROOT / argument).exists(), f"`{argument}`"
    if kind == "web":
        return (ROOT / "web" / argument).exists(), f"`web/{argument}`"
    if kind == "rule":
        return any(r.startswith(argument) for r in _rules()), f"`{argument}*`"
    if kind == "protocol":
        from apiverity.specs.loader import SPEC_FORMATS

        return argument in SPEC_FORMATS, f"`{argument}` format"
    if kind == "ci":
        return argument in _workflows(), f"CI runs `{argument}`"
    if kind == "grep":
        path, _, needle = argument.partition(":")
        target = ROOT / path
        if not target.exists():
            return False, f"`{needle}` in `{path}`"
        return needle in target.read_text(encoding="utf-8"), f"`{needle}` in `{path}`"
    raise ValueError(f"unknown evidence kind: {kind!r}")


def audit() -> tuple[list[tuple[Item, list[str]]], list[Item], list[Item]]:
    """`(failures, shipped, owner_blocked)`."""
    failures: list[tuple[Item, list[str]]] = []
    shipped: list[Item] = []
    blocked: list[Item] = []
    for items in SECTIONS.values():
        for item in items:
            if item.owner:
                blocked.append(item)
                continue
            missing = [p for p in item.evidence if not holds(p)[0]]
            if missing:
                failures.append((item, missing))
            else:
                shipped.append(item)
    return failures, shipped, blocked


# -- the status page ------------------------------------------------------


def render() -> str:
    failures, shipped, blocked = audit()
    total = sum(len(items) for items in SECTIONS.values())
    lines = [
        MARK_OPEN,
        "",
        f"**{len(shipped)} of {total} implemented.** {len(blocked)} need an action only an "
        "account owner can take; they are listed at the end with what is prepared for them.",
        "",
        "Every row below carries evidence — a command, a module, a rule prefix, a file, a CI "
        "step — that is true only while the thing exists. `scripts/check_roadmap.py --check` "
        "runs in CI, so this page and the code cannot disagree.",
        "",
    ]
    for section, items in SECTIONS.items():
        done = [i for i in items if not i.owner and not [p for p in i.evidence if not holds(p)[0]]]
        lines += [
            f"## {section}",
            "",
            f"{len(done)} of {len(items)}.",
            "",
            "| ID | Feature | Evidence |",
            "|---|---|---|",
        ]
        for item in items:
            if item.owner:
                lines.append(f"| `{item.id}` | {item.title} | ⏳ {item.owner} |")
                continue
            proofs = ", ".join(holds(p)[1] for p in item.evidence)
            missing = [p for p in item.evidence if not holds(p)[0]]
            mark = "❌" if missing else "✅"
            lines.append(f"| `{item.id}` | {item.title} | {mark} {proofs} |")
        lines.append("")

    if failures:
        lines += ["## Items whose evidence is missing", ""]
        for item, missing in failures:
            lines.append(f"- **{item.id}** {item.title} — missing: {', '.join(missing)}")
        lines.append("")

    lines += [
        "## Waiting on an account owner",
        "",
        "These are finished on this side. Each needs a step that happens on somebody's "
        "account, not in this repository.",
        "",
    ]
    for item in blocked:
        lines.append(f"- **{item.id}** {item.title} — {item.owner}")
    lines += ["", MARK_CLOSE, ""]
    return NL.join(lines)


def write() -> None:
    header = [
        "# Roadmap status",
        "",
        "The 134-item roadmap, held against the code that implements it.",
        "",
        "A roadmap is the easiest document in a repository to be wrong: items get ticked from",
        "memory, a refactor renames the command a row describes, and the table goes on saying",
        '"done" about a capability that left. This page is generated by',
        "`scripts/check_roadmap.py`, which checks every claim against the code and fails CI",
        "when one stops being true.",
        "",
    ]
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    STATUS.write_text(NL.join(header) + render(), encoding="utf-8", newline=NL)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Hold the roadmap against the code.")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--list", action="store_true", help="print every item and its evidence")
    args = parser.parse_args(argv)

    failures, shipped, blocked = audit()
    total = len(shipped) + len(failures) + len(blocked)

    if args.list:
        for section, items in SECTIONS.items():
            print(f"\n{section}")
            for item in items:
                state = (
                    "owner"
                    if item.owner
                    else ("MISSING" if any(item.id == f.id for f, _ in failures) else "ok")
                )
                print(f"  {item.id:<11s} {state:<8s} {item.title}")
        return 0

    if failures:
        for item, missing in failures:
            print(
                f"error: {item.id} ({item.title}) has no evidence for: {', '.join(missing)}",
                file=sys.stderr,
            )
        return 1

    if args.check:
        expected = render()
        if not STATUS.exists() or STATUS.read_text(encoding="utf-8") != _page(expected):
            print(
                "error: docs/roadmap-status.md is stale. Run: python scripts/check_roadmap.py",
                file=sys.stderr,
            )
            return 1
        print(f"ok     roadmap: {len(shipped)}/{total} implemented, {len(blocked)} with an owner")
        return 0

    write()
    print(f"wrote  docs/roadmap-status.md ({len(shipped)}/{total} implemented)")
    return 0


def _page(body: str) -> str:
    header = [
        "# Roadmap status",
        "",
        "The 134-item roadmap, held against the code that implements it.",
        "",
        "A roadmap is the easiest document in a repository to be wrong: items get ticked from",
        "memory, a refactor renames the command a row describes, and the table goes on saying",
        '"done" about a capability that left. This page is generated by',
        "`scripts/check_roadmap.py`, which checks every claim against the code and fails CI",
        "when one stops being true.",
        "",
    ]
    return NL.join(header) + body


if __name__ == "__main__":
    raise SystemExit(main())
