"""The landing pages, held to the data they claim to come from.

A docs site's per-protocol and per-competitor pages are the ones written once
and never read again by their author. They go on asserting coverage the engine
lost and comparisons that stopped being true, to readers who arrived from a
search and have no other source — which is worse than having no pages, because
a page nobody checks still gets quoted.

So they are generated, and this module is what keeps the generator honest:

* every rule a protocol page lists was **observed firing** on that protocol;
* every capability claimed for this project on a comparison page **names a
  command that exists**;
* every comparison page carries the other tool's strengths, because one that
  only enumerated their gaps would be an advertisement.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "generate_landing_pages.py"
_FOR = _ROOT / "docs" / "for"
_VS = _ROOT / "docs" / "vs"


def _generator() -> Any:
    spec = importlib.util.spec_from_file_location("generate_landing_pages", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["generate_landing_pages"] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop("generate_landing_pages", None)
    return module


def _subcommands() -> set[str]:
    from apiverity.cli.main import build_parser

    return set(build_parser()._subparsers._group_actions[0].choices)  # type: ignore[union-attr]


# -- they match the generator ---------------------------------------------


def test_every_committed_page_matches_a_fresh_run() -> None:
    """`--check` runs in CI; failing here too is faster feedback."""
    result = subprocess.run(
        [sys.executable, str(_SCRIPT), "--check"], capture_output=True, text=True, cwd=_ROOT
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_every_page_carries_the_generated_marker() -> None:
    """So a reader editing one by hand is told where it came from, and so a
    hand-written page cannot be mistaken for a generated one."""
    for path in list(_FOR.glob("*.md")) + list(_VS.glob("*.md")):
        assert "<!-- generated:landing -->" in path.read_text(encoding="utf-8"), path.name


def test_there_are_pages_at_all() -> None:
    assert list(_FOR.glob("*.md"))
    assert list(_VS.glob("*.md"))


# -- protocol pages --------------------------------------------------------


def test_every_rule_a_protocol_page_lists_was_observed_firing() -> None:
    """The claim these pages make. A hand-written list here would assert
    coverage nobody measured, which is exactly the failure `rule-parity.md`
    exists to prevent for the combined table."""
    module = _generator()
    observed = module.measured().by_protocol

    for label, spec in module.PROTOCOLS.items():
        path = _FOR / f"{module._slug(label)}.md"
        if not path.exists():
            continue
        listed = set(re.findall(r"^\| `([A-Z0-9-]+)` \|", path.read_text(encoding="utf-8"), re.M))
        assert listed, f"{path.name} lists no rules at all"
        assert listed <= set(observed.get(label, ())), (
            f"{path.name} lists rules not observed firing on {label}: "
            f"{sorted(listed - set(observed.get(label, ())))}"
        )
        assert spec["title"] in path.read_text(encoding="utf-8")


def _catalogued() -> set[str]:
    from apiverity.rules.breaking import CATALOG
    from apiverity.rules.check_catalog import catalog as check_catalog

    return set(CATALOG) | set(check_catalog())


def test_every_rule_in_a_table_has_a_catalogue_entry() -> None:
    """A rule id in a table with a blank description sends the reader to a
    catalogue that does not have it, and they conclude the catalogue is
    incomplete rather than that the rule is."""
    known = _catalogued()
    for path in _FOR.glob("*.md"):
        listed = set(re.findall(r"^\| `([A-Z0-9-]+)` \|", path.read_text(encoding="utf-8"), re.M))
        unknown = sorted(listed - known)
        assert not unknown, f"{path.name} tabulates rules the catalogue does not have: {unknown}"


def test_every_rule_observed_on_a_protocol_appears_on_its_page() -> None:
    """Either in the table or under the heading that says it is not catalogued.
    Dropping one would make the page's count disagree with the engine's, and a
    reader who receives a rule id and cannot look it up is the defect this
    project has fixed in its own README twice.

    These pages found six such rules when they were written -- `COMPAT-*` and
    `PROTO-*` -- and the catalogue entries that followed are why this now
    passes with the table alone."""
    module = _generator()
    observed = module.measured().by_protocol

    for label in module.PROTOCOLS:
        path = _FOR / f"{module._slug(label)}.md"
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for rule_id in sorted(observed.get(label, ())):
            assert f"`{rule_id}`" in text, f"{path.name} does not mention {rule_id}"


def test_each_protocol_page_names_a_command_that_exists() -> None:
    module = _generator()
    commands = _subcommands()
    for spec in module.PROTOCOLS.values():
        first = spec["command"].split()[1]
        assert first in commands, f"{spec['command']!r} names no such subcommand"


# -- comparison pages ------------------------------------------------------


def test_every_capability_claimed_for_this_project_names_a_real_command() -> None:
    """The evidence file's matrix has a column per competitor and none for this
    project. Filling that gap with an unsourced `yes` in every row is the thing
    this repository exists to not do, so each claim names a command -- and a
    named command that does not exist is a claim again."""
    module = _generator()
    commands = _subcommands()
    for capability, claim in module.OURS.items():
        if claim is None:
            continue
        parts = claim.split()
        assert parts[0] == "apiverity", f"{capability}: {claim!r} is not an apiverity command"
        assert parts[1] in commands, f"{capability}: no subcommand named {parts[1]!r}"


def test_the_capability_names_are_the_ones_in_the_evidence_file() -> None:
    """A mapping key that matches nothing renders in no table and silently
    claims nothing; one missing from the mapping renders as `no` for a
    capability this project may well have."""
    module = _generator()
    matrix = json.loads(module.CAPABILITIES.read_text(encoding="utf-8"))["capability_matrix"]
    named = {k for k in matrix if not k.startswith("_")}
    assert set(module.OURS) == named, (
        f"only in the mapping: {sorted(set(module.OURS) - named)}; "
        f"only in the evidence file: {sorted(named - set(module.OURS))}"
    )


def test_every_comparison_page_says_what_the_other_tool_is_good_at() -> None:
    """A page that only enumerated the other tool's gaps is an advertisement,
    and this project's credibility rests on claims a reader can check."""
    for path in _VS.glob("*.md"):
        text = path.read_text(encoding="utf-8")
        heading = re.search(r"^## What (.+) is good at$", text, re.M)
        assert heading, f"{path.name} does not say what the other tool is good at"
        section = text.split(heading.group(0), 1)[1].split("##", 1)[0]
        assert [line for line in section.splitlines() if line.startswith("- ")], (
            f"{path.name} has the heading and no strengths under it"
        )


def test_no_comparison_page_claims_the_other_tool_should_be_replaced() -> None:
    """The honest position, and the one the README already takes: a tool that
    owns its lane is worth using in it."""
    for path in _VS.glob("*.md"):
        assert "Nothing here argues for replacing" in path.read_text(encoding="utf-8"), path.name


def test_comparison_pages_are_dated() -> None:
    """Repository facts go stale. An undated star count is a number a reader
    has no way to weigh."""
    fetched = str(
        json.loads((_ROOT / "data" / "competitor-meta.json").read_text(encoding="utf-8"))[
            "fetched_utc"
        ]
    ).split("T")[0]
    for path in _VS.glob("*.md"):
        assert fetched in path.read_text(encoding="utf-8"), path.name


def test_a_tool_with_nothing_in_common_gets_no_page() -> None:
    """Fourteen pages comparing a contract governance engine with unrelated
    tools is how a docs site becomes noise. Hoverfly does none of the shared
    lanes, so it has no page -- which is measured from the matrix, not a
    judgement typed here."""
    module = _generator()
    matrix = json.loads(module.CAPABILITIES.read_text(encoding="utf-8"))["capability_matrix"]
    for name in ("Hoverfly",):
        shared = [
            lane for lane in module.SHARED_LANES if module._has(str(matrix[lane].get(name, "no")))
        ]
        assert not shared, f"{name} shares {shared} and should now have a page"
        assert not (_VS / f"{module._slug(name)}.md").exists()


# -- they are reachable ----------------------------------------------------


@pytest.mark.parametrize("directory", ["for", "vs"])
def test_every_page_is_in_the_navigation(directory: str) -> None:
    """A generated page nothing links to is a file, not a page."""
    nav = (_ROOT / "mkdocs.yml").read_text(encoding="utf-8")
    for path in (_ROOT / "docs" / directory).glob("*.md"):
        assert f"{directory}/{path.name}" in nav, f"{directory}/{path.name} is not in the nav"


def test_ci_rechecks_them() -> None:
    workflow = (_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "generate_landing_pages.py --check" in workflow
