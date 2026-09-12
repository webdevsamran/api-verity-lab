"""Render docs/oasdiff-migration.md from the mapping in the code.

The question a team switching from oasdiff actually has is "which of my `jq`
filters will stop matching". A hand-written answer to that goes stale the first
time somebody adds a rule, and a stale migration table is worse than none: it
promises a filter still works after it has stopped.

So the table is generated from `apiverity.reports.oasdiff` and `--check` fails
when the committed file no longer matches.
"""

from __future__ import annotations

import pathlib
import sys

# `scripts/` so `page_meta` resolves, the repository root so `apiverity`
# does. Running this as a script puts the first one on the path; loading
# it by file location -- which is how the tests load it -- puts neither.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from page_meta import front_matter

from apiverity.reports.oasdiff import (
    FOREIGN_PREFIX,
    MAPPING,
    NO_EXACT_MATCH,
    STATUS_MAPPING,
    coverage,
)
from apiverity.rules.breaking import CATALOG

NL = chr(10)
ROOT = pathlib.Path(__file__).resolve().parents[1]
TARGET = ROOT / "docs" / "oasdiff-migration.md"

_HEADER = """# Migrating from oasdiff

Migration cost is the real competitor. A team already gating on
[oasdiff](https://github.com/oasdiff/oasdiff) has `jq` filters, ignore-lists and
dashboards keyed on its output, and asking them to rewrite all of that to *try*
something else is asking for more than a trial is worth.

```bash
apiverity report ./bundle --format oasdiff
```

writes the same shape `oasdiff breaking -f json` does: a bare JSON array of
change objects, most severe first, so an existing filter keeps matching.

**This page is generated** from `apiverity/reports/oasdiff.py`. A hand-written
migration table goes stale the first time somebody adds a rule, and a stale one
is worse than none — it promises a filter still works after it has stopped.

## What was verified, and when

Checked **{checked}** against `oasdiff/oasdiff` at `main`, release
**{version}**, Apache-2.0.

`formatters/changes.go` defines the emitted object: `id`, `text`, `comment`,
`disclaimers`, `level`, `operation`, `operationId`, `path`, `section`,
`attributes`, `baseSource`, `revisionSource`, `fingerprint` — all `omitempty`
except `level`. `checker/source.go` makes `baseSource`/`revisionSource`
`{{file, line, column, endLine, endColumn}}`. `checker/rules/level.go` declares
`type Level int` with `ERR = 3`, `WARN = 2`, `INFO = 1`, `NONE = 0`,
`INVALID = -1` and **no** `MarshalJSON` — so `level` is a *number*, not the
string its `String()` method returns. That last one is the detail a
from-memory implementation gets wrong.

"""


def render() -> str:
    detail = coverage()
    out = [
        front_matter("oasdiff-migration.md")
        + _HEADER.format(checked=detail["checked_on"], version=detail["oasdiff_version_checked"])
    ]

    out.append("## Rules that map exactly" + NL)
    out.append("| This tool | oasdiff |")
    out.append("|---|---|")
    for rule, mapped in sorted(MAPPING.items()):
        out.append(f"| `{rule}` | `{mapped}` |")
    for rule, (success, other) in sorted(STATUS_MAPPING.items()):
        out.append(f"| `{rule}` (2xx) | `{success}` |")
        out.append(f"| `{rule}` (other) | `{other}` |")
    out.append("")

    out.append("## Rules with a near miss, and why they are not mapped" + NL)
    out.append(
        "These come out as `" + FOREIGN_PREFIX + "<rule id>`, which cannot collide with an "
        "oasdiff check id and can be grepped for. Each one is a decision somebody can "
        "argue with rather than an omission." + NL
    )
    out.append("| This tool | Why not |")
    out.append("|---|---|")
    for rule, reason in sorted(NO_EXACT_MATCH.items()):
        out.append(f"| `{rule}` | {reason} |")
    out.append("")

    mapped_ids = set(MAPPING) | set(STATUS_MAPPING)
    unmapped = sorted(set(CATALOG) - mapped_ids - set(NO_EXACT_MATCH))
    out.append("## Rules with no oasdiff counterpart at all" + NL)
    out.append(
        "oasdiff reads OpenAPI. A protobuf field number, an MCP annotation and a SOAPAction "
        "have no check to map onto, so these are namespaced too — listed rather than left "
        "for somebody to discover when a filter silently stops matching." + NL
    )
    for rule in unmapped:
        out.append(f"- `{rule}` — {CATALOG[rule].description}")
    out.append("")

    out.append("## Fields this export does not write" + NL)
    out.append("| Field | Why |")
    out.append("|---|---|")
    for field, reason in detail["omitted_fields"].items():
        out.append(f"| `{field}` | {reason} |")
    out.append("")

    out.append("## Contracts that are not OpenAPI" + NL)
    out.append(
        "Every finding from a gRPC, GraphQL, AsyncAPI, MCP or WSDL contract is namespaced, "
        "whatever its rule. A removed gRPC RPC really is an endpoint removal, but emitting "
        "`api-removed-without-deprecation` for one would make a consumer's tooling report "
        "an OpenAPI endpoint removal that never happened." + NL
    )

    total = len(CATALOG)
    exact = len(mapped_ids)
    out.append(
        f"_{exact} of {total} rules map onto an oasdiff check id; the other "
        f"{total - exact} are namespaced._" + NL
    )
    return NL.join(out)


def main() -> int:
    rendered = render()
    previous = TARGET.read_text(encoding="utf-8") if TARGET.is_file() else None
    if previous == rendered:
        print(f"ok     {TARGET.name} ({len(MAPPING) + len(STATUS_MAPPING)} mapped rules)")
        return 0
    if "--check" in sys.argv:
        print(
            "error: docs/oasdiff-migration.md is stale; run scripts/generate_oasdiff_map.py",
            file=sys.stderr,
        )
        return 1
    TARGET.write_text(rendered, encoding="utf-8", newline=NL)
    print(f"wrote  {TARGET.name} ({len(MAPPING) + len(STATUS_MAPPING)} mapped rules)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
