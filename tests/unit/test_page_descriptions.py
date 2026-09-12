"""Ninety-five of ninety-seven documentation pages published the same sentence.

A MkDocs page with no `description:` front matter inherits `site_description`
from `mkdocs.yml`. Nothing anywhere fails when that happens -- the page renders
correctly, the build is green, `mkdocs build --strict` is satisfied -- and the
only place it shows is a search result, where ninety-seven results carry one
identical line and the engine substitutes an excerpt of its own choosing.

That is the defect class this repository keeps finding: a thing that is only
wrong somewhere nobody on the team looks.

So every page's description lives in `scripts/page_meta.py`, the generators
that own twenty-seven of those pages import it from there, and
`scripts/check_page_descriptions.py` holds the committed tree to it. This
checks the checker -- including that it fails, which is the half that is easy
to leave untested and the half that matters.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = _ROOT / "scripts"
_CHECKER = _SCRIPTS / "check_page_descriptions.py"
_DOCS = _ROOT / "docs"
_MKDOCS = _ROOT / "mkdocs.yml"


def _module(name: str) -> Any:
    """Import a `scripts/` module without leaving it in `sys.modules`."""
    path = _SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    added = str(_SCRIPTS) not in sys.path
    if added:
        sys.path.insert(0, str(_SCRIPTS))
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(name, None)
        if added:
            sys.path.remove(str(_SCRIPTS))
    return module


@pytest.fixture(scope="module")
def meta() -> Any:
    return _module("page_meta")


@pytest.fixture(scope="module")
def checker() -> Any:
    return _module("check_page_descriptions")


def _pages() -> list[str]:
    return sorted(p.relative_to(_DOCS).as_posix() for p in _DOCS.rglob("*.md"))


# -- the committed tree ----------------------------------------------------


def test_the_committed_tree_passes() -> None:
    result = subprocess.run(
        [sys.executable, str(_CHECKER), "--check"], capture_output=True, text=True, cwd=_ROOT
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_every_page_has_a_description(meta: Any) -> None:
    """The whole point. A page added without one is invisible until a search
    result is wrong, so the absence fails here instead."""
    missing = [page for page in _pages() if page not in meta.DESCRIPTIONS]
    assert not missing, f"pages with no meta description: {missing}"


def test_no_description_describes_a_page_that_was_deleted(meta: Any) -> None:
    """The other direction, which is how a table like this usually rots."""
    orphans = sorted(set(meta.DESCRIPTIONS) - set(_pages()))
    assert not orphans, f"descriptions for pages that do not exist: {orphans}"


def test_no_two_pages_share_a_description(meta: Any) -> None:
    """Two identical descriptions are the same signal as ninety-seven, only
    smaller."""
    seen: dict[str, str] = {}
    clashes = []
    for page, description in sorted(meta.DESCRIPTIONS.items()):
        if description in seen:
            clashes.append((seen[description], page))
        seen[description] = page
    assert not clashes, f"pages sharing one description: {clashes}"


def test_no_page_repeats_the_site_description(meta: Any) -> None:
    """Copying `site_description` onto a page is the same defect with more
    steps."""
    site = " ".join(yaml.safe_load(_MKDOCS.read_text(encoding="utf-8"))["site_description"].split())
    repeated = [
        page
        for page, description in meta.DESCRIPTIONS.items()
        if " ".join(description.split()) == site
    ]
    assert not repeated, f"these repeat the site description: {repeated}"


@pytest.mark.parametrize("page", _pages())
def test_each_description_is_a_usable_length(page: str, meta: Any, checker: Any) -> None:
    """Under seventy characters says nothing; over a hundred and sixty-five is
    cut off in the result it was written for."""
    length = len(meta.DESCRIPTIONS[page])
    assert checker.MIN_LENGTH <= length <= checker.MAX_LENGTH, f"{page}: {length} characters"


@pytest.mark.parametrize("page", _pages())
def test_each_page_declares_the_description_recorded_for_it(
    page: str, meta: Any, checker: Any
) -> None:
    """Including the twenty-seven generated ones, whose generators import the
    same table -- which is the only reason a regenerated page keeps its
    description at all."""
    declared = checker.declared((_DOCS / page).read_text(encoding="utf-8"))
    assert declared == meta.DESCRIPTIONS[page]


# -- the checker itself ----------------------------------------------------


def test_the_checker_fails_on_a_page_with_no_entry(
    checker: Any, meta: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A check that has never failed is a check nobody has tested."""
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "index.md").write_text(checker.front_matter("index.md") + "# Home\n", encoding="utf-8")
    (docs / "brand-new.md").write_text("# A page somebody just added\n", encoding="utf-8")
    monkeypatch.setattr(checker, "DOCS", docs)
    monkeypatch.setattr(checker, "DESCRIPTIONS", {"index.md": meta.DESCRIPTIONS["index.md"]})

    found = checker.problems()
    assert any("brand-new.md" in problem for problem in found), found


def test_the_checker_fails_when_a_page_is_edited_away_from_the_table(
    checker: Any, meta: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Editing the front matter directly is the obvious thing to do and the
    wrong one, because a generated page loses it on the next render."""
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "index.md").write_text(
        "---\ndescription: >-\n  Something a person typed straight into the page instead.\n"
        "---\n\n# Home\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(checker, "DOCS", docs)
    monkeypatch.setattr(checker, "DESCRIPTIONS", {"index.md": meta.DESCRIPTIONS["index.md"]})

    found = checker.problems()
    assert any("not the one in" in problem for problem in found), found


def test_the_checker_reports_every_problem_rather_than_the_first(
    checker: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Otherwise adding four pages is four runs."""
    docs = tmp_path / "docs"
    docs.mkdir()
    for name in ("one.md", "two.md", "three.md"):
        (docs / name).write_text(f"# {name}\n", encoding="utf-8")
    monkeypatch.setattr(checker, "DOCS", docs)
    monkeypatch.setattr(checker, "DESCRIPTIONS", {})

    assert len(checker.problems()) == 3


def test_writing_replaces_a_stale_block_rather_than_stacking_another(
    checker: Any, meta: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    page = docs / "index.md"
    page.write_text(
        "---\ndescription: >-\n  An older sentence.\n---\n\n# Home\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(checker, "DOCS", docs)
    monkeypatch.setattr(checker, "DESCRIPTIONS", {"index.md": meta.DESCRIPTIONS["index.md"]})

    checker.write()
    text = page.read_text(encoding="utf-8")
    assert text.count("---\ndescription:") == 1
    assert checker.declared(text) == meta.DESCRIPTIONS["index.md"]
    assert text.rstrip().endswith("# Home")


def test_front_matter_refuses_a_page_it_does_not_know(meta: Any) -> None:
    """A generator that silently emitted no description would produce exactly
    the defect this table exists to prevent, so it raises instead."""
    with pytest.raises(KeyError, match="page_meta"):
        meta.front_matter("a-page-nobody-added.md")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "---\ndescription: >-\n  Folded across\n  two lines.\n---\n\n# T\n",
            "Folded across two lines.",
        ),
        ('---\ndescription: "Quoted inline."\n---\n\n# T\n', "Quoted inline."),
        ("---\ndescription: Bare inline.\n---\n\n# T\n", "Bare inline."),
        ("# No front matter at all\n", None),
        ("---\ntitle: Something else\n---\n\n# T\n", None),
    ],
)
def test_the_front_matter_reader_handles_the_shapes_it_will_meet(
    text: str, expected: str | None, checker: Any
) -> None:
    assert checker.declared(text) == expected
