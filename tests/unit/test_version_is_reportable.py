"""The version has to be reportable, and it has to be the real one.

`apiverity --version` did not exist: argparse rejected the flag and exited 2 —
while `.github/ISSUE_TEMPLATE/bug_report.md` asks every reporter to run exactly
that. Separately, `__version__` was pinned to "0.1.0" in the package while
`pyproject.toml` said 0.2.0, so even once the flag worked it would have named a
release that was never cut.

These two tests are what makes both unrepresentable going forward.
"""

from __future__ import annotations

import pathlib
import tomllib

import pytest

from apiverity import __version__
from apiverity.cli.main import main

PYPROJECT = pathlib.Path(__file__).resolve().parents[2] / "pyproject.toml"


def _declared_version() -> str:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def test_package_version_matches_pyproject() -> None:
    assert __version__ == _declared_version()


def test_version_flag_exits_zero_and_prints_the_version(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_bug_report_template_asks_for_a_command_that_works() -> None:
    """The template is the reason this flag has to exist."""
    template = PYPROJECT.parent / ".github/ISSUE_TEMPLATE/bug_report.md"
    if "apiverity --version" not in template.read_text(encoding="utf-8"):
        pytest.skip("template no longer asks for --version")
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
