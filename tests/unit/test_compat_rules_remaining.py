"""The rest of #15's compatibility catalog, and a misclassification it exposed.

Three things are covered here:

- requiredness changes were only detected in one direction, so a response
  field becoming optional -- breaking for every consumer that read it
  unconditionally -- produced no change at all;
- a field *becoming required* was reported as `BRK-PARAM-OPTIONALIZED` at INFO,
  the exact opposite of what happened, so a breaking request change passed a
  CI gate as informational;
- discriminator changes on polymorphic schemas were invisible, including a
  value silently being remapped to a different schema.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from apiverity.diff.engine import diff_services
from apiverity.rules.breaking import evaluate_breaking
from apiverity.specs.loader import detect_and_load

_OBJECT_SPEC = """\
openapi: "3.0.3"
info: {{ title: D, version: "1.0.0" }}
paths:
  /users:
    post:
      operationId: createUser
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required: [{request_required}]
              properties:
                name: {{ type: string }}
                email: {{ type: string }}
      responses:
        "200":
          description: ok
          content:
            application/json:
              schema:
                type: array
                items:
                  type: object
                  required: [{response_required}]
                  properties:
                    id: {{ type: string }}
                    total: {{ type: number }}
"""

_DISC_SPEC = """\
openapi: "3.0.3"
info: {{ title: D, version: "1.0.0" }}
paths:
  /pets:
    get:
      operationId: getPet
      responses:
        "200":
          description: ok
          content:
            application/json:
              schema:
                oneOf:
                  - {{ type: object, properties: {{ bark: {{ type: string }} }} }}
                  - {{ type: object, properties: {{ meow: {{ type: string }} }} }}
                discriminator:
                  propertyName: {prop}
                  mapping:
{mapping}
"""


def _write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def _changes(old: Path, new: Path):
    old_service, _, _ = detect_and_load(str(old))
    new_service, _, _ = detect_and_load(str(new))
    return diff_services(old_service, new_service)


def _findings(old: Path, new: Path):
    return evaluate_breaking(_changes(old, new))


def _objects(tmp_path: Path, *, req: tuple[str, str], resp: tuple[str, str]):
    old = _write(
        tmp_path,
        "v1.yaml",
        _OBJECT_SPEC.format(request_required=req[0], response_required=resp[0]),
    )
    new = _write(
        tmp_path,
        "v2.yaml",
        _OBJECT_SPEC.format(request_required=req[1], response_required=resp[1]),
    )
    return old, new


# --------------------------------------------------------------- requiredness


def test_a_request_field_becoming_required_is_an_error(tmp_path: Path) -> None:
    """The misclassification: this was BRK-PARAM-OPTIONALIZED at INFO."""
    old, new = _objects(tmp_path, req=("name", "name, email"), resp=("id", "id"))
    matching = [f for f in _findings(old, new) if "email" in f.message]
    assert matching, "a request field becoming required produced no finding"
    finding = matching[0]
    assert finding.rule_id == "BRK-REQ-FIELD-BECAME-REQUIRED", finding.rule_id
    assert finding.severity.value.upper() == "ERROR", (
        "a breaking request change must not be reported as informational"
    )


def test_a_response_field_becoming_optional_is_an_error(tmp_path: Path) -> None:
    """Previously invisible, inside an array of objects."""
    old, new = _objects(tmp_path, req=("name", "name"), resp=("id, total", "id"))
    matching = [f for f in _findings(old, new) if "total" in f.message]
    assert matching, "a response field becoming optional produced no finding"
    finding = matching[0]
    assert finding.rule_id == "BRK-RESP-FIELD-OPTIONALIZED"
    assert finding.severity.value.upper() == "ERROR"


def test_a_request_field_becoming_optional_is_a_relaxation(tmp_path: Path) -> None:
    """Direction matters: relaxing a request cannot break a sender."""
    old, new = _objects(tmp_path, req=("name, email", "name"), resp=("id", "id"))
    matching = [f for f in _findings(old, new) if "email" in f.message]
    assert matching
    assert matching[0].rule_id == "BRK-REQ-FIELD-OPTIONALIZED"
    assert matching[0].severity.value.upper() == "INFO"


def test_an_unchanged_contract_reports_no_requiredness_change(tmp_path: Path) -> None:
    old, new = _objects(tmp_path, req=("name", "name"), resp=("id", "id"))
    noise = [
        c for c in _changes(old, new) if "required" in c.description or "optional" in c.description
    ]
    assert not noise, noise


# -------------------------------------------------------------- discriminator


def _disc(tmp_path: Path, prop: str, mapping: dict[str, str], name: str) -> Path:
    rendered = "\n".join(f'                    {k}: "{v}"' for k, v in mapping.items())
    return _write(tmp_path, name, _DISC_SPEC.format(prop=prop, mapping=rendered))


_BASE_MAP = {"dog": "#/components/schemas/Dog", "cat": "#/components/schemas/Cat"}


def test_renaming_the_discriminator_property_is_reported(tmp_path: Path) -> None:
    old = _disc(tmp_path, "petType", _BASE_MAP, "v1.yaml")
    new = _disc(tmp_path, "kind", _BASE_MAP, "v2.yaml")
    matching = [c for c in _changes(old, new) if "discriminator property" in c.description]
    assert matching, "renaming the discriminator property produced no change"
    assert matching[0].breaking_hint


def test_removing_a_mapping_is_reported(tmp_path: Path) -> None:
    old = _disc(tmp_path, "petType", _BASE_MAP, "v1.yaml")
    new = _disc(tmp_path, "petType", {"dog": _BASE_MAP["dog"]}, "v2.yaml")
    matching = [c for c in _changes(old, new) if "mapping removed" in c.description]
    assert matching and "cat" in matching[0].description


def test_adding_a_response_variant_warns_about_exhaustive_consumers(tmp_path: Path) -> None:
    """Additive in a request; not in a response."""
    old = _disc(tmp_path, "petType", _BASE_MAP, "v1.yaml")
    new = _disc(tmp_path, "petType", {**_BASE_MAP, "bird": "#/x/Bird"}, "v2.yaml")
    matching = [c for c in _changes(old, new) if "mapping added" in c.description]
    assert matching and "bird" in matching[0].description
    assert matching[0].breaking_hint, "a new response variant needs a hint"


def test_remapping_a_value_to_a_different_schema_is_reported(tmp_path: Path) -> None:
    """The quiet one: the same value now deserializes into a different type."""
    old = _disc(tmp_path, "petType", _BASE_MAP, "v1.yaml")
    new = _disc(tmp_path, "petType", {**_BASE_MAP, "dog": "#/x/Canine"}, "v2.yaml")
    matching = [c for c in _changes(old, new) if "now maps to" in c.description]
    assert matching, "a remapped discriminator value produced no change"
    assert "Canine" in matching[0].description
    assert "wrong type" in (matching[0].breaking_hint or "")


def test_identical_discriminators_are_quiet(tmp_path: Path) -> None:
    old = _disc(tmp_path, "petType", _BASE_MAP, "v1.yaml")
    new = _disc(tmp_path, "petType", _BASE_MAP, "v2.yaml")
    assert not [c for c in _changes(old, new) if "discriminator" in c.description]


@pytest.mark.parametrize("rule", ["BRK-REQ-FIELD-OPTIONALIZED", "BRK-RESP-FIELD-OPTIONALIZED"])
def test_new_rules_are_in_the_catalog(rule: str) -> None:
    """An emitted rule id that is not in CATALOG cannot have its severity
    overridden, and would not appear in the generated documentation."""
    from apiverity.rules.breaking import CATALOG

    assert rule in CATALOG
