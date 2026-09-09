"""Page counts in prose must match the router.

ROADMAP.md said the frontend has "all 15 pages" and listed fifteen names.
docs/capability-status.md, written later, said "31-page product UI".
`web/src/pages/index.tsx` defines 30 routes. Three numbers, no two alike, and
nothing checked any of them -- in a repository whose stated rule is that counts
are derived from the source rather than from prose that was true once.

The rule count and the command count are already pinned this way in
`test_readme_counts.py`. This closes the same gap for the frontend.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_ROUTER = _ROOT / "web" / "src" / "pages" / "index.tsx"


def _route_ids() -> set[str]:
    source = _ROUTER.read_text(encoding="utf-8")
    table = source[source.index("ROUTE_TABLE") :]
    return set(re.findall(r"^\s+(\w+): \[", table, re.M))


def _nav_ids() -> set[str]:
    source = _ROUTER.read_text(encoding="utf-8")
    nav = source[source.index("export const NAV") : source.index("export const CHUNKS")]
    return set(re.findall(r"\['([a-z]+)', '", nav))


def test_every_nav_entry_has_a_route_and_vice_versa() -> None:
    """A nav link with no route is a dead end; a route with no link is unreachable."""
    only_nav = _nav_ids() - _route_ids()
    only_routes = _route_ids() - _nav_ids()
    assert not only_nav, f"nav entries with no route: {sorted(only_nav)}"
    assert not only_routes, f"routes reachable from no nav link: {sorted(only_routes)}"


@pytest.mark.parametrize(
    "document",
    ["ROADMAP.md", "docs/capability-status.md"],
)
def test_documented_page_counts_match_the_router(document: str) -> None:
    count = len(_route_ids())
    text = (_ROOT / document).read_text(encoding="utf-8")
    claimed = re.findall(r"(\d+)[- ](?:page|route)", text)
    wrong = [n for n in claimed if int(n) != count]
    assert not wrong, (
        f"{document} claims {wrong} page/route(s); web/src/pages/index.tsx defines {count}. "
        "Update the prose -- the router is the source of truth."
    )
