"""An API named in Japanese must not crash the tool that governs it.

`apiverity validate` on a contract titled 注文管理API exited 4 -- the code this
project documents as "an unexpected error inside the tool" -- on a Windows
console. Python encodes stdout with the locale codepage, cp1252 cannot
represent those characters, and `print` raised. The contract was fine; the
console was the problem, and the exit code blamed the tool.

It was not only user content. `apiverity changelog` prints emoji, and a
`breaking --summary` verdict contains an arrow, so both commands failed the
same way on the same machine with the bundled fixtures.
"""

from __future__ import annotations

import contextlib
import io
from pathlib import Path

import pytest

from apiverity.cli.main import main

_ROOT = Path(__file__).resolve().parents[2]
_V1 = str(_ROOT / "fixtures/apis/versioned/v1.yaml")
_V2 = str(_ROOT / "fixtures/apis/versioned/v2.yaml")

#: A title outside cp1252 entirely. Latin-1 accents encode fine on a Windows
#: console, which is why this went unnoticed for so long -- the failure needs
#: a character the codepage has no room for.
_CJK_TITLE = "注文管理API"

_SPEC = f"""openapi: 3.1.0
info:
  title: {_CJK_TITLE}
  version: 1.0.0
paths:
  /orders:
    get:
      summary: 一覧
      responses:
        '200':
          description: OK
"""


class _LegacyConsole(io.TextIOWrapper):
    """stdout as a Windows console gives it: a single-byte codepage."""

    def __init__(self) -> None:
        self.raw_bytes = io.BytesIO()
        super().__init__(self.raw_bytes, encoding="cp1252", errors="strict")

    def text(self) -> str:
        self.flush()
        return self.raw_bytes.getvalue().decode("utf-8", errors="replace")


def _run(argv: list[str]) -> tuple[int, str]:
    console = _LegacyConsole()
    with contextlib.redirect_stdout(console), contextlib.redirect_stderr(io.StringIO()):
        code = main(argv)
    return code, console.text()


def test_a_contract_titled_outside_the_codepage_still_validates(tmp_path: Path) -> None:
    spec = tmp_path / "cjk.yaml"
    spec.write_text(_SPEC, encoding="utf-8")

    code, output = _run(["validate", str(spec)])
    assert code == 0, "a Japanese API title is not an internal error"
    assert _CJK_TITLE in output


def test_the_changelog_emoji_do_not_crash_a_legacy_console() -> None:
    code, output = _run(["changelog", _V1, _V2])
    assert code == 0
    assert "\U0001f534" in output, "the severity markers should survive, not be dropped"


def test_a_summary_arrow_does_not_crash_a_legacy_console() -> None:
    code, output = _run(["breaking", _V1, _V2, "--summary"])
    assert code == 1  # findings, which is the gate working
    assert "→" in output


@pytest.mark.parametrize("argv", [["rules"], ["explain", "BRK-OP-REMOVED"], ["self-test"]])
def test_no_command_is_left_encoding_the_locale_codepage(argv: list[str]) -> None:
    """The fix is in `main`, so it covers every command rather than three."""
    code, _ = _run(argv)
    assert code in (0, 1)


def test_a_stream_that_cannot_be_reconfigured_is_not_an_error() -> None:
    """A test's StringIO has no `reconfigure`, and neither do some pipes."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        assert main(["rules"]) == 0
    assert out.getvalue()
