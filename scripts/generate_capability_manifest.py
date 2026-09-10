"""Render `docs/llms.txt` and `docs/capabilities.json` from the code.

Two audiences, one source.

`llms.txt` is the emerging convention for telling a language model what a
project is and which documents matter, in one file at the site root. Without
one, a model answering "does api-verity-lab check MCP servers?" is working from
whatever a crawler happened to index, which for a young repository is the
README and nothing else.

`capabilities.json` is the same answer for software: every command, every
protocol, every rule id, the exit codes, and the published schemas. An agent
deciding whether this tool can do a job should not have to parse `--help`.

Both are generated, because a hand-written capability list is a claim that
rots. This project has fixed that same defect four times in its own docs; the
file that tells other people's tools what it can do is the last place to leave
it to memory.

    python scripts/generate_capability_manifest.py            # write
    python scripts/generate_capability_manifest.py --check    # fail if stale
"""

from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from apiverity import __version__
from apiverity.cli.main import build_parser
from apiverity.core.model import Protocol
from apiverity.rules.alternatives import ALTERNATIVES
from apiverity.rules.breaking import CATALOG

ROOT = pathlib.Path(__file__).resolve().parents[1]
LLMS = ROOT / "docs" / "llms.txt"
CAPABILITIES = ROOT / "docs" / "capabilities.json"

#: Documents worth pointing a reader at, in the order a newcomer needs them.
#: Kept here rather than globbed, because "every file in docs/" is not a
#: reading order and an index without one is a directory listing.
_GUIDE: tuple[tuple[str, str, str], ...] = (
    (
        "Rule catalog",
        "rule-catalog.md",
        "Every breaking-change rule, its severity, and the non-breaking alternative",
    ),
    (
        "Spec support",
        "spec-support.md",
        "Which spec versions and constructs are read, and which are not",
    ),
    ("Protocol support", "protocol-support.md", "What each of the seven protocols supports"),
    (
        "Exit codes",
        "exit-codes.md",
        "The exit-code contract, and how it differs from sibling projects",
    ),
    ("MCP drift", "mcp-drift.md", "Declared tool manifest against a running MCP server"),
    (
        "MCP tool poisoning",
        "mcp-poisoning.md",
        "Reading a tool description as executable text (OWASP MCP03)",
    ),
    ("MCP lockfile", "mcp-lock.md", "A reviewed baseline for an agent's tool surface"),
    ("MCP inventory", "mcp-inventory.md", "Shadow MCP servers, found by reading client configs"),
    ("Call budgets", "call-budgets.md", "How often an agent may call each tool"),
    ("Blast radius", "blast-radius.md", "Which consumers a breaking change affects"),
    ("Ghost routes", "ghost-routes.md", "Routes the contract deleted that the deployment kept"),
    ("Inferred contracts", "inferred-contracts.md", "Drafting a contract from recorded traffic"),
    (
        "Monorepo sweep",
        "monorepo-sweep.md",
        "Every contract in a tree, with an owner and a verdict",
    ),
    (
        "Compliance mapping",
        "compliance-mapping.md",
        "Findings mapped onto OWASP MCP, Agentic and API Top 10",
    ),
    (
        "Evidence packs",
        "evidence.md",
        "Dated, checksummed records for SOC 2, ISO 42001, DORA, EU AI Act",
    ),
    (
        "Audit export",
        "audit-export.md",
        "The hash-chained audit log as a document checkable away from the server",
    ),
    ("CI integration", "ci.md", "Wiring the gate into a pipeline"),
    ("Safety model", "safety-model.md", "What this tool will and will not do to a target"),
    ("Privacy", "privacy.md", "What reaches an artifact, and what never does"),
    ("Self-hosting", "self-hosting.md", "Running the server"),
    ("SDK", "sdk.md", "Using the library directly"),
    ("Architecture", "architecture.md", "How the one contract model works"),
    (
        "Competitive analysis",
        "competitive-analysis.md",
        "Verified, dated comparison with other tools",
    ),
)

_SITE = "https://webdevsamran.github.io/api-verity-lab"


def _commands() -> list[dict[str, object]]:
    """Every subcommand, its one-line help, and its flags.

    The help text lives on the *parent's* choice action, not on the subparser
    -- `add_parser(help=...)` records it there. Reading `subparser.description`
    instead produced an empty summary for every command, which is the kind of
    field that looks populated in a schema and says nothing in a file.
    """
    parser = build_parser()
    assert parser._subparsers is not None
    action = parser._subparsers._group_actions[0]
    helps = {choice.dest: (choice.help or "").strip() for choice in action._choices_actions}

    out: list[dict[str, object]] = []
    for name in sorted(action.choices):
        sub = action.choices[name]
        out.append(
            {
                "name": name,
                "summary": helps.get(name, ""),
                "options": sorted(
                    flag.option_strings[0]
                    for flag in sub._actions
                    if flag.option_strings and flag.option_strings[0] != "-h"
                ),
            }
        )
    return out


def _spec_plugins() -> list[dict[str, str]]:
    """The loaders, each with the protocol it compiles into.

    Deliberately not a list of protocol *values*. Two plugins map onto
    `openapi` -- OpenAPI 3.x and Swagger 2.0 -- so a set of values reports five
    formats where six exist, and the `Protocol` enum reports seven because it
    carries `sse` and `websocket`, which are kinds of AsyncAPI channel rather
    than documents anyone hands to a command. Neither number is wrong; they
    answer different questions, so both are published under names that say
    which question.
    """
    from apiverity.specs.loader import _builtin_plugins

    return sorted(
        (
            {
                "plugin": type(plugin).__name__,
                "protocol": plugin.protocol().value,
            }
            for plugin in _builtin_plugins()
        ),
        key=lambda entry: entry["plugin"],
    )


def _format_count() -> int:
    from apiverity.specs.loader import _builtin_plugins

    return len(_builtin_plugins())


def render_capabilities() -> str:
    from apiverity.cli.commands.common import (
        EXIT_FINDINGS,
        EXIT_INTERNAL,
        EXIT_OK,
        EXIT_UNREACHABLE,
        EXIT_USAGE,
    )

    payload = {
        "name": "api-verity-lab",
        "version": __version__,
        "summary": (
            "API contract governance across seven protocols: diff, breaking-change rules, "
            "runtime drift, performance budgets and agent-tool governance under one contract "
            "model and one result format."
        ),
        "repository": "https://github.com/webdevsamran/api-verity-lab",
        "documentation": _SITE,
        "license": "Apache-2.0",
        "spec_plugins": _spec_plugins(),
        "protocol_values": [p.value for p in Protocol],
        "commands": _commands(),
        "rules": {
            "count": len(CATALOG),
            "ids": sorted(CATALOG),
            "every_rule_has_an_alternative": set(CATALOG) <= set(ALTERNATIVES),
        },
        "exit_codes": {
            "ok": EXIT_OK,
            "findings": EXIT_FINDINGS,
            "usage": EXIT_USAGE,
            "unreachable": EXIT_UNREACHABLE,
            "internal": EXIT_INTERNAL,
        },
        "schemas": {
            "result": "schemas/result-v1.schema.json",
            "config": "schemas/config-v1.schema.json",
        },
        "generated_by": "scripts/generate_capability_manifest.py",
    }
    return json.dumps(payload, indent=2) + "\n"


def render_llms() -> str:
    parser = build_parser()
    assert parser._subparsers is not None
    commands = sorted(parser._subparsers._group_actions[0].choices)

    formats = {4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight"}[_format_count()]

    lines = [
        "# api-verity-lab",
        "",
        f"> API contract governance across {formats} formats -- OpenAPI 3.0/3.1/3.2, Swagger 2.0,",
        "> AsyncAPI 2.x/3.x, GraphQL, gRPC and MCP tool manifests -- under one normalized",
        "> contract model and one versioned result format. Diffs contracts, classifies",
        f"> breaking changes against {len(CATALOG)} rules with stable ids, detects runtime drift",
        "> against live services and recorded traffic, governs the tool surface agents call,",
        "> and measures performance budgets.",
        "",
        "Apache-2.0. Python 3.11+. No telemetry. Every claim in these documents is either",
        "generated from the code or carries a dated source; counts in prose are bound to the",
        "thing they count by a test.",
        "",
        "## What it is for",
        "",
        "- Failing a pull request that breaks an API contract, with the rule id and the",
        "  non-breaking alternative.",
        "- Telling whether a running service still matches the contract its consumers were",
        "  given.",
        "- Governing what an AI agent can call: tool-manifest diffing, declared-versus-live",
        "  drift, tool-description poisoning, authentication posture, and a reviewed baseline.",
        "",
        "## Docs",
        "",
    ]
    for title, path, description in _GUIDE:
        lines.append(f"- [{title}]({_SITE}/{path.removesuffix('.md')}/): {description}")

    lines += [
        "",
        "## Machine-readable",
        "",
        f"- [capabilities.json]({_SITE}/capabilities.json): every command, protocol, rule id and",
        "  exit code, generated from the code",
        f"- [result-v1 schema]({_SITE}/../schemas/result-v1.schema.json): the artifact contract",
        "  every command writes",
        "",
        "## Commands",
        "",
        ", ".join(f"`{name}`" for name in commands) + ".",
        "",
        "## What it does not do",
        "",
        "- It does not authenticate, deploy, or modify a target service.",
        "- It does not send traffic anywhere it was not explicitly pointed at, and never",
        "  invokes an MCP tool without a named opt-in.",
        "- It does not claim a compliance control is satisfied; it produces the records an",
        "  auditor maps.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    check = "--check" in sys.argv
    stale: list[str] = []
    for target, rendered in ((LLMS, render_llms()), (CAPABILITIES, render_capabilities())):
        previous = target.read_text(encoding="utf-8") if target.is_file() else None
        if previous == rendered:
            print(f"ok     {target.name}")
            continue
        if check:
            stale.append(target.name)
            continue
        target.write_text(rendered, encoding="utf-8")
        print(f"wrote  {target.name}")
    if stale:
        print(
            f"error: {', '.join(stale)} stale; run scripts/generate_capability_manifest.py",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
