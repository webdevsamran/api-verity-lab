"""Arazzo in and out, and what neither direction carries.

Two claims are under test and they are different claims.

The first is *structural*: what this project writes is valid Arazzo 1.1.0. That
is checked against the OpenAPI Initiative's own published JSON Schema, vendored
under `schemas/vendor/`, not against anything written here.

The second is *behavioural*: what does not survive the conversion is reported.
An importer that quietly dropped a `retry`, a `goto`, or an entire step would
hand back a workflow that looks whole and runs differently from the one
somebody wrote -- so every construct with no equivalent has a test naming it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from apiverity.specs.loader import detect_and_load
from apiverity.stateful.arazzo import (
    ARAZZO_VERSION,
    SCHEMA_ITERATION,
    from_arazzo,
    is_arazzo,
    read_arazzo,
    to_arazzo,
)
from apiverity.stateful.engine import load_workflow_manifest

_ROOT = Path(__file__).resolve().parents[2]
_FIXTURE = _ROOT / "fixtures" / "workflows" / "arazzo" / "users.arazzo.yaml"
_MANIFEST = _ROOT / "fixtures" / "workflows" / "crud-lifecycle.yaml"
_CONTRACT = _ROOT / "fixtures" / "apis" / "crud" / "openapi.yaml"
_SCHEMA = _ROOT / "schemas" / "vendor" / "arazzo-1.1-2026-04-15.schema.json"
_VENDOR_README = _ROOT / "schemas" / "vendor" / "README.md"


@pytest.fixture(scope="module")
def imported() -> Any:
    return read_arazzo(str(_FIXTURE))


@pytest.fixture(scope="module")
def exported() -> Any:
    service, _findings, _plugin = detect_and_load(str(_CONTRACT))
    return to_arazzo(
        load_workflow_manifest(str(_MANIFEST)),
        source_name="crud",
        source_url="../../apis/crud/openapi.yaml",
        service=service,
    )


def _untranslated(result: Any, construct: str) -> Any:
    return [u for u in result.untranslated if u.construct.startswith(construct)]


# ------------------------------------------------------------------ detection


def test_a_description_is_recognised_by_its_own_root_field() -> None:
    """`arazzo` is required and unique to the format, so detection is a fact
    about the document rather than a guess from the file name."""
    assert is_arazzo(yaml.safe_load(_FIXTURE.read_text(encoding="utf-8")))
    assert not is_arazzo(yaml.safe_load(_MANIFEST.read_text(encoding="utf-8")))
    assert not is_arazzo("arazzo: 1.1.0")


def test_reading_a_manifest_as_arazzo_says_what_is_wrong() -> None:
    with pytest.raises(ValueError, match="no root 'arazzo' field"):
        read_arazzo(str(_MANIFEST))


# --------------------------------------------------------------- what imports


def test_the_workflows_are_read(imported: Any) -> None:
    assert imported.version == "1.1.0"
    assert [w.name for w in imported.workflows] == ["user-lifecycle", "audit"]
    assert imported.sources == ["crud"]


def test_operation_path_gives_a_method_and_a_path_with_no_source_document(
    imported: Any,
) -> None:
    """The asymmetry that makes the importer useful: a JSON Pointer names the
    path and the method literally, so nothing has to be resolved."""
    create = imported.workflows[0].steps[0]
    assert (create.request.method, create.request.path) == ("POST", "/users")


def test_a_path_parameter_renames_the_placeholder_to_this_engines_variable(
    imported: Any,
) -> None:
    """The contract declares `/users/{id}`; the value expression says the
    variable is `user_id`. The manifest substitutes by variable name, so
    leaving `{id}` in the path would substitute nothing and send a literal."""
    read_back = imported.workflows[0].steps[1]
    assert read_back.request.path == "/users/{user_id}"


def test_query_and_header_parameters_land_where_the_engine_reads_them(
    imported: Any,
) -> None:
    read_back = imported.workflows[0].steps[1]
    assert read_back.request.query == {"limit": 1}
    assert read_back.request.headers == {"X-Request-Id": "verity-{user_name}"}


def test_a_payload_keeps_its_runtime_values_as_manifest_variables(
    imported: Any,
) -> None:
    create = imported.workflows[0].steps[0]
    assert create.request.body == {"name": "{user_name}", "role": "{user_role}"}


def test_outputs_become_extraction_and_a_timeout_changes_unit(imported: Any) -> None:
    """Arazzo's `timeout` is milliseconds and `timeout_seconds` is not. A unit
    carried across unchanged would make a 15-second step wait four hours."""
    create = imported.workflows[0].steps[0]
    assert create.extract == {"user_id": "$.id"}
    assert create.timeout_seconds == 15.0


def test_an_or_chain_of_status_criteria_becomes_the_expected_list(
    imported: Any,
) -> None:
    delete = imported.workflows[0].steps[2]
    assert delete.assert_status == [200, 204]


def test_an_equality_on_the_body_becomes_a_jsonpath_assertion(imported: Any) -> None:
    read_back = imported.workflows[0].steps[1]
    assert read_back.assert_jsonpath == {"$.role": "user"}


def test_workflow_inputs_become_names(imported: Any) -> None:
    """A JSON Schema in, a list of names out: the manifest has nowhere to put
    a type."""
    assert imported.workflows[0].inputs == ["user_name", "user_role"]


# ---------------------------------------------------- what does not, and says so


def test_a_retry_is_reported_rather_than_dropped(imported: Any) -> None:
    """The step still imports -- the request is unchanged -- but a run that
    retries three times and a run that does not are different runs."""
    entries = _untranslated(imported, "onFailure")
    assert [e.step for e in entries] == ["delete"]
    assert "retry" in entries[0].reason


def test_an_operation_id_step_is_dropped_and_explains_why(imported: Any) -> None:
    """`operationId` names an operation inside a source description. The method
    and path are in that document, which this importer does not read."""
    assert "user-lifecycle.confirm-gone" in imported.dropped_steps
    entries = _untranslated(imported, "operationId")
    assert len(entries) == 1 and "getUser" in entries[0].reason


def test_a_nested_workflow_step_is_dropped(imported: Any) -> None:
    assert "user-lifecycle.run-the-audit" in imported.dropped_steps
    assert _untranslated(imported, "workflowId")


def test_an_asyncapi_channel_step_is_dropped(imported: Any) -> None:
    """1.1.0 added publish/subscribe steps. This engine sends HTTP requests."""
    assert "user-lifecycle.announce" in imported.dropped_steps
    assert _untranslated(imported, "channelPath")


def test_a_cookie_parameter_is_reported(imported: Any) -> None:
    entries = _untranslated(imported, "parameters.in=cookie")
    assert len(entries) == 1


def test_a_jsonpath_criterion_is_reported(imported: Any) -> None:
    entries = _untranslated(imported, "successCriteria.type=jsonpath")
    assert len(entries) == 1


def test_an_expectation_that_needs_a_runtime_value_is_reported(imported: Any) -> None:
    """The engine substitutes variables into paths, bodies, headers and query
    values -- not into an expected value. Importing this one would compare the
    response against the literal text `{$inputs.user_name}` and fail every run,
    which is worse than not importing it."""
    entries = [
        u
        for u in imported.untranslated
        if u.construct == "successCriteria" and "runtime value" in u.reason
    ]
    assert len(entries) == 1
    assert "user_name" in entries[0].reason


def test_every_dropped_step_is_also_named_in_untranslated(imported: Any) -> None:
    """Two lists that could disagree. A step counted as dropped with no reason
    beside it is a hole in exactly the place this module exists to close."""
    explained = {f"{u.workflow}.{u.step}" for u in imported.untranslated if u.step}
    assert set(imported.dropped_steps) <= explained


def test_the_note_says_the_import_carries_no_host_allowlist(imported: Any) -> None:
    """A manifest's `allowed_hosts` is what stops the engine sending traffic
    somewhere the author did not name. Arazzo has no such field, so the
    imported workflow has none and the note has to say so."""
    assert imported.workflows[0].allowed_hosts == []
    assert imported.workflows[0].base_url is None
    assert "no host allowlist" in imported.note
    assert "--base-url" in imported.note


def test_a_workflow_with_no_steps_reads_as_a_workflow_with_no_steps() -> None:
    result = from_arazzo(
        {
            "arazzo": "1.0.0",
            "info": {"title": "t", "version": "1"},
            "sourceDescriptions": [],
            "workflows": [{"workflowId": "empty", "steps": []}],
        }
    )
    assert result.version == "1.0.0"
    assert result.workflows[0].steps == []


def test_a_step_naming_no_operation_at_all_is_reported() -> None:
    result = from_arazzo(
        {
            "arazzo": ARAZZO_VERSION,
            "info": {"title": "t", "version": "1"},
            "sourceDescriptions": [],
            "workflows": [{"workflowId": "w", "steps": [{"stepId": "s"}]}],
        }
    )
    assert result.dropped_steps == ["w.s"]
    assert "operationId" in result.untranslated[0].reason


# --------------------------------------------------------------- what exports


def test_the_export_names_the_version_it_writes(exported: Any) -> None:
    assert exported.document["arazzo"] == ARAZZO_VERSION == "1.1.0"


def test_a_manifest_template_becomes_the_contracts_declared_parameter(
    exported: Any,
) -> None:
    """The manifest says `/users/{user_id}`; the contract declares
    `/users/{id}`. The pointer has to name the contract's path or it resolves
    to nothing, and the parameter has to carry the contract's name."""
    step = exported.document["workflows"][0]["steps"][1]
    assert step["operationPath"].endswith("#/paths/~1users~1{id}/get")
    assert step["parameters"] == [
        {"name": "id", "in": "path", "value": "$steps.create.outputs.user_id"}
    ]


def test_a_variable_is_written_as_the_step_that_produced_it(exported: Any) -> None:
    """`{user_id}` is a name in a flat table here and an origin in Arazzo. A
    value that named no origin would be an input the workflow never declares."""
    values = [
        p["value"]
        for step in exported.document["workflows"][0]["steps"]
        for p in step.get("parameters", [])
    ]
    assert values == [
        "$steps.create.outputs.user_id",
        "$steps.create.outputs.user_id",
    ]


def test_assertions_become_criteria(exported: Any) -> None:
    steps = exported.document["workflows"][0]["steps"]
    assert steps[0]["successCriteria"] == [{"condition": "$statusCode == 201"}]
    assert {"condition": "$response.body#/name == 'alice'"} in steps[1]["successCriteria"]
    assert steps[2]["successCriteria"] == [
        {"condition": "$statusCode == 200 || $statusCode == 204"}
    ]


def test_extraction_becomes_outputs(exported: Any) -> None:
    assert exported.document["workflows"][0]["steps"][0]["outputs"] == {
        "user_id": "$response.body#/id"
    }


def test_cleanup_is_reported_and_not_written_as_an_ordinary_step(
    exported: Any,
) -> None:
    """A manifest's cleanup runs after a failure. Written as a fourth step it
    would run on the success path too -- and the fixture's cleanup is a
    DELETE."""
    step_ids = [s["stepId"] for s in exported.document["workflows"][0]["steps"]]
    assert step_ids == ["create", "get", "delete"]
    assert [u.construct for u in exported.untranslated if u.construct == "cleanup"]


def test_the_allowlist_is_reported_as_not_carried(exported: Any) -> None:
    assert [u for u in exported.untranslated if u.construct == "allowed_hosts"]


def test_without_a_contract_the_manifests_own_template_is_written_and_flagged() -> None:
    """`--to-arazzo` requires `--spec` for exactly this reason. The library
    entry point does not, so it has to say what the difference is."""
    export = to_arazzo(
        load_workflow_manifest(str(_MANIFEST)),
        source_name="crud",
        source_url="./openapi.yaml",
        service=None,
    )
    step = export.document["workflows"][0]["steps"][1]
    assert step["operationPath"].endswith("#/paths/~1users~1{user_id}/get")
    flagged = [u for u in export.untranslated if u.construct == "request.path"]
    assert len(flagged) == 2  # the get and the delete
    assert "declared parameter name" in flagged[0].reason


def test_an_id_outside_arazzos_charset_is_renamed_and_recorded() -> None:
    workflow = load_workflow_manifest(str(_MANIFEST))
    workflow.name = "crud lifecycle (v2)"
    export = to_arazzo(workflow, source_name="crud", source_url="./openapi.yaml")
    assert export.document["workflows"][0]["workflowId"] == "crud-lifecycle-v2"
    assert export.renamed == {"crud lifecycle (v2)": "crud-lifecycle-v2"}


def test_inputs_are_written_as_a_json_schema_of_required_strings() -> None:
    workflow = load_workflow_manifest(str(_MANIFEST))
    workflow.inputs = ["tenant"]
    export = to_arazzo(workflow, source_name="crud", source_url="./openapi.yaml")
    assert export.document["workflows"][0]["inputs"] == {
        "type": "object",
        "properties": {"tenant": {"type": "string"}},
        "required": ["tenant"],
    }


# ------------------------------------------------------------------ round trip


def test_the_export_reads_back_as_the_same_requests(exported: Any) -> None:
    """No Arazzo runtime is vendored here, so nothing in this repository can
    execute what it writes. What can be checked is that the writer and the
    reader agree -- and that is the whole of the claim, stated in the module
    docstring in the same words."""
    back = from_arazzo(exported.document)
    original = load_workflow_manifest(str(_MANIFEST))
    assert len(back.workflows) == 1
    rebuilt = back.workflows[0]
    assert [s.name for s in rebuilt.steps] == [s.name for s in original.steps]
    for was, now in zip(original.steps, rebuilt.steps, strict=True):
        assert now.request.method == was.request.method
        assert now.assert_status == was.assert_status
        assert now.assert_jsonpath == was.assert_jsonpath
        assert now.extract == was.extract


def test_the_round_trip_reports_nothing_it_did_not_already_report(
    exported: Any,
) -> None:
    """Reading back a document this module wrote should surface no surprises:
    anything unrepresentable was already refused at export."""
    back = from_arazzo(exported.document)
    assert back.untranslated == []
    assert back.dropped_steps == []


# ---------------------------------------------------- the schema, not our word


def _validator() -> Any:
    from jsonschema import Draft202012Validator

    schema = json.loads(_SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def test_the_vendored_schema_is_the_iteration_the_module_names() -> None:
    """Three places carry this: the constant, the file name and the provenance
    table. Re-fetching a newer iteration must not leave two of them behind."""
    schema = json.loads(_SCHEMA.read_text(encoding="utf-8"))
    assert schema["$id"] == SCHEMA_ITERATION
    assert SCHEMA_ITERATION.rsplit("/", 1)[-1] in _SCHEMA.name
    assert SCHEMA_ITERATION in _VENDOR_README.read_text(encoding="utf-8")


def test_the_exported_document_validates_against_the_published_schema(
    exported: Any,
) -> None:
    errors = sorted(_validator().iter_errors(exported.document), key=str)
    assert errors == [], [f"{list(e.absolute_path)}: {e.message}" for e in errors]


def test_the_bundled_fixture_is_itself_valid_arazzo() -> None:
    """Every import test above measures this document. If it were not valid
    Arazzo, they would all be measuring something no runtime would accept."""
    document = yaml.safe_load(_FIXTURE.read_text(encoding="utf-8"))
    errors = sorted(_validator().iter_errors(document), key=str)
    assert errors == [], [f"{list(e.absolute_path)}: {e.message}" for e in errors]


def test_the_schema_does_reject_something(exported: Any) -> None:
    """A validator that accepts everything passes both tests above. This is the
    control: a document with a broken step must fail."""
    broken = json.loads(json.dumps(exported.document))
    broken["workflows"][0]["steps"][0].pop("operationPath")
    assert list(_validator().iter_errors(broken))


def test_every_written_id_matches_arazzos_own_pattern(exported: Any) -> None:
    """`[A-Za-z0-9_\\-]+` is a SHOULD in the specification and not in the
    schema, so nothing above would catch a `stepId` with a space in it."""
    pattern = re.compile(r"^[A-Za-z0-9_\-]+$")
    for workflow in exported.document["workflows"]:
        assert pattern.fullmatch(workflow["workflowId"])
        for step in workflow["steps"]:
            assert pattern.fullmatch(step["stepId"])
