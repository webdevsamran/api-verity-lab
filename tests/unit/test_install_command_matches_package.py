"""The install command shown to users must be the real distribution name.

`web/src/pages/overview.tsx` renders a copy-to-clipboard button reading
`pip install apiverity-lab`, while pyproject declares `api-verity-lab`. A
user clicking copy got a command that cannot work. The README had it right,
so nothing caught the drift.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]


def _distribution_name() -> str:
    with (_ROOT / "pyproject.toml").open("rb") as fh:
        return tomllib.load(fh)["project"]["name"]


def test_no_source_advertises_a_wrong_install_name() -> None:
    name = _distribution_name()
    pattern = re.compile(r"pip install\s+(?!-)([A-Za-z0-9._-]+)")
    offenders: list[str] = []

    searched = [
        *(_ROOT / "web" / "src").rglob("*.tsx"),
        *(_ROOT / "web" / "src").rglob("*.ts"),
        *_ROOT.glob("*.md"),
        *(_ROOT / "docs").glob("*.md"),
    ]
    for path in searched:
        for match in pattern.finditer(path.read_text(encoding="utf-8")):
            advertised = match.group(1)
            if advertised in {name, "-e", "."}:
                continue
            # Third-party tooling installs are fine; only flag this project's
            # own name being spelled wrongly.
            if advertised.replace("-", "") == name.replace("-", ""):
                offenders.append(f"{path.relative_to(_ROOT)}: pip install {advertised}")

    assert not offenders, (
        f"distribution is named {name!r}; these advertise a different spelling: "
        + "; ".join(offenders)
    )
