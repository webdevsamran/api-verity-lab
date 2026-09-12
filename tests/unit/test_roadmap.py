"""The roadmap, and the audit that stops it being a wish list.

A roadmap is the easiest document in a repository to be wrong. Items get ticked
from memory, a refactor renames the command a row describes, and the table goes
on saying "done" about a capability that left — to a reader who has no other
source. This project does not accept that for its rule catalogue, its
competitive table or its README counts, and a roadmap is a claim like any other.

So `scripts/check_roadmap.py` gives every item **evidence**: a predicate that is
true only while the thing exists. This module checks the auditor itself, which
is the part nothing else would catch — an evidence string nobody can satisfy, a
predicate kind that silently passes, an item counted twice.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "check_roadmap.py"
_STATUS = _ROOT / "docs" / "roadmap-status.md"

#: The plan this repository was built from. A count that drifts from it means
#: an item was added or dropped without anybody deciding to.
PLANNED_TOTAL = 134

#: Per section, from the plan's own table.
PLANNED_PER_SECTION = {
    "A · Agent & MCP governance": 20,
    "B · Specification coverage": 12,
    "C · Rules, governance & policy": 12,
    "D · Runtime, drift & observability": 14,
    "E · Security & compliance": 16,
    "F · Developer experience": 16,
    "G · Team & enterprise": 12,
    "H · The dashboard": 18,
    "I · Distribution & ranking": 14,
}


def _module() -> Any:
    spec = importlib.util.spec_from_file_location("check_roadmap", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_roadmap"] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop("check_roadmap", None)
    return module


# -- the audit passes -----------------------------------------------------


def test_every_item_that_claims_to_exist_has_evidence_that_holds() -> None:
    """The point of the whole file. `--check` fails naming each item whose
    evidence stopped being true."""
    result = subprocess.run(
        [sys.executable, str(_SCRIPT), "--check"], capture_output=True, text=True, cwd=_ROOT
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_status_page_is_not_stale() -> None:
    module = _module()
    assert _STATUS.exists()
    assert module.MARK_OPEN in _STATUS.read_text(encoding="utf-8")


# -- the table is the plan -------------------------------------------------


def test_the_item_count_is_the_plan_it_came_from() -> None:
    module = _module()
    total = sum(len(items) for items in module.SECTIONS.values())
    assert total == PLANNED_TOTAL, f"the roadmap has {total} items; the plan had {PLANNED_TOTAL}"


@pytest.mark.parametrize(("section", "count"), sorted(PLANNED_PER_SECTION.items()))
def test_each_section_has_the_items_the_plan_gave_it(section: str, count: int) -> None:
    """A total that is right while two sections are wrong in opposite
    directions is the failure a single count cannot see."""
    module = _module()
    assert section in module.SECTIONS, f"no section named {section!r}"
    assert len(module.SECTIONS[section]) == count


def test_no_id_appears_twice() -> None:
    module = _module()
    ids = [item.id for items in module.SECTIONS.values() for item in items]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    assert not duplicates, f"duplicated ids: {duplicates}"


def test_every_id_matches_its_section_prefix() -> None:
    """`AGENT-` items in section A, `SPEC-` in B, and so on. An item filed in
    the wrong section is one nobody looking for it will find."""
    module = _module()
    prefixes = {
        "A · Agent & MCP governance": "AGENT-",
        "B · Specification coverage": "SPEC-",
        "C · Rules, governance & policy": "RULE-",
        "D · Runtime, drift & observability": "RUN-",
        "E · Security & compliance": "SEC-",
        "F · Developer experience": "DX-",
        "G · Team & enterprise": "TEAM-",
        "H · The dashboard": "DASH-",
        "I · Distribution & ranking": "DIST-",
    }
    for section, items in module.SECTIONS.items():
        prefix = prefixes[section]
        wrong = [i.id for i in items if not i.id.startswith(prefix)]
        assert not wrong, f"{section} contains {wrong}"


# -- the auditor cannot pass vacuously ------------------------------------


def test_every_item_carries_either_evidence_or_an_owner() -> None:
    """An item with neither would pass silently -- the empty predicate list is
    trivially satisfied -- which is exactly the hole this file exists to close."""
    module = _module()
    for items in module.SECTIONS.values():
        for item in items:
            assert item.evidence or item.owner, f"{item.id} claims nothing and proves nothing"


def test_no_item_carries_both() -> None:
    """`owner` means the work is not this repository's to finish. Evidence
    means it is done here. Both at once is a row nobody can read."""
    module = _module()
    for items in module.SECTIONS.values():
        for item in items:
            assert not (item.evidence and item.owner), f"{item.id} is both done and blocked"


def test_every_evidence_kind_is_one_the_checker_implements() -> None:
    """An unknown kind raises rather than passing, and this catches it at the
    table rather than at whichever run first reaches that row."""
    module = _module()
    for items in module.SECTIONS.values():
        for item in items:
            for predicate in item.evidence:
                module.holds(predicate)  # raises ValueError on an unknown kind


def test_a_predicate_that_cannot_hold_is_reported_as_false() -> None:
    """The negative case for each kind. A checker that returned True for a
    missing file would pass the whole roadmap."""
    module = _module()
    for predicate in (
        "cmd:not-a-command",
        "flag:breaking:--not-a-flag",
        "mod:apiverity.nothing_here",
        "attr:apiverity.core.model:NotAName",
        "file:no/such/file.txt",
        "web:src/nothing.ts",
        "rule:NOT-A-RULE-",
        "protocol:cobol",
        "ci:nothing-runs-this",
        "grep:README.md:a string the readme does not contain anywhere at all",
    ):
        assert module.holds(predicate)[0] is False, predicate


def test_an_unknown_evidence_kind_raises_rather_than_passing() -> None:
    module = _module()
    with pytest.raises(ValueError, match="unknown evidence kind"):
        module.holds("vibes:it seems fine")


def test_owner_blocked_items_say_what_is_prepared() -> None:
    """ "Blocked" with no explanation is indistinguishable from abandoned."""
    module = _module()
    blocked = [i for items in module.SECTIONS.values() for i in items if i.owner]
    assert blocked, "nothing is blocked, so the wording of this category is untested"
    for item in blocked:
        assert len(item.owner) > 60, f"{item.id}'s reason is too short to be a reason"


# -- the page says what the audit found -----------------------------------


def test_the_page_reports_the_same_numbers_the_audit_did() -> None:
    module = _module()
    _, shipped, blocked = module.audit()
    text = _STATUS.read_text(encoding="utf-8")
    headline = re.search(r"\*\*(\d+) of (\d+) implemented\.\*\*", text)
    assert headline, "the page has no headline count"
    assert int(headline.group(1)) == len(shipped)
    assert int(headline.group(2)) == len(shipped) + len(blocked)


def test_the_page_names_every_item() -> None:
    """A generated page that quietly dropped a row would be a roadmap with a
    hole in it, which is the thing being guarded against."""
    module = _module()
    text = _STATUS.read_text(encoding="utf-8")
    for items in module.SECTIONS.values():
        for item in items:
            assert f"`{item.id}`" in text or f"**{item.id}**" in text, item.id


def test_ci_runs_the_audit() -> None:
    workflow = (_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "check_roadmap.py --check" in workflow
