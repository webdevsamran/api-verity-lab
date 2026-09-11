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

#: A rule id, in any of the families this catalogue covers.
#:
#: Matched against **string literals in the package**, found with `ast`, rather
#: than against `rule_id="..."` -- which is what this required until
#: `security/authz.py` emitted three ids from a dispatch table:
#:
#:     for method, payload, rule in (("GET", None, "AUTHZ-BOLA-READ"), ...):
#:         findings.append(Finding(rule_id=rule, ...))
#:
#: Those ids are produced by code that runs, and requiring one syntactic form
#: reported them as catalogued-and-dead. Docstrings are excluded, so a rule
#: merely *described* in prose still counts as unemitted -- which is the case
#: this test exists to catch.
#: A trailing hyphen makes it a *prefix*, not an id -- `platform.py` keeps a
#: table of them for `explain`'s grouping, and matching those would report a
#: dozen prefixes as rules nothing can explain.
_EMITTED = re.compile(
    r"^(?:SEC|LIFECYCLE|SEMANTIC|SLO|GOV|LINT|SUPPRESSION|CONFIG|AUTHZ|SDK|GUARD|FED"
    r"|COMPAT|PROTO|GQL)-[A-Z0-9-]*[A-Z0-9]$"
)


def _string_literals(source: str) -> set[str]:
    """Every string constant in a module except the docstrings."""
    import ast

    tree = ast.parse(source)
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = getattr(node, "body", [])
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                docstrings.add(id(body[0].value))
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    }


def _emitted_ids() -> set[str]:
    found: set[str] = set()
    for path in _PACKAGE.rglob("*.py"):
        if path.name in {
            "catalog.py",
            "check_catalog.py",
            "lifecycle_catalog.py",
            "lint_catalog.py",
            "authz_catalog.py",
            "gate_catalog.py",
            "policy_catalog.py",
            "semantic_catalog.py",
            "slo_catalog.py",
        }:
            continue
        found.update(
            literal
            for literal in _string_literals(path.read_text(encoding="utf-8"))
            if _EMITTED.match(literal)
        )
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


# ------------------------------------------------ emitted *and* reachable


def _reachable_modules() -> set[str]:
    """Every `apiverity.*` module reachable by import from the CLI.

    Walks `import` statements from `apiverity.cli.main` transitively. Static,
    like the scan above, and deliberately so: importing the world to find out
    what imports the world is a test that passes by having side effects.

    It over-approximates -- a module imported inside a function that is never
    called still counts -- which is the right direction for a guard. What it
    catches is the case that actually happened: a module nothing imports at
    all.
    """
    import ast

    seen: set[str] = set()
    queue = ["apiverity.cli.main", "apiverity.mcp.server"]
    while queue:
        name = queue.pop()
        if name in seen or not name.startswith("apiverity"):
            continue
        seen.add(name)
        path = _PACKAGE.parent / (name.replace(".", "/") + ".py")
        if not path.is_file():
            path = _PACKAGE.parent / name.replace(".", "/") / "__init__.py"
        if not path.is_file():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                queue.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.level:  # a relative import, resolved against this module
                    parent = name.rsplit(".", node.level)[0]
                    queue.append(f"{parent}.{node.module}")
                else:
                    queue.append(node.module)
                    queue.extend(f"{node.module}.{a.name}" for a in node.names)
    return seen


def _module_name(path: Path) -> str:
    relative = path.relative_to(_PACKAGE.parent).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def test_every_catalogued_rule_is_emitted_from_reachable_code() -> None:
    """The scan above cannot tell live code from dead code, and that gap was
    not hypothetical.

    `SEC-NO-AUTH-DECLARED`, `SEC-SECRET-IN-CONTRACT`, `SEC-SENSITIVE-FIELD`
    and `SEC-CORS-WILDCARD` were in the published catalogue, in
    `docs/check-rules.md`, and answerable by `apiverity explain` -- and the
    only code emitting them was `apiverity/security/packs.py`, a rule pack no
    command ever executed. So this tool said it checked for a credential
    committed into a contract, and could not produce that finding.

    `test_every_catalogued_security_rule_is_emitted_by_something` passed the
    whole time, because it greps the package for `rule_id="SEC-..."` and the
    dead module is in the package. This one asks the other half of the
    question: is the module that emits it reachable from an entry point?
    """
    reachable = _reachable_modules()
    orphaned: dict[str, str] = {}
    for path in _PACKAGE.rglob("*.py"):
        if path.name in {
            "catalog.py",
            "check_catalog.py",
            "lifecycle_catalog.py",
            "lint_catalog.py",
            "policy_catalog.py",
            "semantic_catalog.py",
            "slo_catalog.py",
        }:
            continue
        emitted = set(_EMITTED.findall(path.read_text(encoding="utf-8")))
        if not emitted:
            continue
        module = _module_name(path)
        if module in reachable:
            continue
        for rule in emitted:
            orphaned[rule] = module

    assert orphaned == {}, (
        "these rules are catalogued and emitted only from a module nothing imports: "
        f"{orphaned}. A rule that cannot run is a rule people configure, wait for, "
        "and trust."
    )


def test_the_reachability_walk_finds_something() -> None:
    """A walk that returned an empty set would make the test above pass for
    every module, including the dead ones -- which is the failure it exists to
    catch, in a new place."""
    reachable = _reachable_modules()
    assert "apiverity.security.checks" in reachable
    assert "apiverity.rules.breaking" in reachable
    assert len(reachable) > 20


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
