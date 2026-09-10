"""The non-breaking rules were reachable, undocumented, and unexplainable.

`apiverity explain BRK-RESP-FIELD-REMOVED` has worked since the breaking rules
got a catalogue. `apiverity explain SEC-CORS-WILDCARD` answered *"no rule with
id 'SEC-CORS-WILDCARD'"* -- about a rule the tool emits, in the command that
exists because a rule nobody understands gets suppressed rather than fixed.

The test that matters here runs in both directions. A check that emits an id
the catalogue does not carry is a rule that cannot be explained; a catalogue
entry nothing emits is a rule that is published and dead, which is the defect
this project has now found four separate times. Neither direction is caught by
anything else, because both fail silently.
"""

from __future__ import annotations

import contextlib
import io
import json
import re
from pathlib import Path
from typing import Any

from apiverity.cli.main import main
from apiverity.rules.check_catalog import catalog
from apiverity.security.catalog import spec_for

SECURITY_CATALOG = catalog()

_ROOT = Path(__file__).resolve().parents[2]
_PACKAGE = _ROOT / "apiverity"
_DOC = _ROOT / "docs" / "check-rules.md"

#: `rule_id="SEC-..."` anywhere in the package, which is how every one of these
#: is constructed. Read from the source rather than by running every check,
#: because a check that needs a live server to fire would otherwise be invisible
#: to this test and its rule would be the one that goes missing.
_EMITTED = re.compile(r'rule_id=(?:")((?:SEC|LIFECYCLE)-[A-Z0-9-]+)(?:")')


def _emitted_ids() -> set[str]:
    found: set[str] = set()
    for path in _PACKAGE.rglob("*.py"):
        if path.name in {"catalog.py", "check_catalog.py", "lifecycle_catalog.py"}:
            continue
        found.update(_EMITTED.findall(path.read_text(encoding="utf-8")))
    return found


def _run(argv: list[str]) -> tuple[int, dict[str, Any]]:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = main(argv)
    try:
        return code, json.loads(buffer.getvalue())
    except ValueError:
        return code, {}


# --------------------------------------------------- completeness, both ways


def test_every_emitted_security_rule_is_in_the_catalogue() -> None:
    missing = sorted(_emitted_ids() - set(SECURITY_CATALOG))
    assert missing == [], (
        f"these rules are emitted and cannot be explained: {missing}. "
        "Add them to apiverity/security/catalog.py."
    )


def test_every_catalogued_security_rule_is_emitted_by_something() -> None:
    orphaned = sorted(set(SECURITY_CATALOG) - _emitted_ids())
    assert orphaned == [], (
        f"these rules are catalogued and emitted by nothing: {orphaned}. "
        "A rule nobody can produce still gets configured, waited for, and trusted."
    )


def test_every_entry_says_what_to_do() -> None:
    """Including the ones where the answer is "nothing".

    An INFO with an empty `instead` reads as a rule nobody finished, and a
    reader cannot tell that apart from a rule that wants action.
    """
    empty = [rid for rid, spec in SECURITY_CATALOG.items() if not spec.instead.strip()]
    assert empty == []


def test_an_informational_rule_says_so_rather_than_demanding_an_edit() -> None:
    """`SEC-AUTH-ANONYMOUS` records that the document said what it meant.

    Telling someone to fix it would be telling them to undo the thing
    `SEC-AUTH-MISSING` asked for.
    """
    spec = spec_for("SEC-AUTH-ANONYMOUS")
    assert spec is not None
    assert spec.instead.lower().startswith("nothing")


# ------------------------------------------------------------------ explain


def test_explain_answers_for_a_security_rule() -> None:
    code, payload = _run(["--no-config", "explain", "SEC-CORS-WILDCARD", "--json"])
    assert code == 0
    assert payload["rule_id"] == "SEC-CORS-WILDCARD"
    assert payload["severity"] == "WARN"
    assert payload["instead"]


def test_explain_gives_the_exact_override_to_change_it() -> None:
    """The question someone reaching for `explain` actually has."""
    _code, payload = _run(["--no-config", "explain", "SEC-BASIC-AUTH", "--json"])
    assert payload["severity_override"] == "--severity-override SEC-BASIC-AUTH=INFO"


def test_explain_says_which_command_produces_it() -> None:
    """`SEC-RESPONSE-CREDENTIAL` comes from a run against a live service, not
    from reading a file, and someone waiting for it from `validate` waits
    forever."""
    _code, payload = _run(["--no-config", "explain", "SEC-RESPONSE-CREDENTIAL", "--json"])
    assert "drift" in payload["produced_by"]


def test_explain_groups_a_security_rule_with_its_family() -> None:
    _code, payload = _run(["--no-config", "explain", "SEC-SCOPE-BROAD", "--json"])
    assert payload["group"].startswith("Security")
    assert payload["documentation"] == "docs/check-rules.md"


def test_a_typo_suggests_a_security_rule() -> None:
    """The suggestion list only knew the breaking catalogue, so a misspelt
    security rule ended in a dead end."""
    buffer = io.StringIO()
    with (
        contextlib.redirect_stdout(buffer),
        contextlib.redirect_stderr(buffer),
        contextlib.suppress(SystemExit),
    ):
        main(["--no-config", "explain", "SEC-CORS-WILDCAR"])
    assert "SEC-CORS-WILDCARD" in buffer.getvalue()


# ------------------------------------------------------------------- docs


def test_the_generated_document_lists_every_rule() -> None:
    text = _DOC.read_text(encoding="utf-8")
    for rule_id in SECURITY_CATALOG:
        assert f"`{rule_id}`" in text, f"{rule_id} is missing from docs/check-rules.md"
    assert f"_{len(SECURITY_CATALOG)} check rules._" in text


def test_the_document_is_not_stale() -> None:
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, str(_ROOT / "scripts" / "generate_check_rules.py"), "--check"],
        capture_output=True,
        text=True,
        cwd=_ROOT,
    )
    assert result.returncode == 0, result.stderr


def test_the_document_says_profiles_do_not_reach_these_rules() -> None:
    """Reading `strict` as covering everything is the misunderstanding worth
    heading off: it acts on the breaking catalogue alone."""
    text = _DOC.read_text(encoding="utf-8")
    assert "not** covered by the severity profiles" in text
