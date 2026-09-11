"""The browser playground, checked without a browser.

Nothing here launches Pyodide. What it checks is the two things that would make
the page wrong while looking fine, and both are invisible to a reader:

**The Python in `app.js` is the page's only logic, and nothing else runs it.**
A renamed function in `apiverity.diff` would leave the page raising an
`ImportError` in somebody's browser and passing every test here. So the
embedded snippet is extracted and executed against the real engine, with the
page's own sample contracts.

**`micropip.install(deps=False)` is only safe while the analysis path imports
nothing outside the four packages the page loads.** Add an `httpx` import to
`specs/loader.py` and the playground breaks for every visitor, with nothing in
this repository failing. That invariant is measured here by importing the path
in a fresh interpreter and looking at what came in with it.

The page was driven in a real browser during development — OpenAPI, Swagger
2.0, AsyncAPI, GraphQL SDL and an MCP manifest each produced findings, and a
malformed document produced the parser's own complaint rather than a traceback.
That is not something CI reproduces, and the docs say so rather than implying
otherwise.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_APP = _ROOT / "docs" / "playground" / "app.js"
_CSS = _ROOT / "docs" / "playground" / "app.css"
_PAGE = _ROOT / "docs" / "playground.md"
_MANIFEST = _ROOT / "docs" / "playground" / "manifest.json"
_SCRIPT = _ROOT / "scripts" / "generate_playground.py"

#: What the page installs, plus the standard library. The analysis path may
#: import from these and nothing else, because `deps=False` means anything else
#: is simply absent in the browser.
AVAILABLE = {
    "pydantic",
    "pydantic_core",
    "yaml",
    "packaging",
    "graphql",
    # Pulled in by pydantic itself, and therefore present wherever pydantic is.
    "annotated_types",
    "typing_extensions",
    "typing_inspection",
    "apiverity",
}


def _template(name: str) -> str:
    """One of `app.js`'s backtick template literals, by variable name."""
    source = _APP.read_text(encoding="utf-8")
    match = re.search(rf"const {name} = (?:String\.raw)?`(.*?)`;", source, re.S)
    assert match, f"{name} is no longer a template literal in app.js"
    return match.group(1)


def _manifest() -> dict:
    return json.loads(_MANIFEST.read_text(encoding="utf-8"))


# -- the embedded analysis ------------------------------------------------


def test_the_pages_python_runs_against_the_real_engine() -> None:
    """The page's only logic, executed. A renamed function in
    `apiverity.diff` would otherwise leave an ImportError in somebody's browser
    and a green test suite here."""
    namespace: dict = {}
    exec(_template("ANALYSIS"), namespace)

    raw = namespace["apiverity_compare"](_template("SAMPLE_OLD"), _template("SAMPLE_NEW"))
    result = json.loads(raw)

    assert result["protocol"] == "openapi"
    assert result["old_version"] == "1.2.0"
    assert result["new_version"] == "2.0.0"
    assert result["change_count"] > 0
    assert result["breaking"], "the sample is meant to demonstrate breaking changes"


def test_the_sample_demonstrates_the_rules_it_is_there_to_demonstrate() -> None:
    """A sample that produced nothing would leave a first-time visitor with an
    empty result and no way to tell whether the tool works."""
    namespace: dict = {}
    exec(_template("ANALYSIS"), namespace)
    result = json.loads(
        namespace["apiverity_compare"](_template("SAMPLE_OLD"), _template("SAMPLE_NEW"))
    )
    codes = {f["rule_id"] for f in result["breaking"]}
    assert "BRK-OP-REMOVED" in codes
    assert any(code.startswith("BRK-RESP-") for code in codes)
    assert all(f["severity"] in {"ERROR", "WARN", "INFO"} for f in result["breaking"])


def test_a_document_that_will_not_parse_says_which_pane_and_why() -> None:
    """A traceback is the wrong answer to a half-typed contract. The reader
    knows they are mid-edit; what they need is the parser's complaint."""
    namespace: dict = {}
    exec(_template("ANALYSIS"), namespace)
    result = json.loads(
        namespace["apiverity_compare"]("openapi: 3.0.0\npaths:\n  - [unclosed", "{}")
    )
    assert result["error"]["side"] == "old"
    assert result["error"]["type"]
    assert result["error"]["message"]


# -- the dependency invariant ---------------------------------------------


def test_the_analysis_path_imports_nothing_the_playground_does_not_install() -> None:
    """`deps=False` is safe only while this holds. An `httpx` import added to
    the loader would break the page for every visitor, with nothing in this
    repository failing -- so it fails here instead.

    Measured in a fresh interpreter: this process has the whole test suite's
    imports in `sys.modules` already, and asking it would prove nothing.
    """
    probe = (
        "import sys, json;"
        "before=set(sys.modules);"
        "import apiverity.specs.loader, apiverity.diff.engine,"
        " apiverity.rules.breaking, apiverity.security;"
        "print(json.dumps(sorted({m.split('.')[0] for m in set(sys.modules)-before})))"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, cwd=_ROOT, check=True
    )
    pulled = json.loads(result.stdout)

    # Standard library and private extension modules are present in the
    # browser too; only third-party top-levels matter here.
    third_party = {
        name
        for name in pulled
        if not name.startswith("_")
        and name not in sys.stdlib_module_names
        and name != "cython_runtime"
    }
    assert third_party <= AVAILABLE, (
        f"the analysis path imports {sorted(third_party - AVAILABLE)}, which the playground "
        "does not install. Either add it to the manifest's `install` list or keep the import "
        "inside the function that needs it"
    )


def test_everything_the_page_installs_is_something_the_path_could_need() -> None:
    """The other direction. A package installed and never imported is seconds
    added to every visitor's first load for nothing."""
    manifest = _manifest()
    named = set(manifest["preload"]) | {
        re.split(r"[<>=!~]", spec)[0] for spec in manifest.get("install", [])
    }
    # `micropip` is the installer itself.
    assert named - {"micropip"} <= {"pydantic", "pyyaml", "packaging", "graphql-core"}


def test_the_skipped_dependencies_really_are_declared_by_the_package() -> None:
    """The manifest claims `httpx` and `flask` are declared and unreachable. If
    one stopped being declared, the note would be explaining a decision nobody
    is making."""
    pyproject = (_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    for name in _manifest()["skipped_dependencies"]:
        assert re.search(rf'"{name}[><=~]', pyproject, re.I), (
            f"{name} is listed as skipped and is not a declared dependency"
        )


# -- the manifest ---------------------------------------------------------


def test_the_manifest_matches_the_package() -> None:
    """A version bump with a stale manifest is a 404 on the wheel and a
    playground that spins forever."""
    result = subprocess.run(
        [sys.executable, str(_SCRIPT), "--check"], capture_output=True, text=True, cwd=_ROOT
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_wheel_name_is_the_one_the_build_produces() -> None:
    from apiverity import __version__

    assert _manifest()["wheel"] == f"api_verity_lab-{__version__}-py3-none-any.whl"


def test_pyodide_is_pinned() -> None:
    """`latest` would move the bundled Python and the bundled pydantic under
    the page, for visitors, with nobody here running anything."""
    pyodide = _manifest()["pyodide"]
    assert re.fullmatch(r"\d+\.\d+\.\d+", pyodide), f"{pyodide!r} is not a pinned release"


def test_the_page_loads_pyodide_from_the_pinned_version() -> None:
    source = _APP.read_text(encoding="utf-8")
    assert "manifest.pyodide" in source
    assert "cdn.jsdelivr.net/pyodide" in source
    # And never a floating tag.
    assert "/latest/" not in source


def test_python_is_loaded_on_the_first_run_not_on_page_load() -> None:
    """A docs page that pulls tens of megabytes because somebody scrolled past
    it is a docs page that is slow for everybody."""
    source = _APP.read_text(encoding="utf-8")
    assert "loading ??= boot()" in source or "loading ?? = boot()" in source


# -- the page -------------------------------------------------------------


@pytest.mark.parametrize("element", ["pg-old", "pg-new", "pg-run", "pg-output", "pg-status"])
def test_the_page_has_the_elements_the_script_reaches_for(element: str) -> None:
    """The script and the markup live in different files, and a renamed id is
    a `null` dereference nobody sees until the page is open."""
    assert f'id="{element}"' in _PAGE.read_text(encoding="utf-8")


def test_the_page_says_nothing_is_uploaded() -> None:
    """It is the first question a reader has about pasting a contract into a
    web page, and it is the strongest thing about this one."""
    page = _PAGE.read_text(encoding="utf-8").lower()
    assert "no server" in page or "nothing leaves this tab" in page


def test_the_page_says_what_it_cannot_do() -> None:
    """A playground that implied it could probe your staging environment would
    be claiming an answer it cannot have."""
    page = _PAGE.read_text(encoding="utf-8")
    assert "drift --base-url" in page


def test_the_styles_follow_the_docs_theme() -> None:
    """A widget that stays white in a dark docs site is the tell that it was
    bolted on."""
    css = _CSS.read_text(encoding="utf-8")
    assert "--md-default-fg-color" in css
    assert "--md-code-bg-color" in css


def test_the_built_wheel_is_not_committed() -> None:
    """It is a build product, produced by the docs workflow. A committed wheel
    is a binary in every diff and the wrong bytes the moment the code changes."""
    ignored = (_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "api_verity_lab-*.whl" in ignored
    assert not list((_ROOT / "docs" / "playground").glob("*.whl"))


def test_the_docs_workflow_builds_the_wheel_and_watches_the_code() -> None:
    """The playground runs the wheel, so a docs build that did not rebuild it
    would publish a page running whatever the code was the last time a markdown
    file changed."""
    workflow = (_ROOT / ".github/workflows/docs.yml").read_text(encoding="utf-8")
    assert "playground" in workflow
    assert "apiverity/**" in workflow, (
        "the docs workflow does not rerun when the code changes, so the playground would "
        "serve a stale wheel"
    )
