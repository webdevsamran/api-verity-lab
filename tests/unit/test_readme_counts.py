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


def test_the_question_count_matches_the_table(spell_number) -> None:
    match = re.search(r"answers ([\w-]+) questions", README)
    assert match, "the questions claim has been reworded; update this test with it"
    rows = len(_first_table_rows("questions from one place"))
    assert match.group(1) == spell_number(rows), (
        f"README says {match.group(1)!r} questions over a table of {rows} rows; "
        f"it should say {spell_number(rows)!r}"
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


def test_the_declared_version_is_the_same_everywhere() -> None:
    """pyproject, CITATION.cff and the CHANGELOG must agree.

    ToolTrace Bench shipped with these three saying three different things --
    two of them describing a version that had never been tagged. It is a
    one-line fix each time and it happens on every release, which is what a
    test is for.
    """
    import re
    import tomllib

    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    declared = pyproject["project"]["version"]

    citation = (ROOT / "CITATION.cff").read_text(encoding="utf-8")
    match = re.search(r"^version:\s*(\S+)$", citation, re.M)
    assert match, "CITATION.cff has no version field"
    assert match.group(1).strip("'\"") == declared, (
        f"CITATION.cff says {match.group(1)}, pyproject says {declared}"
    )

    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    released = re.findall(r"^## \[(\d+\.\d+\.\d+)\]", changelog, re.M)
    assert released, "the CHANGELOG has no released version heading"
    assert released[0] == declared, (
        f"the newest CHANGELOG entry is {released[0]}, pyproject says {declared}"
    )
