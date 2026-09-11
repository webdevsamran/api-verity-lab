"""Which capabilities no command reaches, pinned so the list cannot drift.

`docs/capability-status.md` grades a capability EXISTING when it is
implemented and tested. Seven modules are implemented, tested, and reachable
from no command — importable from Python, absent from the CLI. A reader will
not distinguish those two things unless told, so the page tells them, and this
file makes the page's list a fact about the code rather than a note somebody
wrote once.

The list is expected to *shrink*: wiring one up, or deleting it, are both
progress. What must not happen quietly is a module joining it — that is a
feature written and never connected, which is how four published rules came to
be unreachable and how "Lint — VERIFIED" came to be published about an engine
nothing ran.
"""

from __future__ import annotations

import importlib.util
import pathlib
from typing import Any

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_PACKAGE = _ROOT / "apiverity"
_DOC = _ROOT / "docs" / "capability-status.md"

#: Reachable by a route this walk cannot see, each for a stated reason.
#:
#: The walk starts at the two console scripts. These are reached another way,
#: and listing them here is how that stays a decision rather than an oversight.
REACHED_OTHERWISE = {
    "apiverity.cli.__main__": "a console entry point itself (`python -m apiverity.cli`)",
    "apiverity.sdk": "the supported library surface; users import it directly",
    "apiverity.server.launch": "what docker/entrypoint.sh runs "
    "(`python -m apiverity.server.launch`), and the supported way to start the "
    "server without Docker",
    "apiverity.server.api": "imported by server.launch",
    "apiverity.server.oidc": "imported by server.launch when an issuer is configured",
    "apiverity.server.auth": "imported by server.api",
    "apiverity.server.decision": "imported by server.api",
    "apiverity.server.jobs": "imported by server.api",
    "apiverity.server.webhooks": "imported by server.api",
    "apiverity.rules.parity": "used by scripts/generate_rule_parity.py",
    "apiverity.mock.mcp_server": "the server under test, used by the demo generator and "
    "five integration tests",
    "apiverity.fuzz.corpus": "used by scripts/generate-demo-data.py",
}

#: Implemented, tested, and reached by no command. Published in
#: docs/capability-status.md under "Library-only capabilities".
#:
#: **Empty**, and that is the interesting part. It began at seven: five were
#: wired to a command, one -- `core.model_v2` -- was deleted as a parallel
#: implementation of things this project already ships, and the page it is
#: pinned against says so. An empty list is not the end of the check: the test
#: below fails the build when a module joins it, which is what the mechanism is
#: for.
LIBRARY_ONLY: set[str] = set()


def _walk() -> Any:
    spec = importlib.util.spec_from_file_location(
        "check_catalog_test", _ROOT / "tests" / "unit" / "test_check_catalog.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _unreachable() -> set[str]:
    walk = _walk()
    reachable = walk._reachable_modules()
    out: set[str] = set()
    for path in sorted(_PACKAGE.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        name = walk._module_name(path)
        if name in reachable or name in REACHED_OTHERWISE:
            continue
        # A bare package `__init__` re-exporting its children is not a
        # capability, and the walk resolves the children rather than the
        # package.
        if path.name == "__init__.py" or path.stat().st_size < 800:
            continue
        if name.startswith("apiverity.plugins"):
            # Loaded by name through entry points, which no import walk sees.
            continue
        out.add(name)
    return out


def test_no_module_has_quietly_stopped_being_reachable() -> None:
    """The direction that matters. A module joining this list is a feature
    written and never connected."""
    new = sorted(_unreachable() - LIBRARY_ONLY)
    assert new == [], (
        f"these modules are reachable from no command and are not in the published list: "
        f"{new}. Wire them up, delete them, or add them to LIBRARY_ONLY *and* to "
        "docs/capability-status.md -- but do not leave the question invisible."
    )


def test_the_published_list_is_not_stale() -> None:
    """The other direction, which is progress: wiring one up or deleting it
    should remove it from the page as well as from here."""
    gone = sorted(LIBRARY_ONLY - _unreachable())
    assert gone == [], (
        f"these are in the published list and are now reachable: {gone}. Remove them "
        "from LIBRARY_ONLY and from docs/capability-status.md."
    )


def test_every_entry_appears_on_the_page() -> None:
    text = _DOC.read_text(encoding="utf-8")
    assert "## Library-only capabilities" in text
    missing = sorted(name for name in LIBRARY_ONLY if f"`{name}`" not in text)
    assert missing == [], f"docs/capability-status.md does not mention {missing}"


def test_the_page_says_the_list_is_empty_while_it_is() -> None:
    """An empty section with a table header and no rows reads as an oversight.
    While there is nothing in the list, the page has to say so in words."""
    text = _DOC.read_text(encoding="utf-8")
    if LIBRARY_ONLY:
        return
    assert "is empty" in text


def test_the_page_says_what_import_only_would_mean() -> None:
    """The two sentences that keep the list from reading as either an
    accusation or a roadmap. Kept while the list is empty, because the next
    entry arrives with them already written."""
    text = _DOC.read_text(encoding="utf-8")
    assert 'is not "broken"' in text
    assert "not a plan" in text


def test_every_exception_carries_a_reason() -> None:
    """`REACHED_OTHERWISE` is the place an oversight would hide: adding a name
    to it silences the check. A reason does not prevent that, and it does make
    it visible in review."""
    assert all(reason.strip() for reason in REACHED_OTHERWISE.values())
