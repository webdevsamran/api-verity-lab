"""The playground's manifest: what to load, and which wheel to install.

The browser playground runs this project's real engine under Pyodide. Three
numbers have to agree for that to work, and none of them is visible from the
others:

* the **wheel filename**, which is `api_verity_lab-<version>-py3-none-any.whl`
  and changes on every version bump;
* the **Pyodide release**, pinned rather than floating, because a new Pyodide
  ships a different Python and a different pydantic;
* the **packages preloaded from Pyodide's own distribution**, which is what
  lets the install skip PyPI entirely.

A version bump with a hand-written manifest is a 404 on the wheel and a
playground that spins forever. So the manifest is generated, and `--check` runs
in CI.

    python scripts/generate_playground.py            # rewrite the manifest
    python scripts/generate_playground.py --check    # verify, exit 1 on drift
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "docs" / "playground" / "manifest.json"

sys.path.insert(0, str(ROOT))

#: Pinned, not `latest`. Pyodide releases change the bundled Python and the
#: bundled pydantic, and a playground that silently moved to an incompatible
#: pair would fail for visitors and for nobody running CI.
#:
#: 0.28.3 bundles pydantic 2.10.6, PyYAML 6.0.2 and packaging 24.2 -- which is
#: every runtime dependency the analysis path actually imports, so nothing is
#: fetched from PyPI at all.
PYODIDE = "0.28.3"

#: Fetched from Pyodide's own distribution rather than PyPI.
PRELOAD = ["micropip", "pydantic", "pyyaml", "packaging"]

#: Fetched from PyPI by micropip, because Pyodide does not bundle them.
#:
#: `graphql-core` is the `graphql` extra, and without it the GraphQL plugin
#: cannot even *recognise* an SDL document -- so a pasted schema came back as
#: "not an API contract in any recognized format", which is both wrong and the
#: least helpful thing this page could say. Pure Python, one wheel.
INSTALL = ["graphql-core>=3.2,<4.0"]

#: What the wheel's own metadata asks for and the playground does not install.
#:
#: `httpx` and `flask` are declared dependencies of the package and are imported
#: by exactly nothing on the path this page exercises -- every command that
#: needs them imports them inside the function that uses them. Installing them
#: would add a dozen wheels and several seconds to a first load for code the
#: page cannot reach.
#:
#: The cost of the shortcut is stated rather than hidden: `micropip.install`
#: runs with `deps=False`, so a future import of something new fails at runtime
#: instead of at install time. `app.js` catches that and names the missing
#: module, which is the difference between a bug report and a blank page.
SKIPPED = ["httpx", "flask"]


def manifest() -> dict[str, object]:
    from apiverity import __version__

    return {
        "_generated_by": "scripts/generate_playground.py",
        "version": __version__,
        "wheel": f"api_verity_lab-{__version__}-py3-none-any.whl",
        "pyodide": PYODIDE,
        "preload": PRELOAD,
        "install": INSTALL,
        "skipped_dependencies": SKIPPED,
    }


def render() -> str:
    return json.dumps(manifest(), indent=2) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    rendered = render()
    if args.check:
        if not MANIFEST.exists() or MANIFEST.read_text(encoding="utf-8") != rendered:
            print(
                "error: docs/playground/manifest.json no longer matches the package. "
                "Run: python scripts/generate_playground.py",
                file=sys.stderr,
            )
            return 1
        print(f"ok     playground manifest ({manifest()['wheel']}, pyodide {PYODIDE})")
        return 0

    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(rendered, encoding="utf-8", newline="\n")
    print(f"wrote  {MANIFEST.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
