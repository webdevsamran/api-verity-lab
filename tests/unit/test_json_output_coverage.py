"""Every command a script might parse must be able to emit JSON.

`--json` was missing from four commands, which made them unscriptable: a CI
step wanting the changelog had to parse markdown, and one wanting the mock's
address had to scrape a log line.

The interesting part is that "add the flag everywhere" would have been wrong.
`report` already has `--format json`, which is strictly more expressive
(it also renders sarif, junit, html and yaml), so a second spelling would be a
redundant flag rather than a fixed gap. And `mock` and `serve` block forever,
so a `--json` that printed only on shutdown would be a flag that does nothing —
they emit the bound address *before* serving, because "which port did it pick"
is the question a script actually has.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
from pathlib import Path
from typing import Any

import pytest

from apiverity.cli.main import build_parser

_ROOT = Path(__file__).resolve().parents[2]

#: Commands with a better-than-`--json` structured output, and why.
_DELIBERATE_EXCLUSIONS = {
    "report": "has --format json|sarif|junit|html|yaml, which is strictly more expressive",
}

#: Commands that emit no artifact of their own, because they run another
#: command and that command's `--json` is the one a caller wants.
#:
#: A separate list from the one above, and checked differently. Parking `watch`
#: beside `report` would mean asserting it has `--format`, which it does not
#: and should not -- and an exclusion list whose entries are not each checked
#: for their *own* reason is a place oversights go to sleep.
_WRAPPERS = {
    "watch": "runs another apiverity command; pass --json to that command",
}


def _subcommands() -> dict[str, argparse.ArgumentParser]:
    parser = build_parser()
    return dict(parser._subparsers._group_actions[0].choices)  # type: ignore[union-attr]


def _flags(sub: argparse.ArgumentParser) -> set[str]:
    return {option for action in sub._actions for option in action.option_strings}


def test_every_command_can_emit_structured_output() -> None:
    without = {
        name
        for name, sub in _subcommands().items()
        if "--json" not in _flags(sub)
        and name not in _DELIBERATE_EXCLUSIONS
        and name not in _WRAPPERS
    }
    assert not without, (
        f"commands with no structured output: {sorted(without)}. Either add --json or "
        "record the command in _DELIBERATE_EXCLUSIONS with the reason."
    )


@pytest.mark.parametrize("name", sorted(_DELIBERATE_EXCLUSIONS))
def test_an_excluded_command_really_does_have_something_better(name: str) -> None:
    """The exclusion list must not become a place to park an oversight."""
    sub = _subcommands()[name]
    assert "--format" in _flags(sub), (
        f"{name} is excluded from --json on the grounds that it has --format, and it does not"
    )


@pytest.mark.parametrize("name", sorted(_WRAPPERS))
def test_a_wrapper_forwards_the_command_it_wraps(name: str) -> None:
    """The exclusion holds only if `--json` actually reaches the inner command.

    `nargs=REMAINDER` is what makes `apiverity watch -- validate spec --json`
    hand `--json` to `validate` rather than consuming it here. Without it the
    exclusion would be an excuse rather than a design.
    """
    sub = _subcommands()[name]
    remainder = [
        action for action in sub._actions if getattr(action, "nargs", None) == argparse.REMAINDER
    ]
    assert remainder, (
        f"{name} is excluded from --json on the grounds that it forwards to another "
        "command, and it takes no forwarded argv"
    )


def test_changelog_puts_the_document_inside_the_artifact() -> None:
    """Not beside it.

    A caller asking for JSON is parsing stdout; a markdown changelog printed
    alongside the artifact would corrupt that parse.
    """
    from apiverity.cli.main import main

    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = main(
            [
                "changelog",
                str(_ROOT / "fixtures/apis/versioned/v1.yaml"),
                str(_ROOT / "fixtures/apis/versioned/v2.yaml"),
                "--json",
            ]
        )
    assert code == 0
    payload = json.loads(out.getvalue())
    assert payload["command"] == "changelog"
    assert payload["document"].lstrip().startswith("#")
    assert payload["format"] == "markdown"
    assert payload["change_count"] > 0


def test_the_mock_reports_its_address_before_it_blocks(monkeypatch: Any) -> None:
    """A --json that produced nothing until Ctrl+C would be a no-op flag."""
    import apiverity.mock as mock_module
    from apiverity.cli.main import main

    served: dict[str, Any] = {}

    def fake_serve(service: Any, **kwargs: Any) -> None:
        served.update(kwargs)

    monkeypatch.setattr(mock_module, "serve", fake_serve)

    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = main(
            ["mock", str(_ROOT / "fixtures/apis/crud/openapi.yaml"), "--port", "8099", "--json"]
        )

    assert code == 0
    payload = json.loads(out.getvalue())
    assert payload["command"] == "mock"
    assert payload["base_url"] == "http://127.0.0.1:8099"
    assert payload["operations"] > 0
    # And it really did go on to start the server.
    assert served.get("port") == 8099
