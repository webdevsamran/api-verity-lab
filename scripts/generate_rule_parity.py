"""Render docs/rule-parity.md by making the rules fire.

The catalogue has sixty-five rules and the tool speaks six formats, and nothing
told a GraphQL user which of the sixty-five could apply to them. The obvious
answer is a hand-written table, which is the one this project will not accept:
a matrix asserting coverage it does not have is worse than no matrix, because
it gets quoted.

So every protocol's shipped contract is loaded, perturbed in each of several dozen
ways, and diffed against itself. Whatever the rules say is what the table says.

Run after adding a rule or a mutation; `--check` fails when the committed file
is stale.
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from apiverity.rules.breaking import CATALOG
from apiverity.rules.parity import MUTATIONS, ParityResult, measure_parity
from apiverity.specs.loader import detect_and_load

NL = chr(10)
ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"

#: One contract per protocol. Its own shipped fixture, so the table describes
#: the parsers as they are rather than a contract written to flatter them.
CONTRACTS: dict[str, pathlib.Path] = {
    "openapi": FIXTURES / "apis" / "versioned" / "v1.yaml",
    "swagger2": FIXTURES / "apis" / "crud" / "openapi.yaml",
    "asyncapi": FIXTURES / "asyncapi" / "events-v1.yaml",
    "grpc": FIXTURES / "grpc" / "users_v1.proto",
    "mcp": FIXTURES / "mcp" / "tools_v1.json",
    # A second OpenAPI column, because the 2020-12 rules can only fire against
    # a contract that uses those keywords. Listing them as unproduced when the
    # only fixture measured is a 3.0-shaped one would say something about the
    # fixture and read as something about the engine.
    "openapi (2020-12)": FIXTURES / "apis" / "jsonschema2020" / "v1.yaml",
}

_HEADER = """# Rule parity across protocols

Which of the breaking-change rules actually fire, for each format this tool
reads.

**This table is derived, not asserted.** Each protocol's shipped contract is
loaded into the normalized model, perturbed in each of the ways listed below,
and diffed against itself; the cells record what the rules said. A matrix
claiming coverage nobody demonstrated is worse than no matrix, because it is
the kind of thing that gets quoted in an evaluation.

## How to read an empty cell

It means **no mutation here produced that rule for that protocol**. It does not
mean the rule cannot fire. The mutation list is finite and deliberately small —
changes a person would actually make — so an empty cell is a fact
about this harness, not a limit of the engine.

The useful signal is the *shape*: a rule that fires for one protocol and not
another usually means the second format cannot express the change, or its
parser does not carry the field the rule reads. `BRK-FIELD-NUMBER-*` firing only
for gRPC is the model working correctly; a schema rule firing only for OpenAPI
would be a parser that is not populating something.

"""


def _load() -> tuple[dict[str, object], dict[str, str]]:
    contracts: dict[str, object] = {}
    unavailable: dict[str, str] = {}
    for protocol, path in CONTRACTS.items():
        if not path.is_file():
            unavailable[protocol] = f"no fixture at {path.relative_to(ROOT).as_posix()}"
            continue
        try:
            contracts[protocol] = detect_and_load(str(path))[0]
        except Exception as exc:  # a parser that cannot read its own fixture
            unavailable[protocol] = str(exc)
    return contracts, unavailable


def render(result: ParityResult) -> str:
    protocols = sorted(result.by_protocol)
    out = [_HEADER]

    out.append("## What was changed" + NL)
    out.append("| Mutation | Stands for |")
    out.append("|---|---|")
    for mutation in MUTATIONS:
        out.append(f"| {mutation.name} | {mutation.describes} |")
    out.append("")

    if result.unavailable:
        out.append("## Protocols not measured" + NL)
        out.append(
            "Reported rather than left out of the table: a column nobody produced and a "
            "column of empty cells look identical." + NL
        )
        for protocol, reason in sorted(result.unavailable.items()):
            out.append(f"- **{protocol}** — {reason}")
        out.append("")

    out.append("## Rules" + NL)
    header = "| Rule | Severity | " + " | ".join(protocols) + " |"
    out.append(header)
    out.append("|---" * (2 + len(protocols)) + "|")

    never: list[str] = []
    for rule_id, spec in sorted(CATALOG.items()):
        cells = []
        seen_anywhere = False
        for protocol in protocols:
            fired = rule_id in result.by_protocol[protocol]
            seen_anywhere = seen_anywhere or fired
            cells.append("✓" if fired else "")
        if not seen_anywhere:
            never.append(rule_id)
        out.append(f"| `{rule_id}` | {spec.severity.value} | " + " | ".join(cells) + " |")
    out.append("")

    out.append("## Rules no mutation produced" + NL)
    out.append(
        "The interesting column. Each of these is either a mutation this harness does not "
        "make, or a rule no input can produce — and the second is a defect this project has "
        "found four separate times. Listed rather than hidden in a table of empty cells." + NL
    )
    if never:
        for rule_id in never:
            out.append(f"- `{rule_id}` — {CATALOG[rule_id].description}")
    else:
        out.append("_None: every rule in the catalogue fired for at least one protocol._")
    out.append("")

    fired_total = len(CATALOG) - len(never)
    out.append(
        f"_{fired_total} of {len(CATALOG)} rules observed firing across "
        f"{len(protocols)} protocol(s) and {len(MUTATIONS)} mutations._" + NL
    )
    return NL.join(out)


def main() -> int:
    contracts, unavailable = _load()
    result = measure_parity(contracts)  # type: ignore[arg-type]
    result.unavailable = unavailable
    rendered = render(result)

    target = ROOT / "docs" / "rule-parity.md"
    previous = target.read_text(encoding="utf-8") if target.is_file() else None
    if previous == rendered:
        print(f"ok     {target.name} ({len(result.rules_seen())} rules observed)")
        return 0
    if "--check" in sys.argv:
        print(
            "error: docs/rule-parity.md is stale; run scripts/generate_rule_parity.py",
            file=sys.stderr,
        )
        return 1
    target.write_text(rendered, encoding="utf-8", newline=NL)
    print(f"wrote  {target.name} ({len(result.rules_seen())} rules observed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
