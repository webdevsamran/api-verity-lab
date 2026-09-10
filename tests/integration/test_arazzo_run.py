"""An Arazzo description, imported and then actually run.

`tests/unit/test_arazzo.py` checks the conversion: what maps, what does not,
and that the export validates against the OpenAPI Initiative's own schema. None
of that sends a request. A description could convert perfectly and produce a
workflow that fails on contact with a server -- a path template nothing fills,
a status list that never matches, an extraction pointing at a field that is not
there -- and every unit test would still be green.

So this runs the bundled description end to end against the stateful mock built
from the contract it names.
"""

from __future__ import annotations

import pytest

from apiverity.mock import MockServer
from apiverity.specs.loader import detect_and_load
from apiverity.stateful.arazzo import read_arazzo
from apiverity.stateful.engine import WorkflowEngine

_FIXTURE = "fixtures/workflows/arazzo/users.arazzo.yaml"
_CONTRACT = "fixtures/apis/crud/openapi.yaml"
_INPUTS = {"user_name": "alice", "user_role": "user"}


@pytest.fixture
def workflow():
    return read_arazzo(_FIXTURE).workflows[0]


@pytest.fixture
def service():
    loaded, _findings, _plugin = detect_and_load(_CONTRACT)
    return loaded


def test_the_imported_description_passes_against_the_mock(workflow, service) -> None:
    with MockServer(service, port=0) as mock:
        result = WorkflowEngine(workflow, mock.base_url, _INPUTS).run()
    assert result.status == "pass", [s.violations for s in result.steps]
    assert [s.step for s in result.steps] == ["create", "read-back", "delete"]
    assert all(s.status == "pass" for s in result.steps)


def test_the_extraction_the_description_declared_actually_extracts(workflow, service) -> None:
    """`outputs: {user_id: $response.body#/id}` became `extract: {user_id:
    $.id}`. The two are the same shape, which is why the mapping is safe -- and
    why nothing would notice if it were wrong except a run."""
    with MockServer(service, port=0) as mock:
        result = WorkflowEngine(workflow, mock.base_url, _INPUTS).run()
    assert result.steps[0].extracted["user_id"]
    assert result.variables["user_id"] == result.steps[0].extracted["user_id"]


def test_the_renamed_path_placeholder_addresses_the_created_resource(workflow, service) -> None:
    """The contract declares `/users/{id}`; the import rewrote it to
    `/users/{user_id}` because that is the variable the value expression names.
    If the rename were wrong the request would go to a literal `/users/{id}`
    and the mock would answer 404, not 200."""
    with MockServer(service, port=0) as mock:
        result = WorkflowEngine(workflow, mock.base_url, _INPUTS).run()
    assert result.steps[1].actual_status == 200


def test_a_declared_input_that_is_not_supplied_stops_the_run(workflow) -> None:
    """`_substitute` leaves an unknown `{user_name}` exactly as written, so
    without this the POST body would carry a literal brace and the run would
    report whatever the server made of that."""
    with pytest.raises(ValueError, match="not supplied"):
        WorkflowEngine(workflow, "http://127.0.0.1:1", {"user_name": "alice"})


def test_supplied_inputs_reach_the_request_body(workflow, service) -> None:
    """`payload: {name: $inputs.user_name}` became `{name: "{user_name}"}`. The
    mock is stateful CRUD, so reading back what the workflow created says
    whether the input was substituted or sent as the literal `{user_name}`.

    The delete step is dropped for this run: the resource has to still exist
    for the question to be answerable.
    """
    import httpx

    workflow.steps = workflow.steps[:2]
    with MockServer(service, port=0) as mock:
        result = WorkflowEngine(
            workflow, mock.base_url, {"user_name": "zoe", "user_role": "user"}
        ).run()
        stored = httpx.get(mock.base_url + f"/users/{result.variables['user_id']}").json()
    assert result.status == "pass"
    assert stored["name"] == "zoe"
