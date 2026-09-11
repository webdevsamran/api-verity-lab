"""Every rule this tool can emit can be looked up.

`apiverity explain` exists because a rule nobody understands gets suppressed
rather than fixed. It answered *"no rule with id ..."* for about a hundred and
sixty of the ids the package emits — the parsers' findings, every MCP rule, the
runtime probes, the compatibility analysers, budgets, workflows, semver. A
reader who received one and looked it up concluded the catalogue was incomplete
rather than that the rule was, which is the same shape of defect as a README
quoting rule ids the engine cannot produce.

This is the guard that keeps it closed. It scans the package for rule-id-shaped
string literals and requires every one to resolve, so a new rule added without
an entry fails here rather than in somebody's terminal.

## The exemptions, and why each is not a rule

`apiverity/rules/summary.py` keeps a table of **prefixes** used to turn findings
into a sentence for a pull-request body — `BRK-PARAM-TYPE` matches
`BRK-PARAM-TYPE-CHANGED`. They look exactly like rule ids and are not, so they
are listed by name: a list checked entry by entry is a list somebody has to
justify adding to.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_PACKAGE = _ROOT / "apiverity"

#: Rule-id shaped: an uppercase family, then at least one hyphenated part.
_SHAPE = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+$")

#: Strings that look like rule ids and are not. Each is named, with the reason,
#: because a pattern-based exemption is where a real rule goes to hide.
NOT_RULES = {
    # `rules/summary.py` matches these as *prefixes* to phrase a finding for a
    # pull-request body. Each matches a real rule id that is longer.
    "BRK-MCP-OUTPUT-SCHEMA": "prefix of BRK-MCP-OUTPUT-SCHEMA-*",
    "BRK-MCP-TOOL-DESCRIPTION": "prefix of BRK-MCP-TOOL-DESCRIPTION-*",
    "BRK-MCP-TOOL-RENAME": "prefix of BRK-MCP-TOOL-RENAME-*",
    "BRK-MEDIA-TYPE": "prefix of BRK-MEDIA-TYPE-*",
    "BRK-PARAM-TYPE": "prefix of BRK-PARAM-TYPE-CHANGED",
    # Header and encoding names, which share the shape by coincidence.
    "UTF-8": "an encoding name",
    "CONTENT-TYPE": "a header name",
}


def _known() -> set[str]:
    from apiverity.rules.breaking import CATALOG
    from apiverity.rules.check_catalog import catalog

    return set(CATALOG) | set(catalog())


def _emitted() -> dict[str, str]:
    """`{rule id: the module it appears in}` for every literal in the package.

    Docstrings are excluded, so a rule merely *described* in prose does not
    count as emitted -- which is the case the catalogue completeness tests
    exist to catch in the other direction.
    """
    found: dict[str, str] = {}
    for path in sorted(_PACKAGE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docstrings = {
            ast.get_docstring(node, clean=False)
            for node in ast.walk(tree)
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        }
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            value = node.value
            if value in docstrings or not _SHAPE.match(value):
                continue
            found.setdefault(value, str(path.relative_to(_ROOT)))
    return found


def test_every_rule_the_package_emits_can_be_explained() -> None:
    orphans = {
        rule_id: module
        for rule_id, module in _emitted().items()
        if rule_id not in _known() and rule_id not in NOT_RULES
    }
    assert not orphans, (
        "these rule ids are emitted and `apiverity explain` cannot answer for them: "
        + "; ".join(f"{rule_id} ({module})" for rule_id, module in sorted(orphans.items()))
        + ". Add a catalogue entry, or record it in NOT_RULES with the reason it is not one."
    )


def test_the_exemption_list_has_no_entry_that_is_actually_a_rule() -> None:
    """The other direction. An exemption that names a real rule would hide it
    from the check above for as long as nobody read the list."""
    known = _known()
    wrong = sorted(rule_id for rule_id in NOT_RULES if rule_id in known)
    assert not wrong, f"these are exempted and are real rules: {wrong}"


def test_every_exempted_prefix_really_is_a_prefix() -> None:
    """The claim each exemption makes. A prefix matching no rule is a phrase
    that can never be used, which is a dead entry rather than an exemption."""
    known = _known()
    for rule_id, reason in NOT_RULES.items():
        if not reason.startswith("prefix of"):
            continue
        assert any(candidate.startswith(rule_id) for candidate in known), (
            f"{rule_id} is exempted as a prefix and matches no rule"
        )


@pytest.mark.parametrize(
    "rule_id",
    [
        "SPEC-REF-UNRESOLVED",
        "COMPAT-MEDIA-REMOVED",
        "PROTO-WIRE-TYPE-CHANGED",
        "GQL-FIELD-REMOVED",
        "DRIFT-STATUS",
        "GHOST-ROUTE",
        "MCP-POISON-INSTRUCTION",
        "MCP-AUTH-ANONYMOUS-LIST",
        "MCP-LOCK-UNSIGNED",
        "BUDGET-EXCEEDED",
        "WF-MISSING-VAR",
        "SEMVER-MAJOR-REQUIRED",
        "CONSUMER-UNKNOWN-OPERATION",
        "POLICY-RULE-CRASHED",
    ],
)
def test_explain_answers_for_one_rule_from_every_family(rule_id: str) -> None:
    """A spot check through the command rather than the catalogue, because the
    catalogue being right and `explain` not reading it is two things."""
    import contextlib
    import io
    import json

    from apiverity.cli.main import main

    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = main(["explain", rule_id, "--json"])
    assert code == 0, rule_id
    payload = json.loads(out.getvalue())
    assert payload["description"].strip()
    assert payload["instead"].strip()
    assert payload["group"] != "Other", f"{rule_id} has no group in the guide table"


# -- the guide table -------------------------------------------------------


def _guide() -> list[tuple[str, str, str]]:
    from apiverity.cli.commands.platform import _RULE_GUIDE

    return list(_RULE_GUIDE)


def test_no_guide_row_is_shadowed_by_an_earlier_one() -> None:
    """`_guide_for` takes the first prefix that matches, so a row whose prefix
    starts with an earlier row's can never be reached. Six such rows had
    accumulated -- a `DRIFT-` pointing at a page that does not document drift
    rules, among them -- and nothing would ever have shown it."""
    prefixes = [prefix for prefix, _, _ in _guide()]
    shadowed = [
        later
        for index, later in enumerate(prefixes)
        if any(later.startswith(earlier) for earlier in prefixes[:index])
    ]
    assert not shadowed, f"unreachable guide rows: {shadowed}"


def test_every_guide_row_matches_a_rule_that_exists() -> None:
    """A prefix for a family that was renamed or removed is a row nobody will
    notice is wrong, because nothing ever reaches it."""
    known = _known()
    dead = [
        prefix
        for prefix, _, _ in _guide()
        if not any(rule_id.startswith(prefix) for rule_id in known)
    ]
    assert not dead, f"guide rows matching no rule: {dead}"


def test_every_page_a_guide_row_names_exists() -> None:
    """`explain` prints this path. One that does not resolve sends a reader who
    already could not explain a finding to a page that is not there."""
    for prefix, _, where in _guide():
        page = _ROOT / where.split("#", 1)[0]
        assert page.exists(), f"{prefix} points at {where}, which does not exist"
