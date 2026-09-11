"""Reading the contract out of a running application object.

Most frameworks generate an OpenAPI document. The usual workflow is to export
it to a file and check the file — and the file is the thing that goes stale.
A service whose handlers changed and whose committed `openapi.yaml` did not is
a contract that passes every check and describes something that no longer
exists.

`--from-app myapp:app` reads the document the application itself produces, so
there is nothing to keep in sync.

## What it works with, stated as a shape rather than a framework

Any object with an `openapi()` method returning a dict. That is FastAPI's, and
it is also every Starlette-derived framework's, `apiflask`'s, and anything else
that adopted the convention.

The alternative -- `isinstance(app, FastAPI)` -- would import FastAPI to check,
make it a dependency of a tool that does not need one, and refuse an
application that produces exactly the right document because its class is
somebody else's.

`app.openapi` as a plain dict attribute is accepted too: a few frameworks
expose the document rather than a method to build it.

## Importing an application executes its module

That is the whole cost of this feature, and it is stated rather than buried.
`--from-app` imports the module named, which runs its top-level code:
decorators, database connections, whatever the application does at import.

It is the same cost `uvicorn myapp:app` has, so a team already running the
application this way is not taking on a new risk. A team pointing it at
somebody else's code is, and the docs say so.

## What it does not do

Start the application, bind a port, or send a request. The document is built
in-process from the route table. `drift --base-url` is the command for asking
what a *running* service does, and conflating the two would mean a check that
claims to have observed something it constructed.
"""

from __future__ import annotations

import copy
import importlib
import sys
from pathlib import Path
from typing import Any

#: The separator in `module:attribute`, matching what uvicorn and gunicorn use.
SEPARATOR = ":"


class AppImportError(Exception):
    """The application could not be reached, with the reason."""


def _resolve(target: str) -> Any:
    if SEPARATOR not in target:
        raise AppImportError(
            f"'{target}' is not `module:attribute`. Give it the way uvicorn does -- "
            "`myapp.main:app`"
        )
    module_name, _, attribute = target.partition(SEPARATOR)
    if not module_name or not attribute:
        raise AppImportError(f"'{target}' is missing a module or an attribute name")

    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise AppImportError(
            f"could not import '{module_name}': {exc}. The module has to be on the path "
            "-- run from the project root, or set PYTHONPATH"
        ) from exc
    except Exception as exc:
        # Importing an application runs its module. A failure here is the
        # application's, and saying so is more useful than a traceback that
        # looks like this tool broke.
        raise AppImportError(
            f"importing '{module_name}' raised {type(exc).__name__}: {exc}. "
            "Importing an application runs its top-level code"
        ) from exc

    try:
        return getattr(module, attribute)
    except AttributeError as exc:
        available = [n for n in dir(module) if not n.startswith("_")][:10]
        raise AppImportError(
            f"'{module_name}' has no attribute '{attribute}'. It does have: {', '.join(available)}"
        ) from exc


def document_of(app: Any) -> dict[str, Any]:
    """The OpenAPI document an application object produces."""
    producer = getattr(app, "openapi", None)
    if producer is None:
        raise AppImportError(
            f"{type(app).__name__} has no `openapi` attribute, so it does not produce a "
            "document this can read. Export the contract to a file and pass that instead"
        )
    document = producer() if callable(producer) else producer
    if not isinstance(document, dict):
        raise AppImportError(
            f"{type(app).__name__}.openapi returned {type(document).__name__}, not a document"
        )
    if "openapi" not in document and "swagger" not in document:
        raise AppImportError(
            "the object returned a dict that declares neither `openapi` nor `swagger`, "
            "so it is not a contract"
        )
    # Copied, because frameworks cache. FastAPI builds the document once and
    # returns the same object on every call, so a caller who edited this would
    # be editing the running application's published schema -- and the edit
    # would be invisible, since the next read returns the object that was
    # edited.
    return copy.deepcopy(document)


def load_app(target: str, *, root: str | Path | None = None) -> tuple[dict[str, Any], str]:
    """`(document, label)` for `module:attribute`.

    `root` is prepended to `sys.path` for the import and removed afterwards, so
    running from elsewhere does not require the caller to set `PYTHONPATH` --
    and so this does not leave the path modified for whatever runs next.
    """
    added = None
    if root is not None:
        added = str(Path(root).resolve())
        if added not in sys.path:
            sys.path.insert(0, added)
        else:
            added = None
    try:
        app = _resolve(target)
        return document_of(app), target
    finally:
        if added is not None:
            sys.path.remove(added)


def write_document(document: dict[str, Any], path: str | Path) -> Path:
    """Write the document out, for a workflow that wants the file after all."""
    import json

    target = Path(path)
    if str(target.parent) not in ("", "."):
        target.parent.mkdir(parents=True, exist_ok=True)
    if target.suffix in (".yaml", ".yml"):
        import yaml

        body = yaml.safe_dump(document, sort_keys=False, allow_unicode=True)
    else:
        body = json.dumps(document, indent=2) + "\n"
    target.write_text(body, encoding="utf-8", newline="\n")
    return target


__all__ = ["SEPARATOR", "AppImportError", "document_of", "load_app", "write_document"]
