"""The files that ask for money and give credit, held to the same rule as the rest.

Sponsorship and acknowledgement pages are where a project is most tempted to be
loose: a funding platform nobody registered, a tier promising something the
maintainer will not deliver, a dependency added three releases ago and never
credited, a link to a file that was renamed.

None of those fail a build anywhere else, and every one of them is the reader's
first impression.

Also checked here: every relative link in the repository's top-level markdown
resolves. `mkdocs build --strict` catches broken links inside `docs/`; nothing
caught a README pointing at a file that does not exist.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[2]
_FUNDING = _ROOT / ".github" / "FUNDING.yml"
_SPONSORS = _ROOT / "SPONSORS.md"
_CREDITS = _ROOT / "ACKNOWLEDGEMENTS.md"

#: Top-level markdown a reader reaches from the repository page.
_TOP_LEVEL = (
    "README.md",
    "SPONSORS.md",
    "ACKNOWLEDGEMENTS.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "ARCHITECTURE.md",
    "PRODUCT_GAPS.md",
    "ROADMAP.md",
)

#: Platforms GitHub renders a button for. A key outside this set is silently
#: ignored, which looks identical to a key that works.
_FUNDING_KEYS = {
    "github",
    "patreon",
    "open_collective",
    "ko_fi",
    "tidelift",
    "community_bridge",
    "liberapay",
    "issuehunt",
    "lfx_crowdfunding",
    "polar",
    "buy_me_a_coffee",
    "thanks_dev",
    "custom",
}

_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")


# -- funding ---------------------------------------------------------------


def test_the_funding_file_is_valid_and_names_only_real_keys() -> None:
    """GitHub ignores an unknown key silently, so a typo renders no button and
    reports nothing -- the same failure as having no file, with the appearance
    of having one."""
    data = yaml.safe_load(_FUNDING.read_text(encoding="utf-8"))
    assert isinstance(data, dict) and data, "the funding file declares nothing"
    unknown = sorted(set(data) - _FUNDING_KEYS)
    assert not unknown, f"GitHub does not render these keys: {unknown}"


def test_the_funding_file_names_the_repository_owner() -> None:
    """A funding file pointing at somebody else's account is the worst possible
    kind of typo."""
    data = yaml.safe_load(_FUNDING.read_text(encoding="utf-8"))
    assert data.get("github") == ["webdevsamran"]


# -- sponsorship -----------------------------------------------------------


def test_the_sponsors_page_says_what_sponsorship_does_not_buy() -> None:
    """The half that is easy to leave out, and the half that prevents a
    misunderstanding discovered later."""
    text = _SPONSORS.read_text(encoding="utf-8")
    assert "What it does not buy" in text
    for promise in ("not priority support", "not an sla", "not a feature on demand"):
        assert promise in text.lower(), promise


def test_no_tier_offers_influence_over_a_finding() -> None:
    """The rule that is the product. A gate a sponsor can soften is not a gate,
    and this project's benchmark publishes where it loses for the same
    reason."""
    text = _SPONSORS.read_text(encoding="utf-8").lower()
    assert "no sponsor gets a rule softened" in text
    # And no logo in anything that gates somebody's deploy.
    assert "do not carry advertising" in text


def test_the_sponsor_list_is_a_fact_rather_than_an_omission() -> None:
    """Either there are sponsors named, or the page says there are none. A
    heading with nothing under it reads as neglect."""
    text = _SPONSORS.read_text(encoding="utf-8")
    section = text.split("## Current sponsors", 1)[1].split("##", 1)[0]
    assert section.strip(), "the sponsors section is empty"
    named = [line for line in section.splitlines() if line.startswith("- ")]
    assert named or "None yet" in section


# -- credits ---------------------------------------------------------------


def test_every_runtime_dependency_is_credited() -> None:
    """A dependency added and never credited is the common case, because
    nothing anywhere fails when it happens."""
    pyproject = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    credits = _CREDITS.read_text(encoding="utf-8").lower()

    declared = [
        re.split(r"[<>=!~\[]", spec)[0].strip().lower()
        for spec in pyproject["project"]["dependencies"]
    ]
    missing = [name for name in declared if name not in credits]
    assert not missing, f"runtime dependencies with no credit: {missing}"


def test_every_optional_extra_is_credited() -> None:
    pyproject = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    credits = _CREDITS.read_text(encoding="utf-8").lower()
    extras = pyproject["project"].get("optional-dependencies", {})
    for name, specs in extras.items():
        if name == "dev":
            continue
        for spec in specs:
            package = re.split(r"[<>=!~\[]", spec)[0].strip().lower()
            assert package in credits, f"{package} (extra '{name}') is not credited"


def test_every_spec_format_the_loader_reads_is_credited() -> None:
    """Each of these is somebody's years of committee work, published for
    free. A format read without acknowledgement is the cheapest thing to get
    wrong."""
    from apiverity.specs.loader import SPEC_FORMATS

    credits = _CREDITS.read_text(encoding="utf-8").lower()
    names = {
        "openapi": "openapi",
        "swagger2": "swagger 2.0",
        "asyncapi": "asyncapi",
        "graphql": "graphql",
        "grpc": "grpc",
        "mcp": "model context protocol",
        "wsdl": "wsdl",
    }
    for key in SPEC_FORMATS:
        assert key in names, f"{key} is read and this test has no name for it"
        assert names[key] in credits, f"{names[key]} is read and not credited"


def test_the_credits_do_not_claim_borrowed_code() -> None:
    """Design inspiration and copied code are different things, and the
    difference is a licence question."""
    text = _CREDITS.read_text(encoding="utf-8")
    assert "None of these projects' code is in this one." in text


# -- links -----------------------------------------------------------------


@pytest.mark.parametrize("name", _TOP_LEVEL)
def test_every_relative_link_resolves(name: str) -> None:
    """`mkdocs build --strict` checks links inside `docs/`. Nothing checked a
    README pointing at a file that was renamed."""
    path = _ROOT / name
    if not path.exists():
        pytest.skip(f"{name} does not exist")

    broken = []
    for target in _LINK.findall(path.read_text(encoding="utf-8")):
        if target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        resolved = (_ROOT / target.split("#", 1)[0]).resolve()
        if not resolved.exists():
            broken.append(target)
    assert not broken, f"{name} links to files that do not exist: {broken}"


def test_the_readme_points_at_the_sponsorship_and_credit_pages() -> None:
    """Both exist to be found. A page nothing links to is a file."""
    readme = (_ROOT / "README.md").read_text(encoding="utf-8")
    assert "SPONSORS.md" in readme
    assert "ACKNOWLEDGEMENTS.md" in readme
    assert "github.com/sponsors/webdevsamran" in readme


def test_the_prepared_awesome_entries_exist_because_the_roadmap_cites_them() -> None:
    """`docs/roadmap-status.md` tells a reader the entries are prepared. A
    citation to a file that does not exist is the defect this project keeps
    finding in other people's documentation."""
    prepared = _ROOT / "docs" / "awesome-list-submissions.md"
    assert prepared.exists()
    status = (_ROOT / "docs" / "roadmap-status.md").read_text(encoding="utf-8")
    assert "awesome-list-submissions.md" in status
