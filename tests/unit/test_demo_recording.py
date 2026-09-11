"""The README's headline animation, held to the same rule as its text.

A screen recording is the one artefact nobody re-checks. It ages silently — a
renamed rule id, a new column — and goes on showing the old thing to everybody
who lands on the page. This project already fixed that for the README's text
blocks; the picture is generated too, and these tests are what keep it that way.

They also pin two things about the SVG that a reading would not catch, because
both were found by putting it in a browser:

- **Nothing may depend on `animation-fill-mode`.** The first encoding gave each
  row a one-frame animation with `animation-delay` set to its reveal time and
  `forwards` to hold it. Rows past about two seconds reported
  `playState: "finished"` with a computed opacity still `0`, and the recording
  stopped three lines in.
- **`prefers-reduced-motion` shows the whole transcript.** An animated README
  image is exactly what that preference is for, and a reader who has set it
  should get the session, not a blank terminal.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "record_demo.py"
_SVG = _ROOT / "docs" / "demo.svg"
_CAST = _ROOT / "docs" / "demo.cast"


def _module() -> Any:
    """A fresh copy of the script, so a test that changes a constant on it does
    not change it for the next one."""
    spec = importlib.util.spec_from_file_location("record_demo", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Registered for the duration of the exec and no longer. `@dataclass`
    # resolves its annotations through `sys.modules[cls.__module__]`, and
    # without the entry that lookup is `None` and the decorator raises.
    sys.modules["record_demo"] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop("record_demo", None)
    return module


def test_the_committed_recording_matches_a_real_run() -> None:
    """`--check` runs in CI; failing here too is faster feedback."""
    result = subprocess.run(
        [sys.executable, str(_SCRIPT), "--check"],
        capture_output=True,
        text=True,
        cwd=_ROOT,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_every_line_in_the_svg_came_out_of_the_tool() -> None:
    """The point of generating it. A recording is only worth trusting if no
    line in it was typed by hand."""
    module = _module()
    rows, _ = module.transcript()
    produced = set()
    for scene in module.SCENES:
        for line in module.run(list(scene.argv)).rstrip("\n").split("\n"):
            produced.update(module.wrap(line, module.COLS))

    for row in rows:
        if row.kind in ("note", "prompt") or not row.text:
            continue
        assert row.text in produced, f"{row.text!r} is in the recording and in no command's output"


def test_the_animation_does_not_depend_on_fill_mode() -> None:
    """Found in a browser, not in review: rows whose animation finished while
    the tab was throttled kept a computed opacity of 0 despite
    `fill-mode: forwards`, and the recording stopped three lines in. Every row
    now runs the same infinite animation of the full duration and flips at its
    own keyframe, so there is no state to hold after it ends."""
    svg = _SVG.read_text(encoding="utf-8")
    assert "animation-iteration-count: infinite" in svg
    assert "animation-delay" not in svg
    assert "forwards" not in svg


def test_every_row_names_a_keyframe_that_exists() -> None:
    """A row pointing at a keyframe rule that was not emitted never appears,
    and an empty line in a terminal recording looks like the command hung."""
    svg = _SVG.read_text(encoding="utf-8")
    defined = set(re.findall(r"@keyframes (k\d+)", svg))
    used = set(re.findall(r"animation-name:(k\d+)", svg))
    assert used, "no row is animated at all"
    assert used <= defined, f"rows name keyframes that do not exist: {sorted(used - defined)}"


def test_reduced_motion_shows_the_whole_transcript() -> None:
    svg = _SVG.read_text(encoding="utf-8")
    block = svg[svg.index("prefers-reduced-motion") :]
    assert "opacity: 1" in block[:200]
    assert "animation: none" in block[:200]


def test_the_description_carries_the_transcript() -> None:
    """A reader who cannot see the image should get the session, not the words
    "terminal recording"."""
    svg = _SVG.read_text(encoding="utf-8")
    description = svg[svg.index("<desc>") + 6 : svg.index("</desc>")]
    assert "apiverity breaking" in description
    assert "BRK-" in description


def test_the_cast_is_a_valid_asciinema_v2_recording() -> None:
    lines = _CAST.read_text(encoding="utf-8").strip().split("\n")
    header = json.loads(lines[0])
    assert header["version"] == 2
    assert header["width"] == _module().COLS

    last = -1.0
    for line in lines[1:]:
        at, stream, _text = json.loads(line)
        assert stream == "o"
        # Monotonic: a player seeks by timestamp, and an event that goes
        # backwards is one it may never show.
        assert at >= last, f"event at {at} follows one at {last}"
        last = at


def test_the_cast_carries_no_timestamp() -> None:
    """asciinema headers usually carry `timestamp`. One here would change on
    every generation, and a file that cannot be `--check`ed is a file that
    drifts -- which is the whole thing this is guarding against."""
    header = json.loads(_CAST.read_text(encoding="utf-8").split("\n")[0])
    assert "timestamp" not in header


def test_a_transcript_that_outgrows_the_frame_fails_rather_than_truncating() -> None:
    """A recording cut off mid-finding reads as a crash. The cap is a build
    failure that names the fix, not a silent slice."""
    module = _module()
    module.MAX_ROWS = 2
    assert module.main(["--check"]) == 1


def test_output_wraps_at_the_column_the_way_a_terminal_does() -> None:
    """Not on words. A reader of the recording will run the command themselves
    and see the terminal's wrapping, not `textwrap`'s."""
    module = _module()
    assert module.wrap("abcdefghij", 4) == ["abcd", "efgh", "ij"]
    assert module.wrap("", 4) == [""]


def test_the_readme_and_the_docs_site_both_point_at_the_recording() -> None:
    """A generated artefact nothing renders is a file, not a demo."""
    assert "docs/demo.svg" in (_ROOT / "README.md").read_text(encoding="utf-8")
    assert "demo.svg" in (_ROOT / "docs" / "index.md").read_text(encoding="utf-8")


def test_ci_rechecks_the_recording() -> None:
    workflow = (_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "scripts/record_demo.py --check" in workflow
