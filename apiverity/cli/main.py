"""apiverity command-line interface.

All commands support ``--json`` and stable exit codes:
0 ok · 1 findings at/above threshold · 2 usage error ·
3 target unreachable · 4 internal error.

Command implementations live in ``apiverity.cli.commands``, grouped by
product lane; this module owns argument parsing and process exit codes.
"""

from __future__ import annotations

import argparse
import contextlib
import sys
from typing import Any

from apiverity import __version__
from apiverity.cli.commands.artifacts import (
    cmd_evidence,
    cmd_export,
    cmd_report,
    cmd_serve,
    cmd_verify,
)
from apiverity.cli.commands.common import (
    EXIT_INTERNAL,
    EXIT_OK,
    load_project_config,
    set_allow_remote_refs,
    set_profile,
    set_spec_format,
)
from apiverity.cli.commands.governance import (
    cmd_breaking,
    cmd_changelog,
    cmd_diff,
    cmd_infer,
    cmd_sweep,
    cmd_validate,
)
from apiverity.cli.commands.platform import (
    cmd_audit,
    cmd_explain,
    cmd_freeze,
    cmd_notify,
    cmd_plugins,
    cmd_rules,
    cmd_self_test,
    cmd_server_db,
    cmd_watch,
)
from apiverity.cli.commands.project import cmd_config, cmd_init
from apiverity.cli.commands.runtime import (
    cmd_baseline,
    cmd_budget,
    cmd_drift,
    cmd_ghosts,
    cmd_mcp_inventory,
    cmd_mcp_lock,
    cmd_regression,
    cmd_replay,
)
from apiverity.cli.commands.testing import (
    cmd_coverage,
    cmd_mock,
    cmd_test,
    cmd_workflow,
)
from apiverity.rules.profiles import PROFILES
from apiverity.runtime.mcp_lock import DEFAULT_KEY_ENV, DEFAULT_LOCK_NAME
from apiverity.specs.loader import SPEC_FORMATS

__all__ = [
    "build_parser",
    "cmd_audit",
    "cmd_baseline",
    "cmd_breaking",
    "cmd_budget",
    "cmd_changelog",
    "cmd_config",
    "cmd_coverage",
    "cmd_diff",
    "cmd_drift",
    "cmd_evidence",
    "cmd_explain",
    "cmd_export",
    "cmd_freeze",
    "cmd_ghosts",
    "cmd_infer",
    "cmd_init",
    "cmd_mcp_inventory",
    "cmd_mcp_lock",
    "cmd_mock",
    "cmd_notify",
    "cmd_plugins",
    "cmd_regression",
    "cmd_replay",
    "cmd_report",
    "cmd_rules",
    "cmd_self_test",
    "cmd_serve",
    "cmd_server_db",
    "cmd_sweep",
    "cmd_test",
    "cmd_validate",
    "cmd_verify",
    "cmd_watch",
    "cmd_workflow",
    "main",
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="apiverity", description=__doc__)
    parser.add_argument("--version", action="version", version=f"apiverity {__version__}")
    parser.add_argument(
        "--profile",
        choices=list(PROFILES),
        help=(
            "severity profile: a starting position every other setting overrides. "
            "`strict` raises every WARN in the catalogue to ERROR; `balanced` is the "
            "catalogue as shipped; `advisory` reports without blocking"
        ),
    )
    parser.add_argument(
        "--config",
        metavar="PATH",
        dest="project_config",
        help=(
            "project config to apply (default: the nearest .apiverity.yaml, searching "
            "upward). Its severity overrides, suppressions file and fail-on threshold "
            "apply to this run"
        ),
    )
    parser.add_argument(
        "--no-config",
        action="store_true",
        help="ignore .apiverity.yaml entirely, for a run that must not inherit project policy",
    )
    parser.add_argument(
        "--spec-format",
        choices=list(SPEC_FORMATS),
        help=(
            "load every contract as this format instead of sniffing its content. "
            "Detection matches substrings, so a GraphQL schema that discusses OpenAPI, "
            "or a tool manifest whose description mentions a service, is otherwise "
            "unloadable by any means"
        ),
    )
    parser.add_argument(
        "--allow-remote-refs",
        action="store_true",
        help=(
            "let a `$ref` naming a URL be fetched when bundling a multi-file contract. "
            "Off by default: a URL inside a document makes this process request an "
            "address you never chose. Relative file refs are always followed"
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser(
        "init",
        help="detect this project's contracts and write .apiverity.yaml",
    )
    p.add_argument("directory", nargs="?", default=".")
    p.add_argument("--force", action="store_true", help="overwrite an existing config")
    p.add_argument("--dry-run", action="store_true", help="report what would be written")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("config", help="validate or show the project config")
    p.add_argument("action", nargs="?", default="validate", choices=["validate", "show"])
    p.add_argument("--path", help="config file (default: nearest .apiverity.yaml)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_config)

    p = sub.add_parser(
        "sweep",
        help="every contract in a tree, with an owner and a verdict for each",
    )
    p.add_argument("root", nargs="?", default=".", help="directory to walk")
    p.add_argument(
        "--base",
        metavar="DIR",
        help=(
            "a checkout to compare against, path for path -- a base branch in a worktree, "
            "so a monorepo gets one breaking-change verdict instead of one per service"
        ),
    )
    p.add_argument("--limit", type=int, default=500, help="stop after this many contracts")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_sweep)

    p = sub.add_parser(
        "infer",
        help="draft a contract from recorded traffic, labelled as a draft",
    )
    p.add_argument("corpus", help="a HAR of recorded requests and responses")
    p.add_argument("-o", "--output", help="write the document here (.yaml or .json)")
    p.add_argument("--title", help="what to call the API in the drafted document")
    p.add_argument(
        "--infer-enums",
        action="store_true",
        help=(
            "guess an enum from repeated string values. Off by default: a fabricated "
            "constraint is worse than an absent one, because it turns a valid request into "
            "a reported violation"
        ),
    )
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_infer)

    p = sub.add_parser(
        "validate",
        help="load a contract, report what is wrong with the document itself",
    )
    p.add_argument("spec")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_validate)
    p = sub.add_parser(
        "diff",
        help="every semantic change between two contracts, with a stable id each",
    )
    p.add_argument("old")
    p.add_argument("new")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_diff)
    p = sub.add_parser(
        "breaking",
        help="classify those changes against the rule catalogue and fail on the breaking ones",
    )
    p.add_argument("old")
    p.add_argument("new")
    p.add_argument("--check-semver", action="store_true")
    p.add_argument("--old-version")
    p.add_argument("--new-version")
    p.add_argument("--require-minor-for-warnings", action="store_true")
    p.add_argument(
        "--summary",
        action="store_true",
        help=(
            "also render a plain-English summary -- what changed, who it affects, what to "
            "do -- suitable for a pull request description. Deterministic templates, no "
            "model call"
        ),
    )
    p.add_argument(
        "--suggest-version",
        action="store_true",
        help=(
            "also recommend the next version, with the rule ids that forced it. The "
            "policy has always had every input needed to answer this and only ever "
            "said whether the version you picked was wrong"
        ),
    )
    p.add_argument(
        "--suggest-fix",
        action="store_true",
        help=(
            "attach the non-breaking alternative to each finding: the way to make the same "
            "change additively. A gate that only says no gets switched off"
        ),
    )
    p.add_argument(
        "--consumers",
        metavar="FILE",
        help=(
            "a consumer registry, so a finding names whose build breaks. Annotation only: "
            "the severity is untouched unless the registry declares itself complete and "
            "--severity-by-consumers is also given"
        ),
    )
    p.add_argument(
        "--severity-by-consumers",
        action="store_true",
        help=(
            "report an ERROR with no registered consumer at WARN. Requires a registry with "
            "`complete: true`, because 'no consumer listed' and 'no consumer exists' are "
            "different statements and only one of them is safe to act on"
        ),
    )
    p.add_argument("--severity-override", action="append")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_breaking)
    p = sub.add_parser(
        "changelog",
        help="a release note for a version bump, in markdown or HTML",
    )
    p.add_argument("old")
    p.add_argument("new")
    p.add_argument("--html", action="store_true")
    p.add_argument("--json", action="store_true")
    p.add_argument("--output")
    p.set_defaults(func=cmd_changelog)
    p = sub.add_parser(
        "test",
        help="generate cases from the schema and run them against a live service",
    )
    p.add_argument("spec")
    p.add_argument("--base-url")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument(
        "--generator",
        action="append",
        metavar="NAME",
        help=(
            "add a case-generation strategy beyond the schema-derived ones. "
            "Repeatable; 'all' selects every registered generator. See "
            "--list-generators."
        ),
    )
    p.add_argument(
        "--list-generators",
        action="store_true",
        help="list available generators, including installed third-party ones, and exit",
    )
    p.add_argument(
        "--operations",
        action="append",
        metavar="FILE.graphql",
        help=(
            "a document of persisted GraphQL operations to run alongside the "
            "generated ones. Repeatable."
        ),
    )
    p.add_argument(
        "--include-mutations",
        action="store_true",
        help=(
            "also generate mutation cases. Off by default: a generated mutation "
            "is a write against whatever --base-url names."
        ),
    )
    p.add_argument("--timeout", type=float, default=10.0)
    p.add_argument("--minimize", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_test)
    p = sub.add_parser(
        "workflow",
        help="run a multi-step workflow manifest, or infer a draft from a contract",
    )
    p.add_argument("manifest", help="a workflow manifest to run, or a spec with --infer")
    p.add_argument("--base-url")
    p.add_argument(
        "--infer",
        action="store_true",
        help=(
            "read a spec instead of a manifest and print a draft workflow, "
            "built only from the `links` objects the spec declares. Every step "
            "is commented out; destructive ones are commented twice."
        ),
    )
    p.add_argument(
        "--template",
        metavar="NAME",
        help="emit a built-in manifest template instead of running one (see --list-templates)",
    )
    p.add_argument("--list-templates", action="store_true", help="list built-in templates and exit")
    p.add_argument("-o", "--output", help="write the draft to a file instead of stdout")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_workflow)
    p = sub.add_parser(
        "mock",
        help="serve a deterministic mock of a contract, with optional misbehaviour",
    )
    p.add_argument("spec")
    p.add_argument("--port", type=int, default=8090)
    p.add_argument("--latency-ms", type=int, default=0)
    p.add_argument("--force-status", type=int)
    p.add_argument("--malformed", action="store_true")
    p.add_argument("--rate-limit-after", type=int)
    p.add_argument(
        "--json",
        action="store_true",
        help="print the bound address as an artifact before serving, for scripts",
    )
    p.set_defaults(func=cmd_mock)
    p = sub.add_parser(
        "coverage",
        help="which operations and statuses a run actually exercised",
    )
    p.add_argument("spec")
    p.add_argument("--exercised", nargs="*")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_coverage)
    p = sub.add_parser(
        "drift",
        help="the declared contract against a live service, a recorded corpus or an MCP server",
    )
    p.add_argument("spec")
    p.add_argument(
        "--base-url",
        help="probe this live service (mutually exclusive with --corpus)",
    )
    p.add_argument(
        "--corpus",
        help=(
            "compare a recorded HAR corpus against the contract instead of "
            "probing; findings are aggregated with a frequency per operation"
        ),
    )
    p.add_argument(
        "--against-corpus",
        metavar="FILE",
        help=(
            "an earlier corpus to compare behaviour against. Reports what the service "
            "stopped doing while the contract stayed valid: an optional field that is no "
            "longer populated, an enum value that no longer appears, a null rate that "
            "jumped. Requires --corpus"
        ),
    )
    p.add_argument(
        "--min-samples",
        type=int,
        default=None,
        metavar="N",
        help=(
            "how many responses an operation needs on each side before behaviour is "
            "compared (default 20). Below it the comparison says nothing, because three "
            "responses then two is not evidence of anything"
        ),
    )
    p.add_argument(
        "--baseline",
        metavar="FILE",
        help=(
            "a recorded baseline; findings in it are reported as `known` and only new ones "
            "fail the run. A gate that goes red on its first run against an API with history "
            "gets made advisory and never comes back"
        ),
    )
    p.add_argument(
        "--save-baseline",
        metavar="FILE",
        help="write this run's findings as a baseline for later comparison",
    )
    p.add_argument(
        "--include-response-bodies",
        action="store_true",
        help=(
            "read response bodies from the corpus so schema drift can be "
            "checked; redaction still applies, and they are excluded by "
            "default because a HAR of a real service holds real user data"
        ),
    )
    p.add_argument(
        "--allow-undeclared-fields",
        action="store_true",
        help="do not report response fields the contract does not declare",
    )
    p.add_argument(
        "--header",
        action="append",
        metavar="NAME=VALUE",
        help=(
            "header to present on every MCP request, repeatable. The MCP spec lets a "
            "server's tool set vary by the authorization presented, so a report from an "
            "unauthenticated probe records that it was one; values never reach the artifact"
        ),
    )
    p.add_argument(
        "--max-list-pages",
        type=int,
        default=50,
        metavar="N",
        help=(
            "stop after N pages of an MCP tools/list. If the cap is reached, declared "
            "tools that were not seen are NOT reported missing -- they may be on a later page"
        ),
    )
    p.add_argument(
        "--otlp-endpoint",
        metavar="URL",
        help=(
            "POST this run's spans to an OTLP/HTTP collector. Spans follow the "
            "OpenTelemetry GenAI conventions for MCP, so a drift finding lands beside the "
            "agent traffic already in your tracing backend. Opt-in: nothing leaves the "
            "machine without this, and bodies and credentials never become attributes"
        ),
    )
    p.add_argument(
        "--skip-auth-probe",
        action="store_true",
        help=(
            "do not assess the MCP server's authentication posture. The probe is one extra "
            "read-only tools/list with any credential headers stripped, which is the only way "
            "to learn whether the credentials were doing anything"
        ),
    )
    p.add_argument(
        "--invoke-tool",
        action="append",
        metavar="NAME",
        help=(
            "also call this MCP tool and check the result against its declared "
            "outputSchema. Exact names only -- a glob against a live tool list would let "
            "the server choose what runs. Repeatable. Prints a plan and sends nothing "
            "unless --execute is also given"
        ),
    )
    p.add_argument(
        "--execute",
        action="store_true",
        help="actually send the --invoke-tool calls instead of printing the plan",
    )
    p.add_argument(
        "--i-know-this-is-production",
        action="store_true",
        help="required to --execute against a target that does not classify as local/dev/staging",
    )
    p.add_argument(
        "--seed",
        type=int,
        default=0,
        help="seed for generated tool arguments; recorded in the artifact",
    )
    p.add_argument("--timeout", type=float, default=10.0)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_drift)
    p = sub.add_parser(
        "budget",
        help="check observed calls against a declared call budget",
    )
    p.add_argument("calls", help="a HAR, or a call log naming operations or tools")
    p.add_argument("--budget", required=True, metavar="FILE", help="the budget to enforce")
    p.add_argument(
        "--spec",
        help=(
            "the contract, needed to resolve a HAR's concrete URLs to operations and to "
            "report a limit naming an operation that does not exist"
        ),
    )
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_budget)

    p = sub.add_parser(
        "mcp-inventory",
        help="list the MCP servers this machine is configured to reach, and flag unapproved ones",
    )
    p.add_argument("root", nargs="?", default=".", help="project root to read configs under")
    p.add_argument(
        "--config",
        action="append",
        metavar="PATH",
        help="an additional client config to read. Repeatable",
    )
    p.add_argument(
        "--inventory",
        metavar="FILE",
        help="an approved-server list; anything configured and absent from it is reported",
    )
    p.add_argument(
        "--include-home",
        action="store_true",
        help=(
            "also read the known client configs in the home directory. Off by default: a "
            "project checkout is what a CI run is entitled to look at"
        ),
    )
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_mcp_inventory)

    p = sub.add_parser(
        "mcp-lock",
        help="write or check mcp.lock, a reviewed baseline for an MCP tool surface",
    )
    p.add_argument("action", choices=["write", "check"])
    p.add_argument(
        "source",
        nargs="?",
        help="a saved tools/list manifest. Omit and pass --base-url to capture a live one",
    )
    p.add_argument("--base-url", help="capture the surface from a live server (read-only)")
    p.add_argument(
        "--lock",
        help=f"lockfile path (default: {DEFAULT_LOCK_NAME})",
    )
    p.add_argument("--force", action="store_true", help="overwrite an existing lockfile")
    p.add_argument(
        "--surface-version",
        help=(
            "the version this surface is being released as. An MCP tool carries no version "
            "field and SEP-1575 is dormant, so the version lives in the file you own"
        ),
    )
    p.add_argument(
        "--sign",
        action="store_true",
        help=(
            "add an HMAC over the lock, keyed from --key-env. It detects an edit made by "
            "something that did not hold the key; it is not provenance"
        ),
    )
    p.add_argument(
        "--key-env", help=f"environment variable holding the key (default: {DEFAULT_KEY_ENV})"
    )
    p.add_argument("--require-minor-for-warnings", action="store_true")
    p.add_argument("--header", action="append", metavar="NAME=VALUE")
    p.add_argument("--max-list-pages", type=int, default=50)
    p.add_argument("--timeout", type=float, default=10.0)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_mcp_lock)
    p = sub.add_parser(
        "ghosts",
        help="find routes the contract no longer declares that the server still answers",
    )
    p.add_argument("spec", help="the current contract")
    p.add_argument("--base-url", required=True, help="the deployment to ask")
    p.add_argument(
        "--was",
        metavar="SPEC",
        help="a previous contract; its operations that this one dropped become candidates",
    )
    p.add_argument(
        "--corpus",
        metavar="HAR",
        help="a recorded corpus; paths it used that this contract does not match become candidates",
    )
    p.add_argument("--timeout", type=float, default=10.0)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_ghosts)

    p = sub.add_parser(
        "replay",
        help="replay a sanitized traffic corpus, dry-run by default",
    )
    p.add_argument("har")
    p.add_argument("--base-url", required=True)
    p.add_argument("--allow-host", action="append", required=True)
    p.add_argument("--execute", action="store_true")
    p.add_argument("--rate", type=float, default=10.0)
    p.add_argument("--i-know-this-is-production", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_replay)
    p = sub.add_parser(
        "baseline",
        help="measure latency percentiles and store them for later comparison",
    )
    p.add_argument("spec")
    p.add_argument("--base-url", required=True)
    p.add_argument("-o", "--output", default="perf-baseline.json")
    p.add_argument(
        "--slo",
        action="store_true",
        help=(
            "measure against the `x-slo` block each operation declares, instead of "
            "against a --policy somebody typed. A run is a sample and an objective is a "
            "promise over a window, so a finding says this run exceeded it -- not that "
            "the objective was breached"
        ),
    )
    p.add_argument("--iterations", type=int, default=20)
    p.add_argument(
        "--warmup",
        type=int,
        default=0,
        help=(
            "requests made before measuring and excluded from the samples; "
            "use the same value here as in the regression run it will be "
            "compared against"
        ),
    )
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_baseline)
    p = sub.add_parser(
        "regression",
        help="measure again and fail when latency or error rate regressed past a tolerance",
    )
    p.add_argument("spec")
    p.add_argument("--base-url", required=True)
    p.add_argument("--baseline")
    p.add_argument(
        "--policy",
        action="append",
        metavar="BUDGET",
        help=(
            "a per-operation budget, repeatable: 'GET /users p95 <= 250ms', "
            "'GET /users error_rate <= 1%%', 'GET /users bytes_p95 <= 256KB'. Size units are "
            "decimal (KB is 1,000), because that is what somebody typing 256KB into a budget "
            "means"
        ),
    )
    p.add_argument(
        "--tolerance",
        action="append",
        metavar="PCT|METRIC=PCT",
        help=(
            "regression tolerance: a percentage for every metric (--tolerance 15) "
            "or per metric (--tolerance p95=10 --tolerance error_rate=0). "
            "Repeatable; default 20 for all."
        ),
    )
    p.add_argument("--iterations", type=int, default=20)
    p.add_argument(
        "--warmup",
        type=int,
        default=0,
        help="requests made before measuring and excluded from the samples",
    )
    p.add_argument(
        "--concurrency",
        type=int,
        default=1,
        metavar="N",
        help=(
            "requests in flight at once. A p95 measured one-at-a-time answers "
            "'is it fast right now' and not 'what happens when more arrive'"
        ),
    )
    p.add_argument(
        "--curve",
        metavar="LEVELS",
        nargs="?",
        const="1,2,4,8",
        help=(
            "sweep concurrency and report the shape: where throughput stops rising and "
            "where latency starts climbing. Comma-separated levels, or bare for 1,2,4,8. "
            "Measures this client and that service together, and says so"
        ),
    )
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_regression)
    p = sub.add_parser(
        "report",
        help=(
            "render a result bundle: terminal, markdown, HTML, JUnit, SARIF, "
            "oasdiff's own JSON shape, a pull request comment, or an OWASP mapping"
        ),
    )
    p.add_argument("bundle")
    p.add_argument(
        "--format",
        default="json",
        help=(
            "one of the renderers in apiverity.reports.renderers. `oasdiff` writes the "
            "shape `oasdiff breaking -f json` writes, so an existing filter keeps "
            "matching -- see docs/oasdiff-migration.md for which rules map"
        ),
    )
    p.set_defaults(func=cmd_report)
    p = sub.add_parser(
        "export",
        help="write a portable .apiverity bundle with checksums",
    )
    p.add_argument("--data", required=True)
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--spec")
    p.add_argument("--config")
    p.add_argument("--workflow")
    p.add_argument("--perf")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_export)
    p = sub.add_parser(
        "evidence",
        help="assemble result artifacts into a dated, checksummed evidence pack",
    )
    p.add_argument("artifacts", nargs="+", help="result JSON files or exported bundle directories")
    p.add_argument("-o", "--output", required=True, help="directory to write the pack into")
    p.add_argument(
        "--as-of",
        help=(
            "timestamp to record instead of now. The pack is deliberately not reproducible "
            "byte-for-byte -- an evidence record with no date is not evidence -- and this "
            "rebuilds a historical one"
        ),
    )
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_evidence)

    p = sub.add_parser(
        "verify",
        help="check a bundle against its own SHA256SUMS",
    )
    p.add_argument("bundle", help="path to a .apiverity bundle directory")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_verify)
    p = sub.add_parser(
        "serve",
        help="serve a bundle over HTTP for local viewing",
    )
    p.add_argument("directory")
    p.add_argument("--port", type=int, default=8080)
    p.add_argument(
        "--json",
        action="store_true",
        help="print the bound address as an artifact before serving, for scripts",
    )
    p.set_defaults(func=cmd_serve)
    p = sub.add_parser("server-db", help="backup/restore/export/import a server database")
    p.add_argument("action", choices=["backup", "restore", "export", "import"])
    p.add_argument("--db", required=True, help="server SQLite database path")
    p.add_argument("-o", "--output", help="backup file / restored db / export JSON path")
    p.add_argument("--input", help="snapshot JSON to import")
    p.add_argument("--org-id", type=int, help="org id for export")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_server_db)
    p = sub.add_parser(
        "audit",
        help="export the hash-chained audit log, or verify an exported one",
    )
    p.add_argument("action", choices=["export", "verify"])
    p.add_argument("file", nargs="?", help="the export document, for `verify`")
    p.add_argument("--db", help="server SQLite database path, for `export`")
    p.add_argument("--org-id", type=int, help="org whose log to export")
    p.add_argument("-o", "--output", help="write the export document here")
    p.add_argument(
        "--against",
        metavar="FILE",
        help=(
            "an earlier export of the same org. A hash chain proves modification and "
            "reordering; it cannot prove nothing was deleted from the end, and this "
            "comparison is what does"
        ),
    )
    p.add_argument(
        "--hmac-key-env",
        metavar="VAR",
        help=(
            "name of an environment variable holding the seal key. The name, not the "
            "value: a key passed on the command line is in the shell history, the CI "
            "log and the process table"
        ),
    )
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_audit)
    p = sub.add_parser(
        "freeze",
        help="emergency stop: refuse deployments and approvals until lifted",
    )
    p.add_argument(
        "action",
        choices=["on", "off", "status"],
        help=(
            "`status` exits 1 while frozen and 3 when the server cannot be reached, so a "
            "pipeline gating on it fails closed"
        ),
    )
    p.add_argument(
        "--server",
        metavar="URL",
        help="the self-hosted server (or set APIVERITY_SERVER)",
    )
    p.add_argument(
        "--token-env",
        metavar="VAR",
        default="APIVERITY_TOKEN",
        help=(
            "name of an environment variable holding the API token. The name, not the "
            "value: a token on the command line is in the shell history and the process table"
        ),
    )
    p.add_argument("--reason", help="why. Required for `on`, and recorded in the audit log")
    p.add_argument(
        "--review-by",
        metavar="TIMESTAMP",
        help=(
            "an advisory date after which the freeze is reported as overdue for review. "
            "Nothing lifts on it -- a kill switch that releases itself fires exactly when "
            "nobody is watching"
        ),
    )
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_freeze)
    p = sub.add_parser(
        "watch",
        help="re-run a command whenever the files it names change",
    )
    p.add_argument(
        "--interval",
        type=float,
        help="seconds between polls (default 0.4)",
    )
    p.add_argument(
        "--path",
        action="append",
        metavar="PATH",
        help=(
            "an extra file or directory to watch. A directory is walked for "
            "contract-shaped files only, so pointing at a repository does not re-run on "
            "every .pyc"
        ),
    )
    p.add_argument(
        "argv",
        nargs=argparse.REMAINDER,
        help="-- followed by the command to run, e.g. `-- breaking old.yaml new.yaml`",
    )
    p.set_defaults(func=cmd_watch)
    p = sub.add_parser(
        "notify",
        help="route a result artifact's findings to the teams they concern",
    )
    p.add_argument("artifact", help="a result-v1 JSON artifact with a top-level `findings` array")
    p.add_argument(
        "--routes",
        required=True,
        metavar="FILE",
        help="YAML mapping a team to a webhook: `routes: {backend: https://...}`",
    )
    p.add_argument(
        "--consumers",
        metavar="FILE",
        help=(
            "a consumer registry, so the teams that call a broken operation are told too. "
            "Without it only the contract's CODEOWNERS are notified"
        ),
    )
    p.add_argument(
        "--root",
        default=".",
        help="repository root to read CODEOWNERS from (default: the working directory)",
    )
    p.add_argument(
        "--send",
        action="store_true",
        help=(
            "actually POST the messages. Off by default: a tool that posts to a team's "
            "channel as a side effect of being run has done something nobody asked for"
        ),
    )
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_notify)
    p = sub.add_parser(
        "plugins",
        help="list installed plugins across the six entry-point groups",
    )
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_plugins)
    p = sub.add_parser(
        "explain",
        help="explain one rule: what it means, why, and how to change its severity",
    )
    p.add_argument("rule_id", help="a rule id, e.g. BRK-RESP-FIELD-REMOVED (case-insensitive)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_explain)
    p = sub.add_parser(
        "rules",
        help="the whole rule catalogue, with the severities this run would apply",
    )
    p.add_argument(
        "--profiles",
        action="store_true",
        help="list the severity profiles instead of the rules",
    )
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_rules)
    p = sub.add_parser(
        "self-test",
        help="check this installation can load, diff and classify a bundled fixture",
    )
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_self_test)
    return parser


def _use_utf8_streams() -> None:
    """Write UTF-8 on every platform, whatever the console codepage says.

    `apiverity validate` on a contract titled in Japanese exited 4 -- the
    documented code for "an unexpected error inside the tool" -- on a Windows
    console, because Python encodes stdout with the locale codepage and cp1252
    cannot represent those characters. A tool that advertises seven protocols and
    reads contracts written anywhere in the world cannot fail on the name of
    the API. The same crash reached `changelog` (which prints emoji) and any
    finding message containing an arrow.

    The trade is explicit: a legacy console decoding cp1252 will now render
    unfamiliar characters as mojibake instead of killing the run. Wrong-looking
    output beats an exit code that says the tool is broken when the contract is
    fine. `backslashreplace` is the floor beneath that -- if UTF-8 itself could
    not be set, characters degrade to escapes and the run still finishes.

    Guarded because a redirected stream (a test's StringIO, a pipe wrapped by
    something else) may not be reconfigurable, and that is not an error.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        # A stream that cannot be reconfigured is not an error; it is a
        # pipe somebody else already wrapped.
        with contextlib.suppress(ValueError, OSError):
            reconfigure(encoding="utf-8", errors="backslashreplace")


def main(argv: list[str] | None = None) -> int:
    _use_utf8_streams()
    parser = build_parser()
    args = parser.parse_args(argv)
    # Set before dispatch, so a command never reads a value left behind by an
    # earlier `main()` call in the same process -- which the test suite makes
    # routine.
    set_allow_remote_refs(bool(getattr(args, "allow_remote_refs", False)))
    set_spec_format(getattr(args, "spec_format", None))
    # `config` prints the file; every other command applies it. Loading it here
    # means one parse per run and one answer, rather than each command finding
    # its own -- which is how two commands come to disagree about which file
    # governs a directory.
    set_profile(getattr(args, "profile", None))
    load_project_config(
        getattr(args, "project_config", None),
        disabled=bool(getattr(args, "no_config", False)),
    )
    try:
        result: Any = args.func(args)
        return int(result)
    except SystemExit:
        raise
    except KeyboardInterrupt:
        return EXIT_OK
    except Exception as exc:
        print(f"internal error: {exc}", file=sys.stderr)
        return EXIT_INTERNAL


if __name__ == "__main__":
    sys.exit(main())
