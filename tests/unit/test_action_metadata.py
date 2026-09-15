"""Every documented way to use this action failed with "Unable to resolve action".

`action.yml` sits at the repository root, so GitHub offers to publish it to the
Marketplace. The metadata was ready for that. The documentation was not:
`docs/ci.md` told readers `@v1` four times, `docs/faq.md` said `@v0` once, and
neither tag existed. The only tag this repository had was `v0.2.0`, which
predates `action.yml` entirely.

So every published example was a copy-paste that fails on the first run, and
nothing noticed -- because nothing in this repository had ever used the action
the way a consumer does. The `contract-gate` workflow reimplements the same
shell rather than calling it.

Two things now stop that recurring. `ci.yml` runs the action itself, with
inputs, and reads the outputs it promises. And this holds the metadata to what
the Marketplace requires and the documentation to the tag `release.yml`
actually moves -- because GitHub validates a listing only when one is created,
which is after the tag exists and the worst moment to learn the colour is
wrong.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = _ROOT / "scripts"
_SCRIPT = _SCRIPTS / "check_action_metadata.py"
_ACTION = _ROOT / "action.yml"
_PAGE = _ROOT / "docs" / "github-action.md"
_RELEASE = _ROOT / ".github" / "workflows" / "release.yml"
_CI = _ROOT / ".github" / "workflows" / "ci.yml"


def _module() -> Any:
    spec = importlib.util.spec_from_file_location("check_action_metadata", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    added = str(_SCRIPTS) not in sys.path
    if added:
        sys.path.insert(0, str(_SCRIPTS))
    sys.modules["check_action_metadata"] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop("check_action_metadata", None)
        if added:
            sys.path.remove(str(_SCRIPTS))
    return module


@pytest.fixture(scope="module")
def checker() -> Any:
    return _module()


@pytest.fixture(scope="module")
def meta() -> dict[str, Any]:
    return yaml.safe_load(_ACTION.read_text(encoding="utf-8"))


# -- the committed state ---------------------------------------------------


def test_the_committed_action_is_publishable() -> None:
    result = subprocess.run(
        [sys.executable, str(_SCRIPT), "--check"], capture_output=True, text=True, cwd=_ROOT
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_action_is_at_the_repository_root() -> None:
    """GitHub reads a Marketplace action from the root and nowhere else. A
    nested `action.yml` is a working action that cannot be listed."""
    assert _ACTION.is_file()


def test_the_branding_is_the_kind_github_accepts(meta: dict[str, Any], checker: Any) -> None:
    """Missing or invalid branding is the single most common reason a listing
    is refused, and it is refused at release time."""
    branding = meta["branding"]
    assert branding["color"] in checker.BRANDING_COLORS
    assert branding["icon"] not in checker.BRANDING_ICONS_REFUSED
    assert checker.ICON_SHAPE.match(branding["icon"])


def test_every_input_and_output_is_described(meta: dict[str, Any]) -> None:
    """These are what the Marketplace listing renders."""
    for section in ("inputs", "outputs"):
        for name, spec in meta[section].items():
            assert str(spec.get("description", "")).strip(), f"{section}.{name}"


# -- the reference a reader copies ----------------------------------------


def test_the_documented_tag_is_the_one_the_release_moves(checker: Any) -> None:
    """The defect this file exists for. `@v1` in the docs and no `v1` tag is a
    quickstart that cannot work, and it is only visible to somebody who tries
    it in another repository."""
    version = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    major = "v" + str(version["project"]["version"]).split(".")[0]
    assert checker.major_tag() == major
    assert not checker.reference_problems(major)


def test_the_major_tag_is_derived_rather_than_written_down(checker: Any) -> None:
    """A 1.0 release has to change one number, not five files."""
    assert checker.major_tag("0.2.0") == "v0"
    assert checker.major_tag("1.4.2") == "v1"
    assert checker.major_tag("12.0.0") == "v12"


def test_the_release_workflow_moves_the_major_tag() -> None:
    """Without this the documented reference resolves once, on the day the tag
    is cut, and then goes stale for every release after it."""
    workflow = yaml.safe_load(_RELEASE.read_text(encoding="utf-8"))
    assert "major-tag" in workflow["jobs"], "nothing moves the tag consumers pin"
    job = workflow["jobs"]["major-tag"]
    assert job["permissions"]["contents"] == "write"
    body = _RELEASE.read_text(encoding="utf-8")
    assert "git push --force origin" in body
    # A pre-release must not move a tag stable consumers are pinned to.
    assert "pre-release" in body


def test_the_action_is_actually_run_somewhere() -> None:
    """A mechanism that exists and is never called is a defect here, and this
    one was about to be published to a marketplace."""
    workflow = yaml.safe_load(_CI.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["action"]["steps"]
    assert any(step.get("uses") == "./" for step in steps), (
        "ci.yml has an `action` job that never uses the action"
    )


def test_the_action_job_exercises_more_than_the_happy_path() -> None:
    """A step observed only succeeding is a step nobody has tested.

    The gate's own find-the-breaking-change logic is covered by the Python
    suite and by `contract-gate` on every pull request; what this job is for is
    the action *wrapper* -- that its inputs are read, its outputs are set, and
    that a bad input is refused rather than guessed at.
    """
    body = _CI.read_text(encoding="utf-8")
    assert "A clean contract passes" in body
    assert "A contract with no base revision is validated, not errored" in body
    assert "An unknown fail-on is refused rather than ignored" in body


def test_the_action_job_reads_the_outputs_the_action_promises() -> None:
    """Five outputs nothing consumed is five outputs that can quietly stop
    being set."""
    body = _CI.read_text(encoding="utf-8")
    for output in ("outputs.result", "outputs.specs-checked"):
        assert output in body, output


# -- the checker itself ----------------------------------------------------


def test_missing_branding_is_reported(checker: Any, meta: dict[str, Any]) -> None:
    """A check that has never failed is a check nobody has tested."""
    without = {k: v for k, v in meta.items() if k != "branding"}
    found = checker.marketplace_problems(without)
    assert any("branding" in problem for problem in found), found


@pytest.mark.parametrize("color", ["teal", "BLUE", "#0366d6", ""])
def test_a_colour_github_refuses_is_reported(
    checker: Any, meta: dict[str, Any], color: str
) -> None:
    broken = dict(meta) | {"branding": {"icon": "git-pull-request", "color": color}}
    found = checker.marketplace_problems(broken)
    assert any("branding.color" in problem for problem in found), (color, found)


@pytest.mark.parametrize("icon", ["coffee", "key", "x", "tool"])
def test_an_icon_on_githubs_refused_list_is_reported(
    checker: Any, meta: dict[str, Any], icon: str
) -> None:
    """These are real Feather icons that GitHub specifically will not take."""
    broken = dict(meta) | {"branding": {"icon": icon, "color": "blue"}}
    found = checker.marketplace_problems(broken)
    assert any("refuses" in problem for problem in found), (icon, found)


def test_an_undescribed_input_is_reported(checker: Any, meta: dict[str, Any]) -> None:
    broken = dict(meta) | {"inputs": {"mystery": {"required": False, "default": ""}}}
    found = checker.surface_problems(broken)
    assert found == ["inputs.mystery has no description"]


def test_a_stale_documented_tag_is_reported(checker: Any) -> None:
    """Held against a major the project does not have, every committed `uses:`
    line should be reported -- which is what happened for real."""
    found = checker.reference_problems("v99")
    assert found, "no documented `uses:` line was found at all"
    assert all("v99" in problem for problem in found)


def test_the_page_is_generated_rather_than_typed(checker: Any) -> None:
    """Eleven inputs and five outputs typed by hand are right on the day they
    are typed."""
    rendered = checker.front_matter("github-action.md") + checker.page()
    assert _PAGE.read_text(encoding="utf-8") == rendered


def test_the_page_names_what_the_owner_still_has_to_do() -> None:
    """Publishing is a person accepting an agreement and ticking a box. A page
    that implies the repository does it leaves somebody waiting."""
    text = _PAGE.read_text(encoding="utf-8")
    assert "Marketplace Developer Agreement" in text
    assert "Publish this Action to the GitHub Marketplace" in text


def test_the_page_says_what_it_cannot_check(checker: Any) -> None:
    """The accepted-icon list is not vendored, and saying so is the difference
    between a limit and a hole."""
    text = _PAGE.read_text(encoding="utf-8")
    assert "unique across the Marketplace" in text
    assert "not vendored here" in text


def test_a_table_cell_cannot_break_the_table(checker: Any) -> None:
    """`spec-dirs` defaults to a regular expression full of pipes, and an
    unescaped one silently turns a row into three columns."""
    assert checker._cell("a|b") == "a" + chr(92) + "|b"
    assert checker._cell("wrapped\n  onto  lines") == "wrapped onto lines"
