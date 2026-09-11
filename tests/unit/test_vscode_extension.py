"""The VS Code client, held against the server it is a client for.

CI compiles the extension; it does not launch VS Code, so "it works in the
editor" is not a claim this repository has established. What *is* checkable is
the seam where the two halves are written in different languages and nothing
else would notice them disagreeing.

The disagreement that matters is the file list. If the extension activates for
fewer languages than the server lints, the one contract format nobody thinks of
silently never gets diagnostics — the client never starts for it, and the user
concludes the file is clean. `.wsdl` was exactly that case: it is `xml` to an
editor, and the first version of this extension did not list `xml`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_EXTENSION = _ROOT / "editors" / "vscode"
_PACKAGE = _EXTENSION / "package.json"
_SOURCE = _EXTENSION / "src" / "extension.ts"

#: Which editor language id each extension the server lints arrives as. Written
#: down because it is a judgement -- `.wsdl` is `xml`, `.gql` is `graphql` --
#: and a judgement nobody wrote down is one that gets quietly forgotten.
LANGUAGE_OF = {
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".graphql": "graphql",
    ".gql": "graphql",
    ".graphqls": "graphql",
    ".proto": "proto",
    ".wsdl": "xml",
}


def _manifest() -> dict:
    return json.loads(_PACKAGE.read_text(encoding="utf-8"))


def _selector_languages() -> set[str]:
    source = _SOURCE.read_text(encoding="utf-8")
    block = source[
        source.index("const SELECTOR") : source.index("];", source.index("const SELECTOR"))
    ]
    return set(re.findall(r"language:\s*'([a-z0-9]+)'", block))


def _activation_languages() -> set[str]:
    return {
        event.split(":", 1)[1]
        for event in _manifest()["activationEvents"]
        if event.startswith("onLanguage:")
    }


def test_the_mapping_covers_every_extension_the_server_lints() -> None:
    """A new extension added to the server with no language recorded here is
    one the editor will never start for."""
    from apiverity.lsp.diagnostics import EXTENSIONS

    missing = sorted(set(EXTENSIONS) - set(LANGUAGE_OF))
    assert not missing, (
        f"the server lints {missing} and this mapping says nothing about which editor "
        "language they arrive as"
    )


def test_the_extension_activates_for_every_language_the_server_lints() -> None:
    """The failure this catches is silent in both directions and visible in
    neither: the client never starts, so there is no error, and the user reads
    the absence of diagnostics as the absence of findings."""
    from apiverity.lsp.diagnostics import EXTENSIONS

    needed = {LANGUAGE_OF[suffix] for suffix in EXTENSIONS if suffix in LANGUAGE_OF}
    assert needed <= _activation_languages(), (
        f"the server lints these and the extension never activates for them: "
        f"{sorted(needed - _activation_languages())}"
    )


def test_the_document_selector_matches_the_activation_events() -> None:
    """Activating without selecting means a server that starts and is sent
    nothing; selecting without activating means a selector that never runs."""
    activation = _activation_languages()
    selector = _selector_languages()
    assert selector == activation, (
        f"selector-only: {sorted(selector - activation)}; "
        f"activation-only: {sorted(activation - selector)}"
    )


def test_it_does_not_activate_on_star() -> None:
    """`*` runs the extension in every window, for every file, including the
    ones it has no opinion about."""
    assert "*" not in _manifest()["activationEvents"]
    assert "onStartupFinished" not in _manifest()["activationEvents"]


def test_the_server_is_started_by_the_command_this_project_ships() -> None:
    from apiverity.cli.main import build_parser

    manifest = _manifest()
    default = manifest["contributes"]["configuration"]["properties"]["apiverity.args"]["default"]
    assert default == ["lsp"]
    subcommands = build_parser()._subparsers._group_actions[0].choices  # type: ignore[union-attr]
    assert "lsp" in subcommands, "the extension's default args name a command that does not exist"


def test_the_extension_version_tracks_the_package() -> None:
    """Two version numbers for one tool is a support question waiting to
    happen: "which apiverity does extension 0.4 need?" has no answer."""
    from apiverity import __version__

    assert _manifest()["version"] == __version__


@pytest.mark.parametrize(
    "field", ["publisher", "license", "repository", "engines", "main", "categories"]
)
def test_the_manifest_carries_what_a_marketplace_listing_needs(field: str) -> None:
    assert _manifest().get(field), f"package.json has no {field}"


def test_the_licence_matches_the_repositorys() -> None:
    assert _manifest()["license"] == "Apache-2.0"


def test_a_missing_executable_is_reported_rather_than_swallowed() -> None:
    """The most misleading thing a linter can do is nothing. An extension whose
    server will not start and says nothing leaves the reader concluding their
    contract is clean."""
    source = _SOURCE.read_text(encoding="utf-8")
    assert "showWarningMessage" in source
    assert "docs/install.md" in source
    # And it checks by *running* the thing, because a file-exists check passes
    # for a stale shim pointing at a removed virtualenv.
    assert "'--version'" in source


def test_the_compiled_output_is_not_committed() -> None:
    """`out/` is a build product. Committing it means reviewing generated
    JavaScript in every diff, and a compiled file that disagrees with its
    source is the hardest kind of stale."""
    ignored = (_EXTENSION / ".gitignore").read_text(encoding="utf-8").split()
    assert "out/" in ignored
    assert "node_modules/" in ignored


def test_ci_compiles_the_extension() -> None:
    """Otherwise it is TypeScript nobody has ever run `tsc` over, and the first
    person to find out is whoever tries to install it."""
    workflow = (_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "editors/vscode" in workflow
