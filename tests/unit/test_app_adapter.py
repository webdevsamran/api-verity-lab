"""Reading the contract out of a real application object.

The point of this module is that the document comes from a framework rather
than from a fixture file. A test that hand-wrote a dict and passed it to
`document_of` would prove the dict was a dict.

`fastapi` is in the `dev` extra for the same reason `graphql-core` and `pyjwt`
are: a suite that silently skips its coverage of a feature is indistinguishable
from one that passes it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import ClassVar

import pytest

from apiverity.specs.app import AppImportError, document_of, load_app, write_document

pytest.importorskip("fastapi", reason="the `dev` extra installs it")

#: A small application with two operations, a path parameter, a response model
#: and a deprecation -- enough that the document it produces is worth reading.
APP_SOURCE = textwrap.dedent(
    """
    from fastapi import FastAPI
    from pydantic import BaseModel

    app = FastAPI(title="Orders", version="2.1.0")
    not_an_app = object()


    class Order(BaseModel):
        id: str
        total_cents: int


    @app.get("/orders/{order_id}", response_model=Order)
    def get_order(order_id: str) -> Order:
        return Order(id=order_id, total_cents=0)


    @app.post("/orders", response_model=Order, deprecated=True)
    def create_order(order: Order) -> Order:
        return order
    """
)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "orders_app.py").write_text(APP_SOURCE, encoding="utf-8")
    return tmp_path


def _document(project: Path) -> dict:
    document, _ = load_app("orders_app:app", root=project)
    return document


def test_the_document_comes_from_the_application(project: Path) -> None:
    document = _document(project)
    assert document["info"] == {"title": "Orders", "version": "2.1.0"}
    assert sorted(document["paths"]) == ["/orders", "/orders/{order_id}"]
    assert document["paths"]["/orders"]["post"]["deprecated"] is True


def test_the_document_loads_through_the_ordinary_loader(project: Path, tmp_path: Path) -> None:
    """Not a parallel model. Whatever the application produces has to survive
    the same parser every committed contract goes through, or the adapter is a
    second way into the engine that can disagree with the first."""
    from apiverity.specs.loader import detect_and_load

    path = write_document(_document(project), tmp_path / "out" / "openapi.json")
    service, _, plugin = detect_and_load(str(path))
    assert plugin.protocol().value == "openapi"
    assert service.title == "Orders"
    assert {op.method.upper() + " " + op.path for op in service.operations} == {
        "GET /orders/{order_id}",
        "POST /orders",
    }


def test_sys_path_is_left_the_way_it_was_found(project: Path) -> None:
    """`root` is prepended for the import. A tool that left it there would
    change what every later import in the process resolves to."""
    before = list(sys.path)
    load_app("orders_app:app", root=project)
    assert sys.path == before


def test_sys_path_is_restored_even_when_the_import_fails(tmp_path: Path) -> None:
    before = list(sys.path)
    with pytest.raises(AppImportError):
        load_app("no_such_module_anywhere:app", root=tmp_path)
    assert sys.path == before


def test_an_object_that_is_not_an_application_is_named_as_such(project: Path) -> None:
    with pytest.raises(AppImportError, match="no `openapi` attribute"):
        load_app("orders_app:not_an_app", root=project)


def test_a_missing_attribute_says_what_the_module_does_have(project: Path) -> None:
    with pytest.raises(AppImportError) as exc:
        load_app("orders_app:application", root=project)
    assert "orders_app" in str(exc.value)
    # The useful half of the message: the name that was meant is usually in
    # this list.
    assert "app" in str(exc.value)


@pytest.mark.parametrize("target", ["orders_app", ":app", "orders_app:"])
def test_a_target_that_is_not_module_colon_attribute_is_refused(target: str) -> None:
    with pytest.raises(AppImportError):
        load_app(target)


def test_the_returned_document_is_not_the_applications_own(project: Path) -> None:
    """FastAPI caches the document it builds and hands back the same object
    every time. A caller who edited what this returned would be editing the
    running application's published schema -- and the edit would be invisible,
    because the next read returns the object that was edited."""
    first = _document(project)
    first["paths"].pop("/orders")
    assert "/orders" in _document(project)["paths"]


def test_a_dict_that_is_not_a_contract_is_refused() -> None:
    class Bare:
        def openapi(self) -> dict:
            return {"paths": {}}

    with pytest.raises(AppImportError, match="neither `openapi` nor `swagger`"):
        document_of(Bare())


def test_openapi_as_a_plain_attribute_is_accepted() -> None:
    """Some frameworks expose the document rather than a method to build it,
    and refusing those would be refusing a correct contract over its shape."""

    class Exposed:
        openapi: ClassVar[dict] = {
            "openapi": "3.1.0",
            "info": {"title": "t", "version": "1"},
            "paths": {},
        }

    assert document_of(Exposed())["info"]["title"] == "t"


def test_yaml_is_written_when_the_suffix_asks_for_it(project: Path, tmp_path: Path) -> None:
    import yaml

    path = write_document(_document(project), tmp_path / "openapi.yaml")
    assert yaml.safe_load(path.read_text(encoding="utf-8"))["info"]["title"] == "Orders"


# -- the command ---------------------------------------------------------


def _run(project: Path, *args: str) -> subprocess.CompletedProcess[str]:
    # `cwd` is the point of the command -- the application is imported relative
    # to it -- so these run outside the repository. Which means the coverage
    # pytest-cov starts in the subprocess cannot find `pyproject.toml`, falls
    # back to statement coverage, and the combine step then refuses to merge
    # statement data into the parent's branch data. Naming the config file
    # keeps the two the same shape.
    env = dict(
        os.environ, COVERAGE_RCFILE=str(Path(__file__).resolve().parents[2] / "pyproject.toml")
    )
    return subprocess.run(
        [sys.executable, "-m", "apiverity.cli.main", "app", *args],
        capture_output=True,
        text=True,
        cwd=project,
        env=env,
    )


def test_the_command_reports_the_applications_operations(project: Path) -> None:
    result = _run(project, "orders_app:app", "--json")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["app"] == "orders_app:app"
    assert payload["operation_count"] == 2
    assert payload["title"] == "Orders"
    # The contract that was checked is identified by its hash, because the
    # document it was built from has no path of its own.
    assert payload["contract_hash"] != "0" * 64


def test_the_artifact_satisfies_the_published_schema(project: Path) -> None:
    """`scripts/validate_result_artifacts.py` holds every other command to
    `result-v1`, and it cannot hold this one: it is a standalone script and
    running `app` would make FastAPI a dependency of it. So the check happens
    here, where a real application is already in hand -- an allowed `command`
    value in the enum that nothing ever emits proves nothing."""
    from jsonschema import Draft202012Validator

    root = Path(__file__).resolve().parents[2]
    schema = json.loads((root / "schemas" / "result-v1.schema.json").read_text(encoding="utf-8"))

    write_document(_document(project), project / "openapi.json")
    result = _run(project, "orders_app:app", "--against", "openapi.json", "--json")
    errors = sorted(
        Draft202012Validator(schema).iter_errors(json.loads(result.stdout)),
        key=lambda e: list(e.path),
    )
    assert not errors, [f"{list(e.path)}: {e.message}" for e in errors]


def test_a_committed_contract_that_matches_the_application_passes(project: Path) -> None:
    write_document(_document(project), project / "openapi.json")
    result = _run(project, "orders_app:app", "--against", "openapi.json", "--json")
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["committed"]["in_sync"] is True
    assert payload["committed"]["changes"] == 0


def test_a_stale_committed_contract_fails_the_run(project: Path) -> None:
    """The whole point. The file says the API has one operation; the
    application serves two, and nothing else in the toolchain would notice."""
    document = _document(project)
    document["paths"].pop("/orders")
    write_document(document, project / "stale.json")

    result = _run(project, "orders_app:app", "--against", "stale.json", "--json")
    assert result.returncode == 1, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["committed"]["in_sync"] is False
    assert payload["committed"]["changes"] >= 1


def test_a_stale_file_fails_even_when_the_difference_is_additive(project: Path) -> None:
    """An added operation breaks nobody. The file is still wrong, and a command
    that passed here would only catch the staleness that happened to be
    breaking -- which is the minority of it."""
    document = _document(project)
    document["paths"].pop("/orders")
    write_document(document, project / "stale.json")

    result = _run(project, "orders_app:app", "--against", "stale.json", "--json")
    payload = json.loads(result.stdout)
    breaking = [f for f in payload["committed"]["findings"] if f["severity"] == "ERROR"]
    assert not breaking, "an added operation is not a breaking change"
    assert result.returncode == 1


def test_the_document_can_be_written_out(project: Path) -> None:
    result = _run(project, "orders_app:app", "-o", "generated.json", "--json")
    assert result.returncode == 0, result.stderr
    written = json.loads((project / "generated.json").read_text(encoding="utf-8"))
    assert written["info"]["title"] == "Orders"
    assert json.loads(result.stdout)["written"].endswith("generated.json")


def test_an_unimportable_target_exits_usage_rather_than_traceback(project: Path) -> None:
    result = _run(project, "nope_not_here:app", "--json")
    assert result.returncode == 2
    assert "could not import 'nope_not_here'" in result.stderr
    assert "Traceback" not in result.stderr


def test_an_application_that_raises_at_import_says_whose_fault_it_is(tmp_path: Path) -> None:
    (tmp_path / "boom.py").write_text("raise RuntimeError('no database')\n", encoding="utf-8")
    result = _run(tmp_path, "boom:app", "--json")
    assert result.returncode == 2
    assert "RuntimeError: no database" in result.stderr
    # Importing an application runs it, and a reader who does not know that
    # reads this as the tool crashing.
    assert "runs its top-level code" in result.stderr
