"""Render the competitive landscape blocks of docs/competitive-analysis.md.

Three places in this repository told the reader this table was generated:

    README.md          "The table is generated from that file, so it cannot
                        drift from the data it cites."
    docs/index.md:35   "the competitive table is rendered from committed API
                        data. CI fails when a generated file and its source
                        disagree."
    docs/index.md:41   "rendered from data fetched by a checked-in script"

No such script existed. The table was typed by hand -- as the docstring of
`tests/unit/test_competitive_table_matches_data.py` said outright -- and no CI
step checked it. In a repository whose stated rule is "documented output is
captured, never written", the document making that claim was the one document
not honouring it.

That mattered beyond tidiness, because the hand-typed table had already
published a falsehood once: Optic's row read "repo gone (404)" when the project
is archived and public, after the fetcher asked for a repository name that
never existed and the null was transcribed as a fact about a competitor.

So this script exists to make those three claims true. Every rendered value
comes from `data/competitor-meta.json`, and `--check` fails the build when the
committed document disagrees with the committed data.

    python scripts/generate_competitive_table.py            # write
    python scripts/generate_competitive_table.py --check    # verify (CI)

It deliberately does not fetch. `scripts/fetch_competitor_meta.py` needs `gh`
auth and network, so CI cannot run it; what CI can prove is that the prose
matches the committed evidence, which is the half that rots silently. Freshness
is carried by the date this script prints out of the data, never by an
unqualified claim that the numbers are current.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "competitive-analysis.md"
README = ROOT / "README.md"
DATA = ROOT / "data" / "competitor-meta.json"
CAPABILITIES = ROOT / "data" / "competitive-capabilities.json"

#: Repository -> the heading the table uses for it.
#:
#: Editorial, so it lives here rather than in the fetched artifact: a file whose
#: provenance line reads "gh api (authenticated)" should carry what the run
#: established and nothing a human chose. The join is explicit because the
#: obvious implicit one is wrong -- keying on the repository basename collapses
#: `MCPJam/inspector` and `modelcontextprotocol/inspector` onto "inspector" and
#: silently drops whichever is written second.
LABELS: dict[str, str] = {
    "oasdiff/oasdiff": "oasdiff",
    "schemathesis/schemathesis": "Schemathesis",
    "stoplightio/spectral": "Spectral",
    "pact-foundation/pact-js": "Pact (pact-js)",
    "opticdev/optic": "Optic",
    "apiaryio/dredd": "Dredd",
    "stoplightio/prism": "Prism",
    "wiremock/wiremock": "WireMock",
    "SpectoLabs/hoverfly": "Hoverfly",
    "karatelabs/karate": "Karate",
    "grafana/k6": "k6",
    "postmanlabs/newman": "Newman",
    "graphql-hive/graphql-inspector": "GraphQL Inspector",
    "bufbuild/buf": "Buf",
}

MARK_OPEN = "<!-- generated:{name} -->"
MARK_CLOSE = "<!-- /generated:{name} -->"

#: A project with no published release renders as an em dash, as the committed
#: table already does for Newman.
NO_RELEASE = "—"


class RenderError(RuntimeError):
    """The data cannot be rendered without inventing something."""


def load_meta() -> dict[str, Any]:
    return json.loads(DATA.read_text(encoding="utf-8"))


def load_capabilities() -> dict[str, Any]:
    return json.loads(CAPABILITIES.read_text(encoding="utf-8"))


#: Keys inside a capability row that are not a competitor.
_NOT_A_TOOL = frozenset({"evidence_note", "_legend"})


def coverage(capabilities: dict[str, Any]) -> list[tuple[str, int]]:
    """How many capability areas each competitor covers, most first.

    A `yes`, however qualified -- "yes (GraphQL)", "yes (protobuf)" -- counts;
    a `partial` does not. The point of the number is the *spread*, not a score:
    it is the same classification the full matrix publishes, counted rather
    than read one row at a time.
    """
    matrix = capabilities.get("capability_matrix")
    if not isinstance(matrix, dict):
        raise RenderError("competitive-capabilities.json has no `capability_matrix`")
    counts: dict[str, int] = {}
    areas = 0
    for area, row in matrix.items():
        if area in _NOT_A_TOOL or not isinstance(row, dict):
            continue
        areas += 1
        for tool, verdict in row.items():
            if tool in _NOT_A_TOOL:
                continue
            counts.setdefault(tool, 0)
            if isinstance(verdict, str) and verdict.startswith("yes"):
                counts[tool] += 1
    if not counts:
        raise RenderError("the capability matrix names no competitors")
    return sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))


def capability_area_count(capabilities: dict[str, Any]) -> int:
    matrix = capabilities.get("capability_matrix") or {}
    return sum(
        1 for area, row in matrix.items() if area not in _NOT_A_TOOL and isinstance(row, dict)
    )


def fetch_date(meta: dict[str, Any]) -> str:
    """The date the evidence was gathered, as ``YYYY-MM-DD``."""
    stamp = meta.get("fetched_utc")
    if not isinstance(stamp, str) or len(stamp) < 10:
        raise RenderError("competitor-meta.json has no usable `fetched_utc`")
    return stamp[:10]


#: A quarter, in days. The claim this document makes is not "these are the
#: numbers" -- it is "these were the numbers on this date", and that claim
#: stays true forever. What decays is its usefulness: a competitor's star count
#: and last release from eighteen months ago are accurate history and a
#: misleading comparison, and the reader cannot tell the difference from the
#: table alone.
DEFAULT_MAX_AGE_DAYS = 92


def evidence_age_days(meta: dict[str, Any], *, today: date | None = None) -> int:
    """How old the committed evidence is, in whole days."""
    gathered = date.fromisoformat(fetch_date(meta))
    return ((today or date.today()) - gathered).days


def freshness_message(meta: dict[str, Any], max_age: int, *, today: date | None = None) -> str:
    age = evidence_age_days(meta, today=today)
    return (
        f"data/competitor-meta.json was gathered {age} days ago "
        f"({fetch_date(meta)}), over the {max_age}-day refresh interval. "
        "Run: python scripts/fetch_competitor_meta.py && "
        "python scripts/generate_competitive_table.py"
    )


def _release_cell(entry: dict[str, Any]) -> str:
    release = entry.get("latest_release")
    if not isinstance(release, dict):
        return NO_RELEASE
    tag = release.get("tag")
    published = release.get("published_at")
    if not tag:
        return NO_RELEASE
    if isinstance(published, str) and len(published) >= 10:
        return f"{tag} ({published[:10]})"
    return str(tag)


def _row(repo: str, entry: dict[str, Any]) -> str:
    label = LABELS.get(repo)
    if label is None:
        raise RenderError(
            f"{repo} is in data/competitor-meta.json with no entry in LABELS. Add its "
            "table heading to scripts/generate_competitive_table.py -- a fetched "
            "competitor the table cannot name is one the table silently omits."
        )
    stars = entry.get("stars")
    if not isinstance(stars, int):
        raise RenderError(f"{repo}: no star count in the artifact; the fetch established none")
    pushed = entry.get("pushed_at")
    if not isinstance(pushed, str) or len(pushed) < 10:
        raise RenderError(f"{repo}: no `pushed_at` in the artifact")
    licence = entry.get("license_spdx") or "unverified"
    status = "**archived**" if entry.get("archived") else "active"
    return (
        f"| {label} | {licence} | {stars:,} | {pushed[:10]} | {_release_cell(entry)} | {status} |"
    )


def render_provenance(meta: dict[str, Any]) -> str:
    return (
        f"Generated: {fetch_date(meta)} · Evidence: live GitHub API metadata "
        "(see `data/competitor-meta.json`) + documented product models. "
        "Full machine-readable matrix: `data/competitive-capabilities.json`."
    )


def render_method(meta: dict[str, Any]) -> str:
    return (
        "- Repo license, stars, last push, archived status and latest release fetched "
        f"**live on {fetch_date(meta)}** via the authenticated GitHub API for every competitor."
    )


def render_landscape(meta: dict[str, Any]) -> str:
    repos = meta.get("repos")
    if not isinstance(repos, dict) or not repos:
        raise RenderError("competitor-meta.json has no `repos`")
    lines = [
        f"## Landscape snapshot (verified {fetch_date(meta)})",
        "",
        "| Tool | License | Stars | Last push | Latest release | Status |",
        "|---|---|---|---|---|---|",
    ]
    lines.extend(_row(repo, entry) for repo, entry in repos.items())
    return "\n".join(lines)


def render_readme_comparison(meta: dict[str, Any]) -> str:
    """The above-the-fold comparison, entirely from committed data.

    The README used to state the project count and the fetch date in prose --
    "14 projects ... fetched from the GitHub API on 2026-09-09" -- in the same
    paragraph that told the reader "CI fails if the two disagree". That was
    true of `docs/competitive-analysis.md` and not of the paragraph claiming
    it: a refresh run moves `fetched_utc` and would have left this sentence
    naming the old date.

    Nothing editorial goes in here. "oasdiff is the healthy incumbent" is a
    judgement and it lives in the prose below this block, where a reader can
    tell it apart from a number.
    """
    capabilities = load_capabilities()
    counted = coverage(capabilities)
    areas = capability_area_count(capabilities)
    repos = meta.get("repos") or {}
    archived = sorted(
        LABELS.get(repo, repo) for repo, entry in repos.items() if entry.get("archived")
    )

    top = counted[:6]
    lines = [
        f"**{len(repos)} competing projects are tracked**, with license, stars, last push and "
        f"latest release fetched from the GitHub API on {fetch_date(meta)} and committed to "
        "[`data/competitor-meta.json`](data/competitor-meta.json).",
        "",
        f"Across the {areas} capability areas in "
        "[`data/competitive-capabilities.json`](data/competitive-capabilities.json), the "
        "deepest specialists cover a handful each:",
        "",
        "| Tool | Capability areas covered |",
        "|---|---|",
    ]
    lines.extend(f"| {tool} | {count} of {areas} |" for tool, count in top)
    lines.extend(
        [
            "",
            "That is the shape of the market, not a scoreboard: each of those tools is "
            "excellent inside its lane, and the classification behind the numbers is this "
            "project's own -- every cell carries its evidence note in the matrix. What none "
            "of them does is put diffing, schema-driven testing, runtime drift and "
            "performance budgets behind *one* contract model and *one* result format.",
        ]
    )
    if archived:
        lines.extend(
            [
                "",
                "Archived, and worth knowing about: "
                + ", ".join(f"**{name}**" for name in archived)
                + ".",
            ]
        )
    lines.extend(
        [
            "",
            "Full analysis, with every row's evidence: "
            "[docs/competitive-analysis.md](docs/competitive-analysis.md).",
        ]
    )
    return "\n".join(lines)


#: Marker name -> (file, renderer). Each block is spliced by name into the file
#: that carries its markers.
BLOCKS: dict[str, tuple[Path, Callable[[dict[str, Any]], str]]] = {
    "provenance": (DOC, render_provenance),
    "method": (DOC, render_method),
    "landscape": (DOC, render_landscape),
    "readme-comparison": (README, render_readme_comparison),
}


def splice(text: str, meta: dict[str, Any], target: Path) -> str:
    """Replace every marked block belonging to `target` with its rendered body.

    Sliced by index rather than `re.sub`, because the rendered body is data. A
    competitor description containing a backslash -- or anything shaped like a
    replacement template -- would otherwise be reinterpreted by `sub` and
    silently corrupt the output.
    """
    for name, (owner, renderer) in BLOCKS.items():
        if owner != target:
            continue
        open_mark = MARK_OPEN.format(name=name)
        close_mark = MARK_CLOSE.format(name=name)
        start = text.find(open_mark)
        end = text.find(close_mark)
        if start == -1 or end == -1 or end < start:
            raise SystemExit(
                f"{target.name} is missing the {open_mark} / {close_mark} markers, or "
                "carries them out of order. Add them around the block before running "
                "this script."
            )
        head = text[: start + len(open_mark)]
        text = f"{head}\n{renderer(meta)}\n{text[end:]}"
    return text


def targets() -> list[Path]:
    """Every file this script writes, in a stable order."""
    seen: list[Path] = []
    for owner, _renderer in BLOCKS.values():
        if owner not in seen:
            seen.append(owner)
    return seen


def main() -> int:
    parser = argparse.ArgumentParser(description="Render the competitive landscape blocks.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the committed document matches the committed data; exit 1 if not",
    )
    parser.add_argument(
        "--max-age-days",
        type=int,
        default=None,
        metavar="N",
        help=(
            "fail when the evidence is older than N days. Off by default on purpose: "
            "blocking an unrelated pull request because a quarter rolled over punishes "
            "the wrong person. The scheduled refresh job passes it"
        ),
    )
    parser.add_argument(
        "--warn-age-days",
        type=int,
        default=DEFAULT_MAX_AGE_DAYS,
        metavar="N",
        help="print a notice when the evidence is older than N days (default: a quarter)",
    )
    args = parser.parse_args()

    meta = load_meta()
    rendered = {
        target: splice(target.read_text(encoding="utf-8"), meta, target) for target in targets()
    }
    stale = [
        target for target, body in rendered.items() if target.read_text(encoding="utf-8") != body
    ]
    count = len(meta["repos"])

    # Age is reported on every run, `--check` or not. A number nobody prints is
    # a number nobody notices, and the whole point of the dated evidence is
    # that its date is visible.
    if args.max_age_days is not None and evidence_age_days(meta) > args.max_age_days:
        print(f"error: {freshness_message(meta, args.max_age_days)}", file=sys.stderr)
        return 1
    if evidence_age_days(meta) > args.warn_age_days:
        print(f"notice: {freshness_message(meta, args.warn_age_days)}", file=sys.stderr)

    names = ", ".join(target.name for target in targets())

    if args.check:
        if not stale:
            print(
                f"ok     {names} match competitor-meta.json "
                f"({count} projects, gathered {fetch_date(meta)}, "
                f"{evidence_age_days(meta)}d old)"
            )
            return 0
        import difflib

        for target in stale:
            print(
                f"{target.name} no longer matches data/competitor-meta.json.\n"
                "Run: python scripts/generate_competitive_table.py",
                file=sys.stderr,
            )
            diff = difflib.unified_diff(
                target.read_text(encoding="utf-8").splitlines(),
                rendered[target].splitlines(),
                fromfile=f"{target.name} (committed)",
                tofile=f"{target.name} (from data)",
                lineterm="",
            )
            for line in list(diff)[:60]:
                print(line, file=sys.stderr)
        return 1

    for target, body in rendered.items():
        target.write_text(body, encoding="utf-8", newline="\n")
    print(f"wrote  {names} ({count} projects from competitor-meta.json)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
