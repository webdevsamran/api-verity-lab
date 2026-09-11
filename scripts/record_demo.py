"""Record the README's terminal demo from real runs.

A project's headline animation is usually a screen recording, which means it is
a picture of whatever the tool printed on the author's machine on one afternoon.
It ages silently: rule ids get renamed, output gets a column, and the animation
goes on showing the old thing to everybody who lands on the page.

This project already fixed that for the README's text blocks
(`scripts/capture_readme_examples.py`). The same rule applies to the picture, so
the picture is generated: the commands below are run through `apiverity.cli.main`
in this process, stdout is captured verbatim, and both artefacts are rendered
from it.

    python scripts/record_demo.py            # rewrite docs/demo.svg and docs/demo.cast
    python scripts/record_demo.py --check    # verify, exit 1 on drift

Two outputs, because they answer to different places:

* **`docs/demo.svg`** is what the README embeds. An animated SVG needs no
  player, no third-party host and no JavaScript -- GitHub renders it inline, and
  an air-gapped clone still has it.
* **`docs/demo.cast`** is the asciinema v2 recording of the same session, for
  anyone who wants to upload, replay or pipe it somewhere.

Everything runs against `fixtures/`, in process, so this needs no network, no
installed console script and no terminal.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SVG_PATH = ROOT / "docs" / "demo.svg"
CAST_PATH = ROOT / "docs" / "demo.cast"

sys.path.insert(0, str(ROOT))

#: Terminal geometry. `COLS` is where output wraps, exactly as a real terminal
#: wraps it -- a recording that let a 200-character line run off the side would
#: be showing something no reader has ever seen.
COLS = 104

#: A transcript taller than this is not a demo, it is a log. The script fails
#: rather than truncating: a silently cut-off recording ends mid-finding and
#: reads as a crash.
MAX_ROWS = 46

#: Seconds. The command "types", then its output arrives a line at a time.
TYPE_SECONDS = 0.035
LINE_SECONDS = 0.09
PAUSE_AFTER_COMMAND = 0.45
PAUSE_BETWEEN_SCENES = 1.1
#: Held at the end so the last finding is readable before the loop restarts.
TAIL_SECONDS = 4.0

PROMPT = "$ "


@dataclass(frozen=True)
class Scene:
    """One command and the reason it is in the demo."""

    argv: tuple[str, ...]
    #: Shown as a comment line above the command. The demo has about fifteen
    #: seconds to say what the tool is for, and raw commands do not.
    note: str


SCENES = (
    Scene(argv=("--version",), note="One binary. No account, no service, no telemetry."),
    Scene(
        # An MCP tool manifest, through the same command an OpenAPI document
        # goes through. That is the claim the whole project rests on, and it is
        # the one thing a recording can show and a paragraph cannot.
        argv=("breaking", "fixtures/mcp/tools_v1.json", "fixtures/mcp/tools_v2.json"),
        note="An agent's tool manifest, through the engine OpenAPI goes through",
    ),
)


def run(argv: list[str]) -> str:
    """Run a command in this process and return exactly what it printed."""
    from apiverity.cli.main import main

    buffer = io.StringIO()
    try:
        with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
            main(argv)
    except SystemExit:
        # `--help` and usage errors leave this way. The output is still the
        # output, and swallowing the exit keeps one scene from ending the run.
        pass
    return buffer.getvalue()


def wrap(line: str, cols: int) -> list[str]:
    """Hard-wrap at the terminal width, the way a terminal does it.

    Not `textwrap`: that breaks on words and would show a layout no terminal
    produces. A terminal wraps at the column, mid-word, and that is what a
    reader of the recording will see when they run the command themselves.
    """
    if not line:
        return [""]
    return [line[i : i + cols] for i in range(0, len(line), cols)]


@dataclass(frozen=True)
class Row:
    """One displayed line, with when it appears and how to colour it."""

    text: str
    at: float
    kind: str  # prompt | note | output | error | warn | info


def _kind(line: str) -> str:
    stripped = line.lstrip()
    if stripped.startswith("[ERROR]"):
        return "error"
    if stripped.startswith("[WARN]"):
        return "warn"
    if stripped.startswith("[INFO]"):
        return "info"
    return "output"


def transcript(scenes: tuple[Scene, ...] = SCENES) -> tuple[list[Row], float]:
    """Every row of the session, with the time it appears."""
    rows: list[Row] = []
    clock = 0.4
    for index, scene in enumerate(scenes):
        if index:
            clock += PAUSE_BETWEEN_SCENES
            rows.append(Row("", clock, "output"))
        rows.append(Row(f"# {scene.note}", clock, "note"))
        clock += 0.35

        command = "apiverity " + " ".join(scene.argv)
        # The command appears character by character, which is the one thing a
        # still image cannot do and the reason to animate at all.
        rows.append(Row(PROMPT + command, clock, "prompt"))
        clock += len(command) * TYPE_SECONDS + PAUSE_AFTER_COMMAND

        for line in run(list(scene.argv)).rstrip("\n").split("\n"):
            for piece in wrap(line, COLS):
                rows.append(Row(piece, clock, _kind(line)))
                clock += LINE_SECONDS
    return rows, clock + TAIL_SECONDS


# -- asciinema -----------------------------------------------------------


def render_cast(rows: list[Row], total: float) -> str:
    """asciinema v2: a header line, then `[time, "o", text]` events."""
    header = {
        "version": 2,
        "width": COLS,
        "height": min(len(rows) + 2, MAX_ROWS),
        # No timestamp. A recording that changes every time it is generated
        # cannot be `--check`ed, and the check is the whole point.
        "env": {"SHELL": "/bin/sh", "TERM": "xterm-256color"},
        "title": "api-verity-lab",
    }
    lines = [json.dumps(header, sort_keys=True)]
    for row in rows:
        lines.append(json.dumps([round(row.at, 3), "o", row.text + "\r\n"]))
    lines.append(json.dumps([round(total, 3), "o", ""]))
    return "\n".join(lines) + "\n"


# -- SVG -----------------------------------------------------------------

#: A terminal palette, fixed rather than theme-aware. The image sits in a README
#: rendered in whichever theme the reader chose, and a terminal that is dark in
#: both is the one thing that looks deliberate in both.
COLOURS = {
    "bg": "#12161d",
    "chrome": "#1b212b",
    "border": "#2b3441",
    "output": "#c8d1dc",
    "note": "#6b7787",
    "prompt": "#7ee2a8",
    "error": "#ff7b72",
    "warn": "#e3b341",
    "info": "#79c0ff",
}

CELL_W = 8.42  # 0.6em at 14px, the advance width of a monospace glyph
LINE_H = 20.0
PAD_X = 18.0
PAD_TOP = 44.0  # room for the title bar
PAD_BOTTOM = 16.0
FONT = (
    "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, "
    "'DejaVu Sans Mono', 'Liberation Mono', monospace"
)


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def render_svg(rows: list[Row], total: float) -> str:
    """An animated SVG that loops, with one keyframe rule per reveal time.

    The obvious encoding -- a one-frame animation per row, `animation-delay`
    set to its reveal time, `fill-mode: forwards` to hold it -- does not
    survive contact with a browser. Rows past a couple of seconds reported
    `playState: "finished"` with a computed opacity still `0`: the fill was
    not applied to an animation that completed while the tab was throttled, and
    the recording stopped three lines in.

    So nothing depends on fill. Every row runs the *same* infinite animation of
    the full duration, and its own keyframes flip opacity at its moment. There
    is no state to hold after the animation ends, because it does not end --
    which also means a reader arriving mid-loop sees it from the top rather
    than a finished screen.
    """
    width = round(COLS * CELL_W + 2 * PAD_X, 1)
    height = round(len(rows) * LINE_H + PAD_TOP + PAD_BOTTOM, 1)
    command = " ".join(r.text[len(PROMPT) :] for r in rows if r.kind == "prompt")

    # One rule per distinct reveal time; rows that appear together share it.
    moments = sorted({row.at for row in rows if row.text})
    names = {at: f"k{index}" for index, at in enumerate(moments)}
    keyframes = []
    for at in moments:
        # Two adjacent stops are an instant flip. A percentage rather than a
        # delay, because the animation is one long loop rather than a
        # per-row one-shot.
        point = max(0.0, min(100.0, at / total * 100.0))
        before = max(0.0, point - 0.05)
        keyframes.append(
            f"  @keyframes {names[at]} {{ 0%,{before:.3f}% {{ opacity:0 }} "
            f"{point:.3f}%,100% {{ opacity:1 }} }}"
        )

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="{FONT}" font-size="14" '
        f'role="img" aria-label="A terminal running: {_escape(command)}">',
        "<style>",
        f"  .r {{ opacity: 0; animation-duration: {total:.2f}s; "
        "animation-timing-function: linear; animation-iteration-count: infinite; }",
        *keyframes,
        # The project respects this preference everywhere else, and an animated
        # README image is exactly the kind of thing it exists for. The whole
        # transcript is shown at once instead.
        "  @media (prefers-reduced-motion: reduce) {",
        "    .r { opacity: 1; animation: none }",
        "  }",
        "</style>",
        f'<rect width="{width}" height="{height}" rx="10" fill="{COLOURS["bg"]}" '
        f'stroke="{COLOURS["border"]}"/>',
        f'<rect width="{width}" height="30" rx="10" fill="{COLOURS["chrome"]}"/>',
        f'<rect y="20" width="{width}" height="10" fill="{COLOURS["chrome"]}"/>',
    ]
    for index, colour in enumerate(("#ff5f57", "#febc2e", "#28c840")):
        parts.append(f'<circle cx="{18 + index * 18}" cy="15" r="5.5" fill="{colour}"/>')
    parts.append(
        f'<text x="{width / 2}" y="19.5" text-anchor="middle" font-size="11.5" '
        f'fill="{COLOURS["note"]}">api-verity-lab</text>'
    )

    for index, row in enumerate(rows):
        if not row.text:
            continue
        y = round(PAD_TOP + index * LINE_H, 1)
        fill = COLOURS.get(row.kind, COLOURS["output"])
        weight = ' font-weight="600"' if row.kind == "prompt" else ""
        parts.append(
            f'<text class="r" style="animation-name:{names[row.at]}" x="{PAD_X}" y="{y}" '
            f'fill="{fill}"{weight} xml:space="preserve">{_escape(row.text)}</text>'
        )

    # The alt text is the transcript, so a reader who cannot see the image is
    # not told "terminal recording" and left there.
    parts.append("<desc>" + _escape("\n".join(row.text for row in rows if row.text)) + "</desc>")
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


# -- entry point ---------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify instead of rewriting")
    args = parser.parse_args(argv)

    rows, total = transcript()
    if len(rows) > MAX_ROWS:
        print(
            f"error: the demo is {len(rows)} rows and the cap is {MAX_ROWS}. Shorten a scene "
            "rather than raising this -- a recording that ends mid-finding reads as a crash",
            file=sys.stderr,
        )
        return 1

    svg = render_svg(rows, total)
    cast = render_cast(rows, total)

    if args.check:
        for path, rendered in ((SVG_PATH, svg), (CAST_PATH, cast)):
            if not path.exists():
                print(f"error: {path.name} is missing; run scripts/record_demo.py", file=sys.stderr)
                return 1
            if path.read_text(encoding="utf-8") != rendered:
                print(
                    f"error: {path.name} no longer matches a real run. Run "
                    "`python scripts/record_demo.py`",
                    file=sys.stderr,
                )
                return 1
        print(f"ok     demo.svg, demo.cast match a real run ({len(rows)} rows, {total:.1f}s)")
        return 0

    SVG_PATH.write_text(svg, encoding="utf-8", newline="\n")
    CAST_PATH.write_text(cast, encoding="utf-8", newline="\n")
    print(f"wrote  demo.svg, demo.cast ({len(rows)} rows, {total:.1f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
