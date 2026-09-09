"""Contrast is a number, so it can be a test.

`--faint` shipped at #8c959f on white: 3.04:1, which fails WCAG AA for normal
text. It is what the 11px sidebar group labels, the chart axis ticks and the
command palette's group names are drawn in -- none of which qualify as "large
text" under the rule (18.7px bold, or 24px), so none of them were covered by
the 3:1 floor it did clear. It looked fine on a bright monitor, which is
exactly why it belongs in CI rather than in a review.

This lives in the Python suite rather than beside the stylesheet because
Vitest stubs CSS imports: `import css from './styles.css?raw'` returns an
empty string there, so a JS version of this check measured nothing and passed.
A test that cannot fail is worse than no test, and `tests/unit/` already reads
`web/src/` for `test_frontend_page_count.py`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_CSS = (_ROOT / "web" / "src" / "styles.css").read_text(encoding="utf-8")

#: Text colours drawn on --bg or --panel at normal size.
_TEXT_TOKENS = ("fg", "muted", "faint", "accent", "error", "warn", "success", "info")

_AA_NORMAL = 4.5


def _luminance(hex_colour: str) -> float:
    """Relative luminance, per WCAG 2.x."""
    value = hex_colour.strip().lstrip("#")
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    channels = []
    for i in (0, 2, 4):
        c = int(value[i : i + 2], 16) / 255
        channels.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    red, green, blue = channels
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _contrast(a: str, b: str) -> float:
    high, low = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def _tokens(selector: str) -> dict[str, str]:
    """Colour tokens declared in one block of styles.css."""
    start = _CSS.index(selector)
    open_brace = _CSS.index("{", start)
    end = _CSS.index("\n}", open_brace)
    block = _CSS[open_brace:end]
    return dict(re.findall(r"--([a-z0-9-]+):\s*(#[0-9a-fA-F]{3,8})\s*;", block))


#: ":root {" is the light theme. ":root[data-theme='dark'] {" is the explicit
#: dark one, carrying the same values as the prefers-color-scheme block.
_THEMES = {
    "light": _tokens("\n:root {"),
    "dark": _tokens("\n:root[data-theme='dark'] {"),
}


@pytest.mark.parametrize("theme", sorted(_THEMES))
def test_the_parser_actually_found_the_tokens(theme: str) -> None:
    """Without this, every assertion below compares None to None and passes."""
    found = _THEMES[theme]
    missing = [t for t in (*_TEXT_TOKENS, "bg", "panel") if t not in found]
    assert not missing, f"{theme}: styles.css block is missing {missing}"


@pytest.mark.parametrize("theme", sorted(_THEMES))
@pytest.mark.parametrize("token", _TEXT_TOKENS)
def test_text_tokens_meet_wcag_aa_on_the_page_background(theme: str, token: str) -> None:
    colours = _THEMES[theme]
    ratio = _contrast(colours[token], colours["bg"])
    assert ratio >= _AA_NORMAL, (
        f"{theme}: --{token} ({colours[token]}) on --bg ({colours['bg']}) is "
        f"{ratio:.2f}:1, below the {_AA_NORMAL}:1 WCAG AA floor for normal text"
    )


@pytest.mark.parametrize("theme", sorted(_THEMES))
@pytest.mark.parametrize("token", ("fg", "muted", "faint"))
def test_text_tokens_meet_wcag_aa_on_panels(theme: str, token: str) -> None:
    """Cards, table hovers and code spans all sit on --panel, not --bg."""
    colours = _THEMES[theme]
    ratio = _contrast(colours[token], colours["panel"])
    assert ratio >= _AA_NORMAL, (
        f"{theme}: --{token} ({colours[token]}) on --panel ({colours['panel']}) is "
        f"{ratio:.2f}:1, below the {_AA_NORMAL}:1 WCAG AA floor"
    )


def test_reduced_motion_reset_comes_after_the_animations_it_disables() -> None:
    """The stylesheet defines real animations now, so the reset has to win."""
    reset = _CSS.rindex("@media (prefers-reduced-motion: reduce)")
    last_keyframes = _CSS.rindex("@keyframes")
    assert reset > last_keyframes, (
        "the prefers-reduced-motion reset must be the last motion rule in the file"
    )


def test_the_stylesheet_defines_the_motion_it_claims_to_disable() -> None:
    """The previous stylesheet had the reset and not one animation to reset."""
    assert _CSS.count("@keyframes") >= 5, (
        "prefers-reduced-motion is being honoured for animations that do not exist"
    )
