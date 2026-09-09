"""A contract inferred from traffic, and the three lies it declines to tell.

The most common answer to "run the contract gate on this API" is "we do not
have a contract". Recorded traffic is the next best evidence -- but a document
inferred from four requests that reads like one a person wrote is worse than no
document, because everything downstream treats it as authoritative.

So the tests are mostly about restraint: required needs enough samples, enums
are off unless asked for, and a path segment becomes a parameter only on
evidence.
"""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from apiverity.cli.commands.common import EXIT_OK, EXIT_USAGE
from apiverity.cli.main import main
from apiverity.specs.infer import (
    MIN_SAMPLES_FOR_REQUIRED,
    _Observed,
    infer,
    infer_templates,
    looks_like_identifier,
    observe,
    to_schema,
)


def _entry(method: str, path: str, status: int = 200, body: Any = None, at: str = "") -> dict:
    return {
        "method": method,
        "url": f"https://api.example.com{path}",
        "status": status,
        "response_body": body,
        "response_mime": "application/json",
        "started_at": at or "2026-03-01T09:00:00.000Z",
    }


def _fold(*bodies: Any) -> _Observed:
    node = _Observed()
    for body in bodies:
        observe(node, body)
    return node


def _run(argv: list[str]) -> tuple[int, dict[str, Any], str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    text = out.getvalue()
    return code, (json.loads(text) if text.strip().startswith("{") else {}), err.getvalue()


# ------------------------------------------------------------------ segments


@pytest.mark.parametrize(
    ("segment", "kind"),
    [
        ("11111111-1111-4111-8111-111111111111", "uuid"),
        ("42", "integer"),
        ("0123456789abcdef01", "hex"),
        ("cus_A1b2C3d4e5", "prefixed id"),
        ("me", None),
        ("settings", None),
        ("v1", None),
    ],
)
def test_what_reads_as_an_identifier(segment: str, kind: str | None) -> None:
    assert looks_like_identifier(segment) == kind


def test_identifier_siblings_collapse_into_one_parameter() -> None:
    paths = [f"/users/{n}" for n in (11, 12, 13)]
    templates = infer_templates(paths)
    assert {t.template for t in templates.values()} == {"/users/{userId}"}


def test_a_named_sibling_keeps_every_path_literal() -> None:
    """`/users/me` and `/users/settings` are two operations, not one."""
    templates = infer_templates(["/users/me", "/users/settings"])
    assert {t.template for t in templates.values()} == {"/users/me", "/users/settings"}


def test_a_named_sibling_among_identifiers_stays_itself() -> None:
    paths = [*[f"/users/{n}" for n in (11, 12, 13)], "/users/me"]
    templates = infer_templates(paths)
    assert templates["/users/me"].template == "/users/me"
    assert templates["/users/11"].template == "/users/{userId}"


def test_a_single_identifier_with_no_siblings_is_not_collapsed() -> None:
    """One observation is not a pattern."""
    templates = infer_templates(["/users/42"])
    assert templates["/users/42"].template == "/users/42"


def test_the_parameter_is_named_after_its_parent_segment() -> None:
    templates = infer_templates([f"/orders/{n}" for n in (1, 2, 3)])
    assert next(iter(templates.values())).template == "/orders/{orderId}"


def test_two_parameters_in_one_path_get_distinct_names() -> None:
    paths = [f"/orders/{o}/items/{i}" for o in (1, 2, 3) for i in (7, 8, 9)]
    template = infer_templates(paths)[paths[0]].template
    assert template == "/orders/{orderId}/items/{itemId}"


def test_every_template_records_why_it_folded() -> None:
    templates = infer_templates([f"/users/{n}" for n in (11, 12, 13)])
    assert "looks like a integer" in next(iter(templates.values())).reason


# ------------------------------------------------------------------- schemas


def test_a_property_seen_every_time_needs_enough_times() -> None:
    """Present in all two samples is a coincidence, not a guarantee."""
    two = to_schema(_fold({"a": 1}, {"a": 2}))
    assert "required" not in two

    enough = to_schema(_fold(*({"a": n} for n in range(MIN_SAMPLES_FOR_REQUIRED))))
    assert enough["required"] == ["a"]


def test_a_property_missing_once_is_never_required() -> None:
    schema = to_schema(_fold({"a": 1}, {"a": 2}, {"a": 3}, {}))
    assert "required" not in schema


def test_every_schema_carries_the_evidence_behind_it() -> None:
    schema = to_schema(_fold({"a": 1}, {"a": 2}))
    assert schema["x-apiverity-samples"] == 2
    assert schema["properties"]["a"]["x-apiverity-samples"] == 2


def test_two_shapes_for_one_field_are_reported_as_two() -> None:
    """A fact about the API, not a problem to smooth over by picking one."""
    schema = to_schema(_fold({"a": 1}, {"a": "x"}))
    assert schema["properties"]["a"]["type"] == ["integer", "string"]


def test_a_nullable_field_keeps_null_in_its_type() -> None:
    schema = to_schema(_fold({"a": 1}, {"a": None}))
    assert "null" in schema["properties"]["a"]["type"]


def test_a_recognised_format_is_recorded() -> None:
    schema = to_schema(_fold({"at": "2026-03-01T09:00:00Z"}))
    assert schema["properties"]["at"]["format"] == "date-time"


def test_conflicting_formats_are_left_out_rather_than_guessed() -> None:
    schema = to_schema(_fold({"v": "2026-03-01"}, {"v": "a@example.com"}))
    assert "format" not in schema["properties"]["v"]


def test_no_enum_is_inferred_by_default() -> None:
    """A fabricated constraint turns a valid request into a violation."""
    schema = to_schema(_fold(*({"s": "open"} for _ in range(20))))
    assert "enum" not in schema["properties"]["s"]


def test_an_enum_needs_asking_for_and_enough_samples() -> None:
    few = to_schema(_fold(*({"s": "open"} for _ in range(3))), infer_enums=True)
    assert "enum" not in few["properties"]["s"]

    many = to_schema(_fold(*({"s": "open"} for _ in range(20))), infer_enums=True)
    assert many["properties"]["s"]["enum"] == ["open"]


def test_too_many_distinct_values_were_never_an_enum() -> None:
    schema = to_schema(_fold(*({"s": f"v{n}"} for n in range(20))), infer_enums=True)
    assert "enum" not in schema["properties"]["s"]


def test_an_array_describes_its_items() -> None:
    schema = to_schema(_fold({"xs": [{"a": 1}, {"a": 2}]}))
    assert schema["properties"]["xs"]["items"]["properties"]["a"]["type"] == "integer"


# ----------------------------------------------------------------- documents


def test_the_document_says_it_is_inferred_at_the_top_level() -> None:
    document, _ = infer([_entry("GET", "/users")])
    assert document["x-apiverity-inferred"] is True
    assert "(inferred draft)" in document["info"]["title"]


def test_the_description_says_how_much_evidence_there_was() -> None:
    document, _ = infer(
        [
            _entry("GET", "/users", at="2026-03-01T09:00:00.000Z"),
            _entry("GET", "/users", at="2026-03-09T09:00:00.000Z"),
        ]
    )
    description = document["info"]["description"]
    assert "2 recorded request(s)" in description
    assert "2026-03-01T09:00:00.000Z and 2026-03-09T09:00:00.000Z" in description
    assert "not what the API supports" in description


def test_provenance_records_what_was_read_and_what_was_not() -> None:
    _, provenance = infer([_entry("GET", "/users"), {"nonsense": True}])
    assert provenance["requests_read"] == 2
    assert provenance["requests_usable"] == 1


def test_a_status_with_no_body_is_still_a_declared_response() -> None:
    document, _ = infer([_entry("GET", "/users", status=204, body=None)])
    response = document["paths"]["/users"]["get"]["responses"]["204"]
    assert "content" not in response
    assert "no response body recorded" in response["description"]


def test_each_operation_says_how_its_path_was_templated() -> None:
    document, _ = infer([_entry("GET", f"/users/{n}") for n in (11, 12, 13)])
    described = document["paths"]["/users/{userId}"]["get"]["description"]
    assert "Path templating:" in described


# ----------------------------------------------------------------------- CLI


def _har(tmp_path: Path, entries: list[dict[str, Any]]) -> str:
    log = {
        "log": {
            "entries": [
                {
                    "startedDateTime": entry["started_at"],
                    "time": 4.0,
                    "request": {
                        "method": entry["method"],
                        "url": entry["url"],
                        "headers": [],
                        "queryString": [],
                    },
                    "response": {
                        "status": entry["status"],
                        "headers": [{"name": "content-type", "value": "application/json"}],
                        "content": {
                            "mimeType": "application/json",
                            "text": json.dumps(entry["response_body"]),
                        },
                    },
                }
                for entry in entries
            ]
        }
    }
    path = tmp_path / "traffic.har"
    path.write_text(json.dumps(log), encoding="utf-8")
    return str(path)


def test_the_command_writes_a_document_that_loads_back(tmp_path: Path) -> None:
    corpus = _har(tmp_path, [_entry("GET", f"/users/{n}", body={"id": n}) for n in (11, 12, 13)])
    out = tmp_path / "inferred.yaml"
    code, payload, _ = _run(["infer", corpus, "-o", str(out), "--json"])

    assert code == EXIT_OK
    assert payload["provenance"]["operations"] == 1
    document = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert "/users/{userId}" in document["paths"]


def test_the_drafted_document_is_a_contract_this_tool_can_read(tmp_path: Path) -> None:
    """The point of drafting one: everything downstream should accept it."""
    corpus = _har(tmp_path, [_entry("GET", f"/users/{n}", body={"id": n}) for n in (11, 12, 13)])
    out = tmp_path / "inferred.yaml"
    _run(["infer", corpus, "-o", str(out), "--json"])

    from apiverity.specs.loader import detect_and_load

    service, _, _ = detect_and_load(str(out))
    assert [op.key for op in service.operations] == ["GET /users/{userId}"]


def test_an_empty_corpus_is_a_usage_error_not_an_empty_api(tmp_path: Path) -> None:
    """An inferred document with no paths reads as 'this service has none'."""
    corpus = _har(tmp_path, [])
    code, _, err = _run(["infer", corpus])
    assert code == EXIT_USAGE
    assert "nothing to infer from" in err


def test_without_an_output_path_the_document_is_still_returned(tmp_path: Path) -> None:
    corpus = _har(tmp_path, [_entry("GET", "/users", body={"a": 1})])
    _, payload, _ = _run(["infer", corpus, "--json"])
    assert payload["document"]["paths"]["/users"]
