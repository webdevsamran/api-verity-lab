"""Four places said what protocols this tool reads, and all four were wrong.

GitHub keeps a repository's description and topics in a settings page. Nothing
reviews them, nothing notices when they go stale, and this repository's said it
handled **three** protocols while the loader read **seven** — so somebody
arriving from a search for "asyncapi breaking changes" was told, by the
repository's own card, that it does not do that.

It was not alone. The README's headline said OpenAPI, GraphQL and gRPC;
`mkdocs.yml` said those plus AsyncAPI; `pyproject.toml` said the README's
version. One sentence, four copies, four different lists.

This holds all of them against `apiverity.specs.loader.SPEC_FORMATS`, which is
the only one of the five that cannot be wrong.
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
_SCRIPT = _ROOT / "scripts" / "check_repo_metadata.py"
_METADATA = _ROOT / ".github" / "repo-metadata.yml"


def _module() -> Any:
    spec = importlib.util.spec_from_file_location("check_repo_metadata", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_repo_metadata"] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop("check_repo_metadata", None)
    return module


def _metadata() -> dict:
    return yaml.safe_load(_METADATA.read_text(encoding="utf-8"))


def test_the_offline_check_passes() -> None:
    """`--check` never touches the network: it is the file against the code."""
    result = subprocess.run(
        [sys.executable, str(_SCRIPT), "--check"], capture_output=True, text=True, cwd=_ROOT
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_every_supported_format_has_a_prose_name() -> None:
    """A list built from the format keys would read "swagger2, wsdl", which is
    not what anybody calls them -- so the names are written down, and a new
    format with no name would silently never be mentioned anywhere."""
    module = _module()
    assert not set(module.supported()) - set(module.PROSE)


@pytest.mark.parametrize("name", ["README.md", "mkdocs.yml", "pyproject.toml", "docs/index.md"])
def test_every_place_that_states_the_list_names_every_format(name: str) -> None:
    module = _module()
    head = (_ROOT / name).read_text(encoding="utf-8")[:4000]
    missing = [
        prose
        for key in module.supported()
        if (prose := module.PROSE.get(key)) and prose.lower() not in head.lower()
    ]
    assert not missing, f"{name} does not mention {missing}"


def test_the_description_fits_what_github_accepts() -> None:
    module = _module()
    description = " ".join(str(_metadata()["description"]).split())
    assert len(description) <= module.MAX_DESCRIPTION


def test_the_topics_are_topics_github_will_take() -> None:
    """GitHub rejects the whole edit on one bad topic, which is a confusing
    failure to debug from a settings page."""
    module = _module()
    topics = _metadata()["topics"]
    assert len(topics) <= module.MAX_TOPICS
    assert len(set(topics)) == len(topics)
    for topic in topics:
        assert module.TOPIC.match(topic), topic


def test_the_topics_cover_what_this_project_is_searched_for() -> None:
    """Not an SEO theory: each of these is a thing the tool demonstrably does,
    and a topic for a capability the tool lacks would be the kind of claim this
    repository does not make."""
    topics = set(_metadata()["topics"])
    assert {"api-governance", "breaking-changes", "contract-testing", "openapi"} <= topics
    # MCP is the wedge, and it was in neither the description nor the topics.
    assert "mcp" in topics


def test_the_apply_command_is_one_command() -> None:
    """The whole point of checking this file in: a maintainer should be able to
    run one thing rather than retype twenty topics into a form."""
    module = _module()
    command = module.apply_command()
    assert command.startswith("gh repo edit ")
    for topic in _metadata()["topics"]:
        assert f"--add-topic {topic}" in command


def test_nothing_here_writes_to_github() -> None:
    """Repository settings are the maintainer's. A script that edited them from
    CI would be a script with more access than it needs, and this one is run in
    CI."""
    source = _SCRIPT.read_text(encoding="utf-8")
    for forbidden in ("urlopen(request, data", 'method="PATCH"', "requests.patch", "gh repo edit'"):
        assert forbidden not in source


def test_ci_runs_the_offline_check() -> None:
    workflow = (_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "check_repo_metadata.py --check" in workflow
