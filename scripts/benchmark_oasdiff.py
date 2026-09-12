"""Run this engine and oasdiff over the same contracts, and record both answers.

A benchmark that only wins reads as marketing, and the reader who notices that
stops believing the rest of the repository. So the interesting column here is
the one where the other tool found something we did not.

Two modes, on purpose, and the split is the same one
`generate_competitive_table.py` uses:

    python scripts/benchmark_oasdiff.py --run     # needs oasdiff on PATH
    python scripts/benchmark_oasdiff.py           # renders from the evidence
    python scripts/benchmark_oasdiff.py --check   # CI: is the doc stale?

`--run` executes both tools and writes `data/benchmark-oasdiff.json`, dated and
versioned. Everything else reads that file. CI has no Go toolchain and should
not grow one to render a document, and a benchmark that silently re-ran on
every push would publish numbers nobody looked at.

## What is compared, and what that is worth

Rule ids do not align across the two vocabularies -- that is what
`docs/oasdiff-migration.md` is about -- so nothing here pretends to match
finding against finding. The comparison is at **operation** granularity: for
each contract pair, which operations did each tool flag as breaking?

That is a real question with a checkable answer, and it is still not a
correctness measure. Two tools disagreeing about an operation usually means
they model different things, and either may be right. The document says so
where somebody might otherwise read a score.
"""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import sys
from typing import Any

# `scripts/` so `page_meta` resolves, the repository root so `apiverity`
# does. Running this as a script puts the first one on the path; loading
# it by file location -- which is how the tests load it -- puts neither.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from page_meta import front_matter

NL = chr(10)
ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"
EVIDENCE = ROOT / "data" / "benchmark-oasdiff.json"
TARGET = ROOT / "docs" / "benchmark.md"

#: OpenAPI pairs only. oasdiff reads OpenAPI, and running it against a `.proto`
#: to report that it found nothing would be a rigged comparison.
PAIRS: list[tuple[str, str, str]] = [
    (
        "versioned",
        "apis/versioned/v1.yaml",
        "apis/versioned/v2.yaml",
    ),
    (
        "json-schema 2020-12",
        "apis/jsonschema2020/v1.yaml",
        "apis/jsonschema2020/v2.yaml",
    ),
    (
        "crud against drift",
        "apis/crud/openapi.yaml",
        "apis/drift/openapi.yaml",
    ),
]


def _ours(old: pathlib.Path, new: pathlib.Path) -> list[dict[str, Any]]:
    """Every finding this engine reports, at every severity.

    Filtering to ERROR was the first version of this and it produced a
    falsehood about our own tool: it showed two changes as things oasdiff found
    and this engine missed, when this engine reports both -- one at WARN and
    one at INFO. A benchmark that publishes a gap that is not there is the same
    defect as one that hides a gap that is, and it is more embarrassing.

    The severity travels with each row instead, because a difference in
    *judgement* is the interesting comparison once both tools have found the
    same change.
    """
    import contextlib
    import io

    from apiverity.cli.main import main

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(io.StringIO()):
        main(["--no-config", "breaking", str(old), str(new), "--json"])
    payload = json.loads(buffer.getvalue())
    # `COMPAT-*` is a separate family about protocol compatibility rather than
    # about the contract diff, and oasdiff has no equivalent to compare it to.
    return [f for f in payload.get("findings", []) if str(f.get("rule_id", "")).startswith("BRK-")]


def _theirs(binary: str, old: pathlib.Path, new: pathlib.Path) -> list[dict[str, Any]]:
    result = subprocess.run(
        [binary, "breaking", str(old), str(new), "-f", "json"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        timeout=120,
    )
    text = result.stdout.strip()
    if not text:
        return []
    parsed = json.loads(text)
    return parsed if isinstance(parsed, list) else []


def _operation(change: dict[str, Any]) -> str:
    """`GET /users`, from either tool's way of saying it."""
    if "operation_key" in change:
        return str(change.get("operation_key") or "")
    method = str(change.get("operation") or "")
    path = str(change.get("path") or "")
    return f"{method} {path}".strip()


#: oasdiff's numeric levels, spelled the way its own `String()` does, so the
#: two columns read in the same units. From `checker/rules/level.go`.
LEVEL_NAMES = {3: "error", 2: "warning", 1: "info", 0: "issue"}


def _level(value: Any) -> str:
    return LEVEL_NAMES.get(value, str(value))


def _cell(text: Any) -> str:
    """One finding's message, safe inside a Markdown table cell.

    A pipe in a message would split the row, and a message is the one thing
    here written by neither of these two tools with a table in mind.
    """
    return str(text or "").replace("|", "\\|").replace(chr(10), " ")


def run(binary: str, *, module_version: str) -> dict[str, Any]:
    """Execute both tools over every pair and record what each said."""
    from datetime import UTC, datetime

    from apiverity import __version__

    pairs: list[dict[str, Any]] = []
    for label, old_rel, new_rel in PAIRS:
        old, new = FIXTURES / old_rel, FIXTURES / new_rel
        if not (old.is_file() and new.is_file()):
            pairs.append({"pair": label, "unavailable": f"no fixture at {old_rel} / {new_rel}"})
            continue
        ours = _ours(old, new)
        theirs = _theirs(binary, old, new)
        pairs.append(
            {
                "pair": label,
                "old": old_rel,
                "new": new_rel,
                "ours": [
                    {
                        "rule_id": f.get("rule_id"),
                        "severity": f.get("severity"),
                        "operation": _operation(f),
                        "text": f.get("message"),
                    }
                    for f in ours
                ],
                "theirs": [
                    {
                        "id": c.get("id"),
                        "level": c.get("level"),
                        "operation": _operation(c),
                        "text": c.get("text"),
                    }
                    for c in theirs
                ],
            }
        )

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "apiverity_version": __version__,
        "oasdiff_module_version": module_version,
        # Recorded because `oasdiff --version` self-reports "main" when built
        # with `go install`, which would otherwise read as an unversioned build
        # of an unknown commit. The module version above is the one asked for.
        "oasdiff_self_reported": _self_reported(binary),
        "pairs": pairs,
        "not_run": {
            "Specmatic": (
                "needs a JVM, and this machine has none. Listed rather than left out: a "
                "benchmark naming two competitors and measuring one has said something "
                "about the second by omission"
            )
        },
    }


def _self_reported(binary: str) -> str:
    try:
        out = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=30)
        return out.stdout.strip() or out.stderr.strip()
    except OSError as exc:
        return f"could not ask: {exc}"


_HEADER = """# Benchmark against oasdiff

Both engines over the same contracts, with what each reported.

**The interesting column is the one where oasdiff found something this tool did
not.** A benchmark that only wins reads as marketing, and the reader who
notices that stops believing everything else in the repository.

## What this measures, and what it does not

Rule ids do not align across the two vocabularies -- that is what
[migrating from oasdiff](oasdiff-migration.md) is about -- so nothing here
matches finding against finding. The comparison is at **operation**
granularity: for each pair of contracts, which operations did each tool flag as
breaking?

That question has a checkable answer. It is still **not a correctness
measure**. Two tools disagreeing about an operation usually means they model
different things, and either may be right; a count is a fact about coverage,
not about being correct. Where they disagree below, the other tool's own
wording is quoted so a reader can judge rather than take a number.

Every finding from both tools is listed, at every severity, with the severity
each one assigned. An earlier version of this page compared only this tool's
`ERROR` findings against oasdiff's output and published two changes as gaps
that were not gaps -- both were reported here, one at `WARN` and one at `INFO`.
A benchmark that invents a gap is the same defect as one that hides a gap, and
more embarrassing.

Once both tools have found the same change, the interesting comparison is what
each one *called* it. `oasdiff breaking` reports only what it considers
breaking; this tool's `breaking` reports everything the diff produced, with a
severity. The two lists are deliberately *not* a two-column table: putting one
tool's n-th finding beside the other's implies they correspond, and the
vocabularies differ in granularity, so they often do not. Read them as two
accounts of the same pair of documents.

Only OpenAPI pairs are compared. oasdiff reads OpenAPI, and running it against
a `.proto` to report that it found nothing would be a rigged comparison.

"""


def render(evidence: dict[str, Any]) -> str:
    out = [front_matter("benchmark.md") + _HEADER]
    out.append("## Provenance" + NL)
    out.append(f"- Run: **{evidence['generated_at']}**")
    out.append(f"- api-verity-lab: **{evidence['apiverity_version']}**")
    out.append(
        f"- oasdiff: module **{evidence['oasdiff_module_version']}**, "
        f"self-reported `{evidence['oasdiff_self_reported']}` "
        "(`go install` builds without the version ldflag, so the binary does not know "
        "which tag it came from -- the module version is the one that was asked for)"
    )
    for tool, reason in sorted(evidence.get("not_run", {}).items()):
        out.append(f"- **{tool}**: not run -- {reason}")
    out.append("")

    total_only_theirs = 0
    total_only_ours = 0

    for pair in evidence["pairs"]:
        out.append(f"## {pair['pair']}" + NL)
        if "unavailable" in pair:
            out.append(f"_Not compared: {pair['unavailable']}._" + NL)
            continue
        out.append(f"`{pair['old']}` against `{pair['new']}`" + NL)

        ours = {c["operation"] for c in pair["ours"] if c["operation"]}
        theirs = {c["operation"] for c in pair["theirs"] if c["operation"]}
        only_theirs = sorted(theirs - ours)
        only_ours = sorted(ours - theirs)
        total_only_theirs += len(only_theirs)
        total_only_ours += len(only_ours)

        out.append("| | This tool | oasdiff |")
        out.append("|---|---|---|")
        out.append(f"| Breaking findings | {len(pair['ours'])} | {len(pair['theirs'])} |")
        out.append(f"| Operations flagged | {len(ours)} | {len(theirs)} |")
        out.append(f"| Operations both flagged | {len(ours & theirs)} | {len(ours & theirs)} |")
        out.append("")

        if only_theirs:
            out.append(
                "Operations **only oasdiff** flagged: "
                + ", ".join(f"`{operation}`" for operation in only_theirs)
                + NL
            )
        if only_ours:
            out.append(
                "Operations **only this tool** flagged: "
                + ", ".join(f"`{operation}`" for operation in only_ours)
                + NL
            )

        # Agreeing about *which operations* broke says much less than it looks
        # like: on a small contract both tools flag the same three, and the
        # difference that matters is inside them. Both lists are printed in
        # full, per operation, and the alignment is left to the reader --
        # the two vocabularies do not map, and a table pairing them up would
        # be asserting equivalences nobody established.
        out.append("### What each tool said" + NL)
        for operation in sorted(ours | theirs):
            mine = [c for c in pair["ours"] if c["operation"] == operation]
            yours = [c for c in pair["theirs"] if c["operation"] == operation]
            out.append(f"**`{operation}`** — {len(mine)} here, {len(yours)} from oasdiff" + NL)
            # Two lists, not a two-column table. Putting the n-th finding from
            # each tool on the same row implies the two correspond, and they
            # do not: the vocabularies differ in granularity, so one tool's
            # third finding may be another's first or may have no counterpart
            # at all. A table said that by accident on the first render.
            out.append("_This tool_" + NL)
            if mine:
                for change in mine:
                    out.append(
                        f"- `{change['rule_id']}` ({change.get('severity', '?')}) — "
                        f"{_cell(change['text'])}"
                    )
            else:
                out.append("- nothing")
            out.append("")
            out.append("_oasdiff_" + NL)
            if yours:
                for change in yours:
                    out.append(
                        f"- `{change['id']}` ({_level(change.get('level'))}) — "
                        f"{_cell(change['text'])}"
                    )
            else:
                out.append("- nothing")
            out.append("")

    out.append("## Reading this" + NL)
    out.append(
        f"Across every pair, oasdiff flagged **{total_only_theirs}** operation(s) this tool "
        f"did not, and this tool flagged **{total_only_ours}** oasdiff did not." + NL
    )
    out.append(
        "On contracts this size that number is usually zero and it is the least "
        "informative thing on the page: both tools flag the same handful of operations, "
        "and everything interesting is *inside* them. The per-operation lists above are "
        "where the disagreement is, and an operation whose oasdiff list is longer than "
        "this tool's is where to look first." + NL
    )
    out.append(
        "Neither count is a score. Two tools disagreeing about a change usually means "
        "they model different things, and either may be right." + NL
    )
    return NL.join(out)


def main() -> int:
    if "--run" in sys.argv:
        binary = shutil.which("oasdiff") or shutil.which("oasdiff.exe")
        if binary is None:
            gopath = subprocess.run(
                ["go", "env", "GOPATH"], capture_output=True, text=True, timeout=30
            ).stdout.strip()
            candidate = pathlib.Path(gopath) / "bin" / "oasdiff.exe"
            binary = str(candidate) if candidate.is_file() else None
        if binary is None:
            print(
                "error: oasdiff is not on PATH. Install it with\n"
                "    go install github.com/oasdiff/oasdiff@v1.31.0",
                file=sys.stderr,
            )
            return 1
        version = "v1.31.0"
        for argument in sys.argv:
            if argument.startswith("--oasdiff-version="):
                version = argument.split("=", 1)[1]
        evidence = run(binary, module_version=version)
        EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
        EVIDENCE.write_text(json.dumps(evidence, indent=2) + NL, encoding="utf-8", newline=NL)
        print(f"wrote  {EVIDENCE.relative_to(ROOT).as_posix()}")

    if not EVIDENCE.is_file():
        print(
            "error: no benchmark evidence. Run with --run (needs oasdiff) first.",
            file=sys.stderr,
        )
        return 1
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    rendered = render(evidence)
    previous = TARGET.read_text(encoding="utf-8") if TARGET.is_file() else None
    if previous == rendered:
        print(f"ok     {TARGET.name} ({len(evidence['pairs'])} pairs)")
        return 0
    if "--check" in sys.argv:
        print(
            "error: docs/benchmark.md is stale; run scripts/benchmark_oasdiff.py",
            file=sys.stderr,
        )
        return 1
    TARGET.write_text(rendered, encoding="utf-8", newline=NL)
    print(f"wrote  {TARGET.name} ({len(evidence['pairs'])} pairs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
