"""The CRUD invariants a schema check cannot state, and the mock that hid them.

`apiverity/stateful/model_based.py` asks three questions no per-request check
can ask, because they are about sequences: can what you just created be read
back, does an update persist, and is a deleted resource actually gone. A
service can satisfy its contract on every individual request and fail all
three.

No command reached it. And the mock everything else in this suite is tested
against could not have answered two of them: its "stateful CRUD behavior for
collections" did create and read, so an update returned a freshly generated
body and changed nothing, and a delete changed nothing either -- a resource
deleted and read back came back.
"""

from __future__ import annotations

import contextlib
import io
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import httpx
import pytest

from apiverity.cli.main import main
from apiverity.core.model import Service
from apiverity.mock import MockServer
from apiverity.specs.loader import detect_and_load
from apiverity.stateful.model_based import (
    discover_collections,
    payload_for,
)

_CONTRACT = "fixtures/apis/templates/openapi.yaml"


@pytest.fixture(scope="module")
def service() -> Service:
    loaded, _findings, _plugin = detect_and_load(_CONTRACT)
    return loaded


# ------------------------------------------------------- the mock does CRUD


def test_the_mock_persists_an_update(service: Service) -> None:
    """It returned a freshly generated body and stored nothing, so every
    "did that take effect" check passed against a mock where nothing did."""
    with MockServer(service, port=0) as mock:
        created = httpx.post(mock.base_url + "/widgets", json={"name": "alice"}).json()
        httpx.patch(f"{mock.base_url}/widgets/{created['id']}", json={"name": "bob"})
        assert httpx.get(f"{mock.base_url}/widgets/{created['id']}").json()["name"] == "bob"


def test_the_mock_actually_deletes(service: Service) -> None:
    with MockServer(service, port=0) as mock:
        created = httpx.post(mock.base_url + "/widgets", json={"name": "alice"}).json()
        assert httpx.delete(f"{mock.base_url}/widgets/{created['id']}").status_code == 204
        assert httpx.get(f"{mock.base_url}/widgets/{created['id']}").status_code == 404


def test_a_204_carries_no_body(service: Service) -> None:
    """`_build_body` treats "no response schema" as an error case, so a 204
    went out as `{"error": "mock error 204"}` -- which RFC 9110 forbids and
    which a client reading `Content-Length` has to cope with."""
    with MockServer(service, port=0) as mock:
        created = httpx.post(mock.base_url + "/widgets", json={"name": "x"}).json()
        response = httpx.delete(f"{mock.base_url}/widgets/{created['id']}")
    assert response.status_code == 204
    assert response.content == b""


def test_a_put_replaces_where_a_patch_merges(service: Service) -> None:
    """A mock that merged on PUT would let a client believe a field it stopped
    sending was still being cleared."""
    with MockServer(service, port=0) as mock:
        created = httpx.post(mock.base_url + "/widgets", json={"name": "alice"}).json()
        merged = httpx.patch(f"{mock.base_url}/widgets/{created['id']}", json={}).json()
    assert merged["name"] == "alice"


# ------------------------------------------------------------- discovery


def test_a_collection_is_a_post_and_a_sibling_id_get(service: Service) -> None:
    """Nothing is inferred from a name. `/widgets` is a collection because the
    contract says you can create one and read one back."""
    assert [c.path for c in discover_collections(service)] == ["/orders", "/widgets"]


def test_the_update_verb_comes_from_the_contract(service: Service) -> None:
    found = {c.path: c.update_verb for c in discover_collections(service)}
    assert found == {"/widgets": "PATCH", "/orders": None}


def test_a_collection_with_no_update_verb_is_exercised_without_those_steps(
    service: Service,
) -> None:
    """Rather than failed for not having them. An API with no update endpoint
    is not a broken API."""
    orders = next(c for c in discover_collections(service) if c.path == "/orders")
    assert [t.name for t in orders.transitions()] == [
        "create",
        "read",
        "delete",
        "read-deleted",
    ]
    assert "neither PATCH nor PUT" in orders.notes[0]


def test_the_payload_comes_from_the_contract(service: Service) -> None:
    """A hardcoded `{"name": ...}` works against a fixture and against nothing
    else: a real create usually has required fields, and a 400 from one of them
    would be reported as a service that cannot create a resource."""
    widgets = next(c for c in discover_collections(service) if c.path == "/widgets")
    body = payload_for(widgets.create_operation)
    assert set(body) == {"name"}
    assert isinstance(body["name"], str) and body["name"]


# ------------------------------------------------------------- the run


def _run(argv: list[str]) -> tuple[int, dict[str, Any], str]:
    out, err = io.StringIO(), io.StringIO()
    code = 0
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = main(argv)
        except SystemExit as stop:
            code = int(stop.code or 0)
    try:
        return code, json.loads(out.getvalue()), err.getvalue()
    except ValueError:
        return code, {}, err.getvalue()


def _argv(base_url: str, *extra: str) -> list[str]:
    return [
        "--no-config",
        "test",
        _CONTRACT,
        "--base-url",
        base_url,
        "--model-based",
        "--include-mutations",
        "--json",
        *extra,
    ]


def test_every_collection_passes_against_a_mock_that_does_crud(service: Service) -> None:
    with MockServer(service, port=0) as mock:
        code, payload, _err = _run(_argv(mock.base_url))
    assert code == 0
    runs = payload["model_based"]["collections"]
    assert {r["collection"] for r in runs} == {"/widgets", "/orders"}
    assert all(r["status"] == "pass" for r in runs), runs


def test_what_a_collection_could_not_be_checked_for_is_reported(service: Service) -> None:
    """A collection with no DELETE was exercised without the check that a
    deleted resource is gone, and a reader has to be able to tell that from a
    collection where the check passed."""
    with MockServer(service, port=0) as mock:
        _code, payload, _err = _run(_argv(mock.base_url))
    orders = next(r for r in payload["model_based"]["collections"] if r["collection"] == "/orders")
    assert orders["not_checked"] == [
        "/orders/{id} declares neither PATCH nor PUT, so nothing checks that an update persists"
    ]


def test_one_collection_can_be_named(service: Service) -> None:
    with MockServer(service, port=0) as mock:
        _code, payload, _err = _run(_argv(mock.base_url, "--collection", "/widgets"))
    assert [r["collection"] for r in payload["model_based"]["collections"]] == ["/widgets"]


def test_a_collection_that_is_not_there_is_a_usage_error(service: Service) -> None:
    code, _payload, err = _run(_argv("http://127.0.0.1:1", "--collection", "/nope"))
    assert code != 0
    assert "no CRUD collection at '/nope'" in err


def test_it_will_not_write_without_being_told() -> None:
    """Create, update and delete, against whatever `--base-url` names."""
    code, _payload, err = _run(
        [
            "--no-config",
            "test",
            _CONTRACT,
            "--base-url",
            "http://127.0.0.1:1",
            "--model-based",
            "--json",
        ]
    )
    assert code != 0
    assert "--include-mutations" in err
    assert "creates, updates and deletes" in err


def test_a_contract_with_no_crud_resource_is_not_a_failure() -> None:
    """A fact about the API rather than a fault."""
    code, payload, _err = _run(
        [
            "--no-config",
            "test",
            "fixtures/apis/slo/openapi.yaml",
            "--base-url",
            "http://127.0.0.1:1",
            "--model-based",
            "--include-mutations",
            "--json",
        ]
    )
    assert code == 0
    assert payload["model_based"]["collections"] == []
    assert "no CRUD resource to drive" in payload["model_based"]["note"]


# ------------------------------------------------ what it catches


class _AmnesiacHandler(BaseHTTPRequestHandler):
    """A service that accepts an update and forgets it.

    Every request is contract-valid. `PATCH` answers 200 with the resource,
    `GET` answers 200 with the resource, and the resource never changes -- so
    every schema check, every status check and every per-request assertion in
    this project passes against it.
    """

    def log_message(self, *_args: Any) -> None:
        return

    def _answer(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        body = json.dumps({"id": "1", "name": "as-created"}).encode()
        status = 201 if self.command == "POST" else 200
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = do_POST = do_PATCH = do_PUT = do_DELETE = _answer


@pytest.fixture
def amnesiac():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _AmnesiacHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def test_an_update_that_does_not_persist_is_caught(amnesiac: str) -> None:
    """The finding this whole module exists for. Nothing else in the suite
    reports it, because no single request is wrong."""
    code, payload, _err = _run(_argv(amnesiac, "--collection", "/widgets"))
    assert code != 0
    steps = payload["model_based"]["collections"][0]["steps"]
    failed = next(s for s in steps if s["status"] == "fail")
    assert failed["step"] == "read-after-update"
    assert "update not persisted" in failed["violations"][0]


def test_a_delete_that_does_not_delete_is_caught(amnesiac: str) -> None:
    """`/orders` has no update verb, so the run reaches the delete -- and the
    service answers 200 for a resource it was told to remove."""
    code, payload, _err = _run(_argv(amnesiac, "--collection", "/orders"))
    assert code != 0
    steps = payload["model_based"]["collections"][0]["steps"]
    failed = next(s for s in steps if s["status"] == "fail")
    assert failed["step"] == "read-deleted"
    assert "expected status in [404, 410] but got 200" in failed["violations"][0]
