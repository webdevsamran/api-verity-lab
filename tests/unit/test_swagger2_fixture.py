"""The Swagger 2.0 adapter had no fixture, in a repo whose tables graded it.

`PROTOCOL_SUPPORT.md` carried a Swagger 2.0 column with eight graded cells and
a paragraph saying imports were "normalized into the protocol-v2 model with
explicit loss/ambiguity findings". Two things were wrong with that.

The mechanism named was not the mechanism involved: `core/model_v2.py` is
about stable entity ids, canonical hashes, artifact migration and contract
bundles, and `specs/swagger2.py` does not import it. And there was no Swagger
2.0 document anywhere in `fixtures/`, so nothing measured the column at all.

What is true is simpler and is what the page says now: a 2.0 document compiles
into the *same* normalized model as OpenAPI 3, so the column is the OpenAPI
column minus what the adapter reports as lost. These tests are that claim,
checked.
"""

from __future__ import annotations

from pathlib import Path

from apiverity.core.model import ParameterLocation, Protocol
from apiverity.specs.loader import detect_and_load
from apiverity.specs.swagger2 import Swagger2SpecPlugin

_ROOT = Path(__file__).resolve().parents[2]
_FIXTURE = _ROOT / "fixtures" / "apis" / "swagger2" / "petstore.yaml"


def _load():
    return detect_and_load(str(_FIXTURE))


def test_the_adapter_claims_the_document() -> None:
    _service, _findings, plugin = _load()
    assert isinstance(plugin, Swagger2SpecPlugin)


def test_it_compiles_into_the_same_model_as_openapi() -> None:
    """The whole basis of the column: not a parallel model, the same one."""
    service, _findings, _plugin = _load()
    assert service.protocol is Protocol.OPENAPI
    assert service.operation_keys() == ["GET /pets", "POST /pets", "GET /pets/{petId}"]


def test_host_basepath_and_schemes_become_one_server() -> None:
    service, _findings, _plugin = _load()
    assert [s.url for s in service.servers] == ["https://petstore.example.com/v1"]


def test_a_body_parameter_becomes_a_request_body() -> None:
    """2.0's `in: body` has no OpenAPI 3 parameter equivalent. Leaving it as a
    parameter would put the payload where no engine downstream looks for it."""
    service, _findings, _plugin = _load()
    op = service.find_operation("POST /pets")
    assert op is not None and op.request_body is not None
    assert op.request_body.required
    assert "application/json" in op.request_body.content
    assert not [p for p in op.parameters if p.location is ParameterLocation.QUERY]


def test_definitions_resolve_into_schemas() -> None:
    """A `$ref` into `#/definitions` that resolved to nothing would leave the
    differ comparing two absences -- the failure mode the bundler exists for."""
    service, _findings, _plugin = _load()
    op = service.find_operation("POST /pets")
    assert op is not None and op.request_body is not None
    body = op.request_body.content["application/json"]
    assert sorted(body.properties) == ["name", "tag"]
    assert body.required == ["name"]


def test_parameter_constraints_survive() -> None:
    service, _findings, _plugin = _load()
    op = service.find_operation("GET /pets")
    assert op is not None
    limit = next(p for p in op.parameters if p.name == "limit")
    assert limit.schema_node is not None
    assert (limit.schema_node.minimum, limit.schema_node.maximum) == (1, 100)
    status = next(p for p in op.parameters if p.name == "status")
    assert status.schema_node is not None
    assert status.schema_node.enum == ["available", "pending", "sold"]


def test_security_definitions_become_schemes() -> None:
    service, _findings, _plugin = _load()
    assert sorted(service.security_schemes) == ["apiKey", "petstoreOauth"]
    assert [r.scheme_name for r in service.global_security] == ["apiKey"]


# ------------------------------------------------------------ what is lost


def test_the_losses_are_reported_rather_than_absorbed() -> None:
    """The column reads "as OpenAPI, minus what the adapter reports". If the
    adapter reported nothing, that sentence would be doing the work."""
    _service, findings, _plugin = _load()
    ids = {f.rule_id for f in findings}
    assert "SWAGGER2-SERVER-SYNTHESIZED" in ids
    assert "SWAGGER2-OAUTH-FLOW-LOSSY" in ids


def test_the_oauth_loss_names_the_scheme_it_flattened() -> None:
    """2.0 declares one flow per definition and OpenAPI 3 nests flows under
    one scheme, so the flattening loses which flow was which."""
    _service, findings, _plugin = _load()
    finding = next(f for f in findings if f.rule_id == "SWAGGER2-OAUTH-FLOW-LOSSY")
    assert "petstoreOauth" in finding.message


def test_the_document_still_analyses_end_to_end() -> None:
    """The point of compiling into the shared model. If any of this raised,
    the eight cells would be describing something that does not run."""
    from apiverity.diff.engine import diff_services
    from apiverity.rules.breaking import evaluate_breaking
    from apiverity.security import run_security_checks

    service, _findings, _plugin = _load()
    assert run_security_checks(service) is not None
    assert evaluate_breaking(diff_services(service, service)) == []
