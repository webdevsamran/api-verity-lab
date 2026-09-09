"""A wide table must scroll; the page must not.

Measured in a browser at 375px before this rule existed: the Audit Log page
made the document 400px wide and Runs/Jobs made it 464px, so the whole app --
header, navigation, everything -- slid sideways under the reader's thumb.

The more useful half of the finding is that `.table-wrap`, a class whose only
job is `overflow-x: auto`, has been in the stylesheet since the first version
and no page ever used it. The mechanism was there and unused, which is why the
defect stayed invisible: nothing was broken in the code, something was simply
never called.

A layout assertion needs a layout engine and jsdom has none, so this checks
the rule rather than the rendering. The rendering was verified in a browser.
"""

from __future__ import annotations

import re
from pathlib import Path

_CSS = Path(__file__).resolve().parents[2] / "web" / "src" / "styles.css"


def _blocks() -> dict[str, str]:
    """Media-query blocks, keyed by their condition."""
    source = _CSS.read_text(encoding="utf-8")
    out: dict[str, str] = {}
    for match in re.finditer(r"@media ([^{]+)\{", source):
        start = match.end()
        depth = 1
        index = start
        while index < len(source) and depth:
            if source[index] == "{":
                depth += 1
            elif source[index] == "}":
                depth -= 1
            index += 1
        out[match.group(1).strip()] = source[start : index - 1]
    return out


def _narrow_block() -> str:
    blocks = _blocks()
    key = next((k for k in blocks if "max-width: 900px" in k), None)
    assert key, f"no narrow-viewport breakpoint in styles.css; found {sorted(blocks)}"
    return blocks[key]


def test_a_table_scrolls_itself_on_a_narrow_viewport() -> None:
    rule = re.search(r"main table\s*\{([^}]*)\}", _narrow_block())
    assert rule, "no rule makes a table scrollable at narrow widths"
    body = rule.group(1)
    assert "overflow-x: auto" in body, body
    assert "max-width: 100%" in body, body


def test_the_explicit_wrapper_still_exists_for_use_at_any_width() -> None:
    """`.table-wrap` is the version without the display:block trade."""
    source = _CSS.read_text(encoding="utf-8")
    rule = re.search(r"\.table-wrap\s*\{([^}]*)\}", source)
    assert rule and "overflow-x: auto" in rule.group(1)


def test_the_pages_that_ship_the_widest_tables_use_the_wrapper() -> None:
    """The agent pages set the example the rest of the app should follow."""
    page = (_CSS.parent / "pages" / "agents.tsx").read_text(encoding="utf-8")
    assert page.count("table-wrap") == page.count("<table>"), (
        "every table on this page should be wrapped; the media query is the "
        "safety net, not the intended form"
    )
