"""Landing pages, generated from what the tool measurably does.

Every project's docs site eventually grows a page per protocol and a page per
competitor, and they are almost always written once by hand and never read
again by their author. They then go on asserting coverage the engine lost and
comparisons that stopped being true, to readers who arrived from a search and
have no other source.

So these are generated:

* **`docs/for/<protocol>.md`** — the rules that *actually fire* for a format,
  measured by perturbing that format's own shipped fixture, the same way
  `docs/rule-parity.md` is measured. A rule listed here has been observed
  firing on that protocol in this build.
* **`docs/vs/<tool>.md`** — one page per competitor that shares a lane, built
  from `data/competitive-capabilities.json`: their strengths in their words,
  the capability matrix in both directions, and the dated evidence. A
  comparison that only lists what the other tool lacks is marketing, so the
  generator refuses to emit a page with no strengths recorded.

    python scripts/generate_landing_pages.py           # rewrite
    python scripts/generate_landing_pages.py --check   # verify, exit 1 on drift
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
# `scripts/` too, because this imports `generate_rule_parity` for its contract
# list. Running as a script puts it there; being imported by a test does not.
sys.path.insert(0, str(Path(__file__).resolve().parent))

FOR = ROOT / "docs" / "for"
VS = ROOT / "docs" / "vs"
CAPABILITIES = ROOT / "data" / "competitive-capabilities.json"
META = ROOT / "data" / "competitor-meta.json"

NL = chr(10)

#: How each protocol is introduced, and the command a reader of that page
#: wants. The measured rule list is generated; this is the part that needs a
#: person, and it is short on purpose -- prose nobody can check is prose that
#: rots.
PROTOCOLS: dict[str, dict[str, str]] = {
    "openapi": {
        "title": "OpenAPI breaking changes",
        "lead": (
            "OpenAPI 3.0, 3.1 and 3.2, plus Swagger 2.0. Paths, parameters, request and "
            "response schemas, security schemes, and the 3.2 additions: the `query` method, "
            "`additionalOperations`, `querystring` parameters and hierarchical tags."
        ),
        "command": "apiverity breaking openapi-v1.yaml openapi-v2.yaml --check-semver",
    },
    "swagger2": {
        "title": "Swagger 2.0 breaking changes",
        "lead": (
            "Swagger 2.0 compiles into the same contract model as OpenAPI 3, so the same "
            "rules run against it -- and a 2.0 document can be diffed against a 3.x one."
        ),
        "command": "apiverity breaking swagger.json openapi.yaml",
    },
    "asyncapi": {
        "title": "AsyncAPI breaking changes",
        "lead": (
            "AsyncAPI 2.x and 3.x: channels, messages and payload schemas, with diffing "
            "that knows which direction a channel runs. A payload field removed from a "
            "message you publish breaks your subscribers; one removed from a message you "
            "subscribe to breaks you."
        ),
        "command": "apiverity breaking events-v1.yaml events-v2.yaml",
    },
    "grpc": {
        "title": "gRPC and protobuf breaking changes",
        "lead": (
            "`.proto` sources and compiled descriptor sets. Field numbers, presence, "
            "streaming, reserved ranges -- the things that break a generated stub while "
            "leaving the service definition looking similar."
        ),
        "command": "apiverity breaking users_v1.proto users_v2.proto",
    },
    "mcp": {
        "title": "MCP tool manifest breaking changes",
        "lead": (
            "A saved `tools/list` response, diffed under the same rules as any other "
            "contract, plus a `BRK-MCP-*` family for the parts that are MCP's alone: "
            "annotation hints, `outputSchema` presence and tool-description edits. An "
            "agent routes on the description, so a silent edit to one is a change to what "
            "your agents do."
        ),
        "command": "apiverity breaking tools-v1.json tools-v2.json",
    },
    "wsdl": {
        "title": "SOAP and WSDL breaking changes",
        "lead": (
            "WSDL 1.1: portTypes, bindings and the XSD subset a WSDL actually uses, plus a "
            "`BRK-SOAP-*` family for SOAPAction, binding style and SOAP version -- the "
            "three facts that break every generated stub while leaving every message schema "
            "identical."
        ),
        "command": "apiverity breaking orders-v1.wsdl orders-v2.wsdl",
    },
    "openapi (2020-12)": {
        "title": "JSON Schema 2020-12 breaking changes",
        "lead": (
            "OpenAPI 3.1 aligned with JSON Schema 2020-12, which brought keywords the "
            "older rules could not see: `prefixItems`, `if`/`then`, `dependentRequired`, "
            "`patternProperties`. These rules fire only against a contract that uses them."
        ),
        "command": "apiverity breaking v1.yaml v2.yaml",
    },
}

#: Capabilities that put a tool in the same lane. A page comparing this project
#: with a load-testing tool would be a page about two unrelated things, and
#: publishing fourteen of those is how a docs site becomes noise. A tool
#: qualifies by doing at least one of these -- `no` in every one of them is not
#: a shared lane.
SHARED_LANES = (
    "openapi-diff",
    "breaking-change-rules",
    "semver-verdicts",
    "linting",
    "schema-driven-fuzzing",
    "drift-detection",
    "response-validation",
)

#: What provides each capability *here*.
#:
#: The evidence file's matrix has a column per competitor and none for this
#: project -- it was gathered to describe them, not us. Filling the gap with an
#: unsourced "yes" in every row would be the thing this repository exists to
#: not do, so each claim names the command that provides it, and
#: `tests/unit/test_landing_pages.py` asserts every one of those commands
#: exists in the CLI.
#:
#: `None` is a real answer and appears as `no`.
OURS: dict[str, str | None] = {
    "openapi-diff": "apiverity diff",
    "breaking-change-rules": "apiverity breaking",
    "semver-verdicts": "apiverity breaking --check-semver",
    "linting": "apiverity validate",
    "schema-driven-fuzzing": "apiverity test",
    "stateful-workflows": "apiverity workflow",
    "response-validation": "apiverity test",
    "mock-server": "apiverity mock",
    "service-virtualization": "apiverity mock --workspace",
    "drift-detection": "apiverity drift",
    "traffic-replay": "apiverity replay",
    "load-testing": "apiverity regression --shape",
    "performance-budgets": "apiverity regression",
    "consumer-contracts": "apiverity breaking --consumers",
    "can-i-deploy": "apiverity serve (/v1/can-i-deploy)",
    # Pact's broker is a service with a publication protocol, and this project
    # does not implement one. Saying `partial` here would be claiming a thing
    # nobody could find.
    "broker-publication": None,
    "graphql-breaking": "apiverity breaking",
    "grpc-compat": "apiverity breaking",
    "asyncapi-support": "apiverity breaking",
    "plugin-api": "apiverity plugins",
    "self-hosted-server": "apiverity serve",
    "rbac-audit": "apiverity audit",
    "sarif-export": "apiverity report --format sarif",
    "otel-export": "apiverity test --otlp-endpoint",
    "frontend-ui": "apiverity serve (web/)",
}

MARK = "<!-- generated:landing -->"


def _slug(name: str) -> str:
    keep = [c if c.isalnum() else "-" for c in name.lower()]
    return "-".join(part for part in "".join(keep).split("-") if part)


# -- protocol pages -------------------------------------------------------


def measured() -> Any:
    """Which rules fire for which protocol, by making them fire."""
    from generate_rule_parity import CONTRACTS  # the same fixtures rule-parity uses

    from apiverity.rules.parity import measure_parity
    from apiverity.specs.loader import detect_and_load

    services = {}
    for label, path in CONTRACTS.items():
        service, _, _ = detect_and_load(str(path))
        services[label] = service
    return measure_parity(services)


def protocol_page(label: str, rules: set[str], catalog: dict[str, Any]) -> str:
    spec = PROTOCOLS[label]
    # Some rule ids fire and have no catalogue entry. Dropping them silently
    # would make this page's count disagree with the engine's; rendering them
    # with an empty description would send a reader to a catalogue that does
    # not have them. They are named instead, as the gap they are.
    documented = sorted(rule_id for rule_id in rules if rule_id in catalog)
    undocumented = sorted(rule_id for rule_id in rules if rule_id not in catalog)
    lines = [
        f"# {spec['title']}",
        "",
        MARK,
        "",
        spec["lead"],
        "",
        "```bash",
        spec["command"],
        "```",
        "",
        f"## The {len(documented)} catalogued rules observed firing on {label}",
        "",
        "Measured, not asserted: this format's own shipped fixture is perturbed in each of",
        "several dozen ways and the result is whatever the rules said. A rule listed here",
        "was seen firing on this protocol in this build; one that is absent was not, which",
        "may mean the rule does not apply or that no mutation reached it.",
        "",
        "| Rule | Severity | What it means |",
        "|---|---|---|",
    ]
    for rule_id in documented:
        entry = catalog[rule_id]
        severity = getattr(getattr(entry, "severity", None), "value", "")
        description = getattr(entry, "description", "") or ""
        lines.append(f"| `{rule_id}` | {severity} | {description.replace('|', '/')} |")

    if undocumented:
        lines += [
            "",
            f"### {len(undocumented)} more fired here and are not in the catalogue",
            "",
            "Recorded rather than dropped. A rule id a reader receives and cannot look up is",
            "the defect this project has fixed in its own README twice, and hiding it here",
            "would make this page's count disagree with the engine's.",
            "",
        ]
        lines += [f"- `{rule_id}`" for rule_id in undocumented]

    lines += [
        "",
        "[The full catalogue](../rule-catalog.md) has the rationale and the remediation for",
        "each. [Rule parity](../rule-parity.md) is the same measurement across every format",
        "at once.",
        "",
        "## The rest of the toolchain speaks this format too",
        "",
        "One contract model means the other commands are not separate tools:",
        "",
        "```bash",
        "apiverity validate contract          # lint and security checks",
        "apiverity changelog old new          # a human changelog of the same diff",
        "apiverity coverage contract          # which operations your tests reach",
        "apiverity drift contract --base-url  # does the running service still match?",
        "```",
        "",
        "[Protocol support](../protocol-support.md) is the full matrix of what each format",
        "supports, and what it does not.",
        "",
    ]
    return NL.join(lines)


# -- competitor pages -----------------------------------------------------


def _has(value: str) -> bool:
    """Whether a matrix cell claims the capability at all."""
    return value.strip().lower().split()[0] in {"yes", "partial"} if value.strip() else False


def _matrix_rows(matrix: dict[str, Any], tool: str) -> list[tuple[str, str, str]]:
    rows = []
    for capability, values in matrix.items():
        if capability.startswith("_") or not isinstance(values, dict):
            continue
        theirs = values.get(tool)
        if theirs is None:
            continue
        ours = OURS.get(capability)
        rows.append((capability, str(theirs), f"yes — `{ours}`" if ours else "no"))
    return rows


def competitor_page(entry: dict[str, Any], matrix: dict[str, Any], fetched: str) -> str | None:
    name = entry["name"]
    rows = _matrix_rows(matrix, name)
    if not any(capability in SHARED_LANES and _has(theirs) for capability, theirs, _ in rows):
        # Nothing in common. A page comparing a contract governance engine with
        # a load generator would be a page about two unrelated things.
        return None
    if not entry.get("strengths"):
        # A comparison that lists only what the other tool lacks is marketing.
        # Refusing is better than publishing one.
        return None

    repo = entry.get("github_repo") or ""
    lines = [
        f"# api-verity-lab compared with {name}",
        "",
        MARK,
        "",
        "Generated from `data/competitive-capabilities.json`, which is gathered by",
        f"`scripts/fetch_competitor_meta.py`. Repository facts below were fetched {fetched}.",
        "",
        "| | |",
        "|---|---|",
    ]
    if repo:
        lines.append(f"| Repository | [{repo}](https://github.com/{repo}) |")
    for label, key in (
        ("Licence", "license_spdx"),
        ("Stars", "stars"),
        ("Latest release", "latest_release_tag"),
        ("Deployment", "deployment_model"),
        ("Audience", "target_audience"),
    ):
        value = entry.get(key)
        if value:
            lines.append(f"| {label} | {value} |")

    lines += ["", f"## What {name} is good at", ""]
    lines += [f"- {item}" for item in entry["strengths"]]
    lines += [
        "",
        f"That list is from the evidence file, not from this project's opinion of {name}.",
        "A comparison page that only enumerated the other tool's gaps would be an",
        "advertisement, and this project's whole credibility rests on claims a reader can",
        "check.",
        "",
    ]

    tradeoffs = entry.get("weaknesses_or_tradeoffs") or []
    if tradeoffs:
        lines += ["## Where it stops", ""]
        lines += [f"- {item}" for item in tradeoffs]
        lines.append("")

    coverage = entry.get("protocol_coverage") or []
    if coverage:
        lines += [
            "## Protocols",
            "",
            f"**{name}:** {', '.join(coverage)}",
            "",
            "**api-verity-lab:** OpenAPI 3.0/3.1/3.2, Swagger 2.0, AsyncAPI 2.x/3.x, "
            "GraphQL SDL, gRPC (proto and descriptor sets), MCP tool manifests, WSDL 1.1.",
            "",
        ]

    lines += [
        "## Capability by capability",
        "",
        f"| | {name} | api-verity-lab |",
        "|---|---|---|",
    ]
    for capability, theirs, ours in sorted(rows):
        lines.append(f"| {capability.replace('-', ' ')} | {theirs} | {ours} |")

    lines += [
        "",
        f"The {name} column is `yes` / `partial` / `no` / `unknown` from the evidence file,",
        "with `no` recorded only where the absence is verifiable or the area is clearly",
        "outside that product's documented scope; the legend and the evidence notes are in",
        "the data file. The api-verity-lab column names the command that provides each one,",
        "because that column is not in the evidence file -- it was gathered to describe other",
        "tools -- and an unsourced `yes` in every row is the thing this project exists to not",
        "do. A test asserts every command named there exists.",
        "",
        "## Using both",
        "",
        f"Nothing here argues for replacing {name}. A tool that owns its lane is worth using",
        "in it; this project's claim is a different one -- one contract model and one result",
        "format across every protocol you speak, including the ones your agents speak.",
        "",
        "[The full comparison](../competitive-analysis.md) covers every tool at once, and",
        "[the benchmark](../benchmark.md) is reproducible, including where this project",
        "loses.",
        "",
    ]
    return NL.join(lines)


# -- entry point ----------------------------------------------------------


def render() -> dict[Path, str]:
    """Every page this generator owns, as `{path: content}`."""
    from apiverity.rules.breaking import CATALOG

    pages: dict[Path, str] = {}

    result = measured()
    for label, rules in result.by_protocol.items():
        if label not in PROTOCOLS:
            continue
        pages[FOR / f"{_slug(label)}.md"] = protocol_page(label, set(rules), CATALOG)

    capabilities = json.loads(CAPABILITIES.read_text(encoding="utf-8"))
    fetched = str(json.loads(META.read_text(encoding="utf-8")).get("fetched_utc", "")).split("T")[0]
    matrix = capabilities["capability_matrix"]
    for entry in capabilities["competitors"]:
        page = competitor_page(entry, matrix, fetched)
        if page is not None:
            pages[VS / f"{_slug(entry['name'])}.md"] = page
    return pages


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    pages = render()

    if args.check:
        existing = {
            p for directory in (FOR, VS) if directory.exists() for p in directory.glob("*.md")
        }
        stale = sorted(p.name for p in existing - set(pages))
        if stale:
            print(
                f"error: these pages are no longer generated and are still committed: {stale}. "
                "Run: python scripts/generate_landing_pages.py",
                file=sys.stderr,
            )
            return 1
        for path, content in sorted(pages.items()):
            if not path.exists() or path.read_text(encoding="utf-8") != content:
                print(
                    f"error: docs/{path.parent.name}/{path.name} no longer matches the code. "
                    "Run: python scripts/generate_landing_pages.py",
                    file=sys.stderr,
                )
                return 1
        print(f"ok     {len(pages)} landing pages match the measurement and the evidence file")
        return 0

    for directory in (FOR, VS):
        directory.mkdir(parents=True, exist_ok=True)
        for existing in directory.glob("*.md"):
            # A page dropped from the generator must not linger: a committed
            # comparison with a tool no longer in the evidence file is a page
            # nothing updates.
            if existing not in pages:
                existing.unlink()
    for path, content in sorted(pages.items()):
        path.write_text(content, encoding="utf-8", newline=NL)
    print(f"wrote  {len(pages)} landing pages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
