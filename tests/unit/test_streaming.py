"""OpenAPI 3.2 streaming payloads: SSE, JSON Lines, multipart.

Before 3.2 a streaming endpoint had two ways to describe itself and both were
wrong. `schema` describes the whole body, and a stream has no whole body; the
alternative was prose, which no tool can check. `itemSchema` describes one
item, and this module is what makes sure the tool reads it.

The test that matters most is the last one in the diff section.
`application/json` becoming `application/jsonl` breaks every consumer while
leaving every schema byte-identical, so every schema-diffing tool reports a
clean run — and a reader who trusts a clean run ships it.
"""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from apiverity.core.model import SEQUENTIAL_MEDIA, is_sequential_media
from apiverity.diff.engine import diff_services
from apiverity.rules.breaking import evaluate_breaking
from apiverity.specs.loader import detect_and_load

_ROOT = Path(__file__).resolve().parents[2]
_V1 = _ROOT / "fixtures" / "apis" / "streaming" / "v1.yaml"
_V2 = _ROOT / "fixtures" / "apis" / "streaming" / "v2.yaml"


def _load(path: Path) -> Any:
    service, _, _ = detect_and_load(str(path))
    return service


def _spec(document: dict[str, Any], tmp_path: Path, name: str) -> Any:
    path = tmp_path / f"{name}.yaml"
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    service, findings, _ = detect_and_load(str(path))
    return service, findings


def _contract(media: str, media_object: dict[str, Any], version: str = "1.0.0") -> dict[str, Any]:
    return {
        "openapi": "3.2.0",
        "info": {"title": "Stream", "version": version},
        "paths": {
            "/events": {
                "get": {
                    "responses": {"200": {"description": "ok", "content": {media: media_object}}}
                }
            }
        },
    }


def _rules(old: Any, new: Any) -> list[str]:
    return [f.rule_id for f in evaluate_breaking(diff_services(old, new))]


# -- what counts as a stream ----------------------------------------------


@pytest.mark.parametrize(
    ("media", "sequential"),
    [
        ("text/event-stream", True),
        ("text/event-stream; charset=utf-8", True),
        ("application/jsonl", True),
        ("application/x-ndjson", True),
        ("application/json-seq", True),
        ("multipart/mixed", True),
        ("multipart/form-data; boundary=x", True),
        ("application/json", False),
        ("text/plain", False),
        ("application/xml", False),
    ],
)
def test_which_media_types_carry_a_sequence(media: str, sequential: bool) -> None:
    """Parameters are ignored on purpose. A contract that writes
    `text/event-stream; charset=utf-8` and a service that sends
    `text/event-stream` are not disagreeing about anything."""
    assert is_sequential_media(media) is sequential


def test_the_sequential_list_is_lowercase_and_parameterless() -> None:
    """It is compared against a lowercased, parameter-stripped media type, so
    an entry with a parameter or a capital could never match."""
    for media in SEQUENTIAL_MEDIA:
        assert media == media.lower()
        assert ";" not in media


# -- parsing ---------------------------------------------------------------


def test_an_item_schema_is_parsed_into_the_same_model_a_body_schema_is() -> None:
    """Not a parallel representation. Every field, type and constraint rule
    applies to an event because an event is a `SchemaNode` like any other."""
    service = _load(_V1)
    events = next(op for op in service.operations if op.path == "/events")
    stream = events.responses[0].streaming["text/event-stream"]
    assert stream.item_schema is not None
    assert sorted(stream.item_schema.properties) == ["at", "detail", "id", "kind"]
    assert sorted(stream.item_schema.required) == ["id", "kind"]


def test_a_body_with_only_an_item_schema_is_not_dropped(tmp_path: Path) -> None:
    """The defect this fixes. A JSON Lines body legitimately declares an item
    shape and no body shape, and the parser only ever looked at `schema` -- so
    the payload was invisible to every rule."""
    service, _ = _spec(
        _contract("application/jsonl", {"itemSchema": {"type": "object"}}), tmp_path, "only-item"
    )
    response = service.operations[0].responses[0]
    assert response.content == {}
    assert "application/jsonl" in response.streaming


def test_a_contract_that_says_nothing_streaming_grows_no_empty_declaration(
    tmp_path: Path,
) -> None:
    """Otherwise every 3.0 contract would appear to have lost something the
    moment it was diffed against itself."""
    service, _ = _spec(
        _contract("application/json", {"schema": {"type": "object"}}), tmp_path, "plain"
    )
    assert service.operations[0].responses[0].streaming == {}


def test_item_encoding_is_read_as_a_map_of_properties() -> None:
    service = _load(_V1)
    ingest = next(op for op in service.operations if op.path == "/ingest")
    stream = ingest.request_body.streaming["application/jsonl"]
    assert stream.item_encoding["value"].content_type == "application/json"


def test_item_encoding_written_as_one_object_is_read_rather_than_dropped(
    tmp_path: Path,
) -> None:
    """Some documents write a single Encoding Object meaning "the whole item".
    A contract this tool silently ignored half of would be worse than one it
    read generously and reported on accurately."""
    service, _ = _spec(
        _contract(
            "application/jsonl",
            {"itemSchema": {"type": "object"}, "itemEncoding": {"contentType": "application/cbor"}},
        ),
        tmp_path,
        "single-encoding",
    )
    stream = service.operations[0].responses[0].streaming["application/jsonl"]
    assert stream.item_encoding[""].content_type == "application/cbor"


def test_prefix_encoding_keeps_its_positions(tmp_path: Path) -> None:
    """It is positional. An unreadable entry becomes an empty Encoding rather
    than shifting everything after it into the wrong slot."""
    service, _ = _spec(
        _contract(
            "multipart/mixed",
            {
                "itemSchema": {"type": "object"},
                "prefixEncoding": [
                    {"contentType": "application/json"},
                    "nonsense",
                    {"contentType": "text/plain"},
                ],
            },
        ),
        tmp_path,
        "prefixes",
    )
    prefix = service.operations[0].responses[0].streaming["multipart/mixed"].prefix_encoding
    assert [e.content_type for e in prefix] == ["application/json", None, "text/plain"]


# -- validation ------------------------------------------------------------


def test_a_stream_with_no_item_schema_is_reported(tmp_path: Path) -> None:
    """What every pre-3.2 contract looks like. Worth a warning rather than
    silence: the payload is invisible to every rule and the contract does not
    say so."""
    _, findings = _spec(
        _contract("text/event-stream", {"schema": {"type": "object"}}), tmp_path, "no-item"
    )
    codes = {f.rule_id for f in findings}
    assert "SPEC-STREAM-ITEM-SCHEMA-MISSING" in codes


def test_an_item_schema_on_a_non_sequential_media_type_is_reported(tmp_path: Path) -> None:
    _, findings = _spec(
        _contract("application/json", {"itemSchema": {"type": "object"}}), tmp_path, "unused-item"
    )
    codes = {f.rule_id for f in findings}
    assert "SPEC-STREAM-ITEM-SCHEMA-UNUSED" in codes


def test_a_well_formed_stream_is_reported_as_neither() -> None:
    """Both directions. A rule that fires on a correct contract is the one that
    gets a whole family switched off."""
    _, findings, _ = detect_and_load(str(_V1))
    codes = {f.rule_id for f in findings}
    assert "SPEC-STREAM-ITEM-SCHEMA-MISSING" not in codes
    assert "SPEC-STREAM-ITEM-SCHEMA-UNUSED" not in codes


# -- diffing ---------------------------------------------------------------


def test_every_field_rule_applies_to_an_item() -> None:
    """The reason item schemas are `SchemaNode`s. A second family of
    item-shaped rules would be forty duplicates that drift."""
    fired = _rules(_load(_V1), _load(_V2))
    assert "BRK-RESP-FIELD-REMOVED" in fired
    assert "BRK-ENUM-NARROWED-RESPONSE" in fired


def test_the_finding_says_it_was_an_item_not_a_body() -> None:
    """A reader has to be able to tell which. The wire shapes differ."""
    findings = evaluate_breaking(diff_services(_load(_V1), _load(_V2)))
    removed = next(f for f in findings if f.rule_id == "BRK-RESP-FIELD-REMOVED")
    assert "stream item" in removed.message


def test_a_changed_item_encoding_is_breaking() -> None:
    """The part still arrives and the parser reading it fails."""
    assert "BRK-STREAM-ENCODING-CHANGED" in _rules(_load(_V1), _load(_V2))


def test_removing_the_item_schema_is_breaking(tmp_path: Path) -> None:
    old, _ = _spec(
        _contract("application/jsonl", {"itemSchema": {"type": "object"}}), tmp_path, "a"
    )
    new, _ = _spec(
        _contract("application/jsonl", {"itemEncoding": {"contentType": "application/json"}}),
        tmp_path,
        "b",
    )
    assert "BRK-STREAM-ITEM-SCHEMA-REMOVED" in _rules(old, new)


def test_adding_an_item_schema_is_a_note(tmp_path: Path) -> None:
    old, _ = _spec(
        _contract("application/jsonl", {"itemEncoding": {"contentType": "application/json"}}),
        tmp_path,
        "c",
    )
    new, _ = _spec(
        _contract("application/jsonl", {"itemSchema": {"type": "object"}}), tmp_path, "d"
    )
    fired = _rules(old, new)
    assert "BRK-STREAM-ITEM-SCHEMA-ADDED" in fired


def test_inserting_a_leading_part_is_breaking(tmp_path: Path) -> None:
    """`prefixEncoding` is positional: anything but an append renumbers every
    part after the change, so a reader that correctly identified part three now
    reads part four's bytes with part three's decoder."""
    old, _ = _spec(
        _contract(
            "multipart/mixed",
            {"itemSchema": {"type": "object"}, "prefixEncoding": [{"contentType": "text/plain"}]},
        ),
        tmp_path,
        "e",
    )
    new, _ = _spec(
        _contract(
            "multipart/mixed",
            {
                "itemSchema": {"type": "object"},
                "prefixEncoding": [
                    {"contentType": "application/json"},
                    {"contentType": "text/plain"},
                ],
            },
        ),
        tmp_path,
        "f",
    )
    assert "BRK-STREAM-PREFIX-COUNT-CHANGED" in _rules(old, new)


def test_a_document_becoming_a_stream_is_reported_though_no_schema_changed(
    tmp_path: Path,
) -> None:
    """The finding this family exists for.

    `application/json` to `application/jsonl` breaks every consumer -- one
    waits for the body to end and parses once, the other parses a line at a
    time and may never see an end -- and every schema-diffing tool reports a
    clean run, because no schema changed.
    """
    item = {"type": "object", "properties": {"id": {"type": "string"}}}
    old, _ = _spec(_contract("application/json", {"schema": item}), tmp_path, "doc")
    new, _ = _spec(_contract("application/jsonl", {"itemSchema": item}), tmp_path, "stream")

    fired = _rules(old, new)
    assert "BRK-STREAM-SEQUENTIAL-CHANGED" in fired

    # And it is an error, not a note: this is not a content-negotiation detail.
    findings = evaluate_breaking(diff_services(old, new))
    transition = next(f for f in findings if f.rule_id == "BRK-STREAM-SEQUENTIAL-CHANGED")
    assert transition.severity.value == "ERROR"


def test_a_stream_becoming_a_document_is_reported_too(tmp_path: Path) -> None:
    """The other direction breaks the same clients for the mirror reason."""
    item = {"type": "object", "properties": {"id": {"type": "string"}}}
    old, _ = _spec(_contract("application/jsonl", {"itemSchema": item}), tmp_path, "s")
    new, _ = _spec(_contract("application/json", {"schema": item}), tmp_path, "d2")
    assert "BRK-STREAM-SEQUENTIAL-CHANGED" in _rules(old, new)


def test_a_contract_diffed_against_itself_reports_no_streaming_change() -> None:
    """The cheapest false-positive check there is, and the one that catches a
    rule keyed on something that is not stable."""
    service = _load(_V1)
    assert not [r for r in _rules(service, _load(_V1)) if r.startswith("BRK-STREAM-")]
    assert not diff_services(service, _load(_V1))


# -- the rules are explainable and suggest a fix ---------------------------


@pytest.mark.parametrize(
    "rule_id",
    [
        "BRK-STREAM-SEQUENTIAL-CHANGED",
        "BRK-STREAM-ITEM-SCHEMA-REMOVED",
        "BRK-STREAM-ITEM-SCHEMA-ADDED",
        "BRK-STREAM-ENCODING-CHANGED",
        "BRK-STREAM-PREFIX-COUNT-CHANGED",
        "SPEC-STREAM-ITEM-SCHEMA-MISSING",
        "SPEC-STREAM-ITEM-SCHEMA-UNUSED",
    ],
)
def test_explain_answers_for_every_streaming_rule(rule_id: str) -> None:
    from apiverity.cli.main import main

    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = main(["explain", rule_id, "--json"])
    assert code == 0
    payload = json.loads(out.getvalue())
    assert payload["description"].strip()
    assert payload["group"] == "Streaming media"


def test_the_breaking_rules_carry_a_non_breaking_alternative() -> None:
    """A gate that only says no gets switched off, and the reader still wants
    the change they came for."""
    from apiverity.rules.alternatives import ALTERNATIVES

    for rule_id in (
        "BRK-STREAM-SEQUENTIAL-CHANGED",
        "BRK-STREAM-ITEM-SCHEMA-REMOVED",
        "BRK-STREAM-ENCODING-CHANGED",
        "BRK-STREAM-PREFIX-COUNT-CHANGED",
    ):
        assert len(ALTERNATIVES[rule_id]) > 40, rule_id
