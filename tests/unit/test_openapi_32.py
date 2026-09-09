"""OpenAPI 3.2, released 2025-09-19.

The version gate accepted 3.0 and 3.1 only, so a 3.2 document — the current
release — was reported as an unsupported version and every construct it added
was invisible. Evaluations are lost on absences like this, not won on depth.

What matters is not that the parser *accepts* the new constructs but that the
engine treats changes to them correctly. A `query` operation that loads and
then cannot be reported as removed is worse than one that never loaded: it
looks covered.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from apiverity.core.model import ParameterLocation
from apiverity.diff.engine import diff_services
from apiverity.rules.breaking import evaluate_breaking
from apiverity.specs.loader import detect_and_load
from apiverity.specs.openapi.parser import SUPPORTED_OPENAPI_VERSIONS, OpenApiParser

_ROOT = Path(__file__).resolve().parents[2]
_FIXTURE = _ROOT / "fixtures" / "apis" / "openapi32" / "catalog.yaml"


def _load_doc(doc: dict[str, Any], tmp_path: Path, name: str = "spec.yaml"):
    path = tmp_path / name
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    service, findings, _ = detect_and_load(str(path))
    return service, findings


def _base() -> dict[str, Any]:
    return yaml.safe_load(_FIXTURE.read_text(encoding="utf-8"))


def _rules(old: dict[str, Any], new: dict[str, Any], tmp_path: Path) -> set[str]:
    before, _ = _load_doc(old, tmp_path, "old.yaml")
    after, _ = _load_doc(new, tmp_path, "new.yaml")
    return {f.rule_id for f in evaluate_breaking(diff_services(before, after))}


# ------------------------------------------------------------------ version


def test_a_32_document_loads_without_an_unsupported_version_finding() -> None:
    service, findings, _ = detect_and_load(str(_FIXTURE))
    assert "SPEC-VERSION-UNSUPPORTED" not in {f.rule_id for f in findings}
    assert service.version == "2.1.0"


def test_an_unreleased_version_is_still_refused(tmp_path: Path) -> None:
    """A 3.3 document must not be parsed on the assumption it resembles 3.2.

    Guessing at a format nobody has published yields a contract that looks
    parsed and is wrong, which is worse than saying so.
    """
    doc = _base()
    doc["openapi"] = "3.3.0"
    _, findings = _load_doc(doc, tmp_path)
    assert "SPEC-VERSION-UNSUPPORTED" in {f.rule_id for f in findings}


def test_the_supported_set_is_stated_once() -> None:
    assert SUPPORTED_OPENAPI_VERSIONS == ("3.0", "3.1", "3.2")


# ------------------------------------------------------------- new methods


def test_the_query_method_becomes_a_real_operation() -> None:
    service, _, _ = detect_and_load(str(_FIXTURE))
    assert "QUERY /products" in service.operation_keys()


def test_additional_operations_become_real_operations() -> None:
    """Verbs the specification does not name still have request and response shapes."""
    service, _, _ = detect_and_load(str(_FIXTURE))
    assert "PURGE /products" in service.operation_keys()


def test_removing_a_query_operation_is_breaking(tmp_path: Path) -> None:
    """The assertion that matters: loaded *and* governed, not merely parsed."""
    old = _base()
    new = _base()
    del new["paths"]["/products"]["query"]
    assert "BRK-OP-REMOVED" in _rules(old, new, tmp_path)


def test_removing_an_additional_operation_is_breaking(tmp_path: Path) -> None:
    old = _base()
    new = _base()
    del new["paths"]["/products"]["additionalOperations"]
    assert "BRK-OP-REMOVED" in _rules(old, new, tmp_path)


def test_tightening_a_query_request_body_is_breaking(tmp_path: Path) -> None:
    """A `query` body is a request body; the direction-aware rules apply."""
    old = _base()
    new = _base()
    schema = new["paths"]["/products"]["query"]["requestBody"]["content"]["application/json"][
        "schema"
    ]
    schema["required"] = ["filter", "sort"]
    assert "BRK-REQ-FIELD-BECAME-REQUIRED" in _rules(old, new, tmp_path)


# ------------------------------------------------------ querystring params


def test_the_querystring_location_is_accepted_and_distinct() -> None:
    service, findings, _ = detect_and_load(str(_FIXTURE))
    assert "SPEC-PARAM-LOCATION" not in {f.rule_id for f in findings}
    reports = service.find_operation("GET /reports")
    assert reports is not None
    locations = {p.name: p.location for p in reports.parameters}
    assert locations["filters"] is ParameterLocation.QUERYSTRING


def test_removing_a_querystring_parameter_is_breaking(tmp_path: Path) -> None:
    old = _base()
    new = _base()
    new["paths"]["/reports"]["get"]["parameters"] = []
    assert "BRK-PARAM-REMOVED" in _rules(old, new, tmp_path)


# ------------------------------------------------------- hierarchical tags


def test_tag_objects_are_captured_with_their_hierarchy() -> None:
    service, _, _ = detect_and_load(str(_FIXTURE))
    by_name = {tag["name"]: tag for tag in service.tags}
    assert by_name["search"]["parent"] == "catalog"
    assert by_name["catalog"]["kind"] == "nav"


def test_only_specified_tag_fields_are_captured() -> None:
    """Unknown keys stay in the document rather than being invented into the model."""
    service, _, _ = detect_and_load(str(_FIXTURE))
    allowed = {"name", "summary", "description", "parent", "kind"}
    for tag in service.tags:
        assert set(tag) <= allowed


def test_a_tag_parent_that_names_nothing_is_reported(tmp_path: Path) -> None:
    """A dangling parent is a navigation branch that cannot be built.

    Reported rather than repaired: guessing which tag was meant would be
    inventing structure the document does not have.
    """
    doc = _base()
    doc["tags"].append({"name": "orphan", "parent": "does-not-exist"})
    _, findings = _load_doc(doc, tmp_path)
    assert "SPEC-TAG-PARENT-UNKNOWN" in {f.rule_id for f in findings}


# --------------------------------------------------------------- security


def test_oauth_scopes_are_populated_at_last() -> None:
    """`SecurityScheme.scopes` was declared by the model and never filled.

    The parser read `flows` for nothing, so scope coverage reporting had no
    data to work from for any contract in any version.
    """
    service, _, _ = detect_and_load(str(_FIXTURE))
    scheme = service.security_schemes["oauth"]
    assert scheme.scopes == {
        "catalog:read": "Read the catalog",
        "catalog:write": "Modify the catalog",
    }


def test_the_device_authorization_flow_is_recognised() -> None:
    service, _, _ = detect_and_load(str(_FIXTURE))
    scheme = service.security_schemes["oauth"]
    assert set(scheme.oauth_flows) == {"authorizationCode", "deviceAuthorization"}
    assert scheme.oauth_flows["deviceAuthorization"] == {"catalog:read": "Read the catalog"}


def test_the_oauth_metadata_url_is_captured() -> None:
    service, _, _ = detect_and_load(str(_FIXTURE))
    assert service.security_schemes["oauth"].metadata_url == (
        "https://auth.example.com/.well-known/oauth-authorization-server"
    )


def test_an_undefined_oauth_flow_is_reported(tmp_path: Path) -> None:
    doc = _base()
    doc["components"]["securitySchemes"]["oauth"]["flows"]["telepathy"] = {"scopes": {}}
    _, findings = _load_doc(doc, tmp_path)
    assert "SPEC-OAUTH-FLOW-UNKNOWN" in {f.rule_id for f in findings}


# ------------------------------------------------------------ regressions


@pytest.mark.parametrize("fixture", ["apis/crud/openapi.yaml", "apis/versioned/v1.yaml"])
def test_existing_documents_are_unaffected(fixture: str) -> None:
    """3.2 support must not change how a 3.0 or 3.1 contract loads."""
    service, findings, _ = detect_and_load(str(_ROOT / "fixtures" / fixture))
    assert service.operations
    assert "SPEC-VERSION-UNSUPPORTED" not in {f.rule_id for f in findings}


def test_the_parser_reports_no_error_findings_on_the_fixture() -> None:
    parser = OpenApiParser(str(_FIXTURE))
    assert parser.findings == []
    _, findings, _ = detect_and_load(str(_FIXTURE))
    assert [f for f in findings if f.severity.value == "ERROR"] == []
