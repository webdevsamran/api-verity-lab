"""README counts must be derived from the thing they count.

Every count-style claim in these docs had drifted at some point -- "ten
questions" over a twelve-row table, "~30 rules" over a catalog of 37. They are
each a one-line fix and each individually trivial; collectively they are the
reason a reader stops trusting the document. A number in prose that restates
something checkable belongs in a test.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
README = (ROOT / "README.md").read_text(encoding="utf-8")

_WORDS = {
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
}


def _first_table_rows(after: str) -> list[str]:
    """The rows of the first markdown table following `after`."""
    body = README[README.index(after) :]
    rows: list[str] = []
    started = False
    for line in body.splitlines():
        if line.startswith("|---"):
            started = True
            continue
        if started:
            if not line.startswith("|"):
                break
            rows.append(line)
    return rows


def test_the_question_count_matches_the_table() -> None:
    match = re.search(r"answers (\w+) questions", README)
    assert match, "the questions claim has been reworded; update this test with it"
    claimed = _WORDS.get(match.group(1))
    assert claimed is not None, f"unhandled number word {match.group(1)!r}"
    assert claimed == len(_first_table_rows("questions from one place")), (
        f"README claims {match.group(1)} questions but the table has "
        f"{len(_first_table_rows('questions from one place'))} rows"
    )


def test_the_rule_count_matches_the_catalog() -> None:
    from apiverity.rules.breaking import CATALOG

    match = re.search(r"catalog ships (\d+) rules", README)
    assert match, "the rule-count claim has been reworded; update this test with it"
    assert int(match.group(1)) == len(CATALOG), (
        f"README claims {match.group(1)} rules, CATALOG has {len(CATALOG)}"
    )


def test_every_command_named_in_the_table_exists() -> None:
    """A table row is a promise that the command runs."""
    from apiverity.cli.main import build_parser

    parser = build_parser()
    known = set()
    for action in parser._subparsers._group_actions if parser._subparsers else []:
        known.update(getattr(action, "choices", {}) or {})
    assert known, "could not enumerate subcommands; the parser shape changed"

    named = set(re.findall(r"`apiverity (\w[\w-]*)", README))
    unknown = sorted(named - known - {"lab"})
    assert not unknown, f"README names commands that do not exist: {unknown}"
