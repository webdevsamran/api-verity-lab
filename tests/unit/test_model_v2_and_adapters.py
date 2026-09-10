"""The Swagger 2.0 and AsyncAPI adapters, and lifecycle transitions.

This file also tested `core/model_v2.py` -- entity ids, canonical hashes,
artifact migration, bundles and a second CODEOWNERS reader -- until that module
was deleted. Every part of it was a parallel implementation of something this
project already ships, and the ownership half got the CODEOWNERS matching rules
wrong. See the commit that removed it.
"""

from __future__ import annotations

import json
from pathlib import Path

from apiverity.core.model import LIFECYCLE_TRANSITIONS, LifecycleState, Operation, OperationKind
from apiverity.specs.asyncapi import load_asyncapi
from apiverity.specs.loader import detect_and_load
from apiverity.specs.swagger2 import load_swagger2

FIXTURES = Path(__file__).parent.parent / "fixtures"


SWAGGER2_DOC = """
swagger: "2.0"
info:
  title: Legacy API
  version: 1.2.3
host: api.example.com
basePath: /v1
schemes: [https]
consumes: [application/json]
produces: [application/json]
paths:
  /users/{id}:
    get:
      operationId: getUser
      parameters:
        - name: id
          in: path
          required: true
          type: integer
      responses:
        "200":
          description: OK
          schema:
            $ref: "#/definitions/User"
    post:
      operationId: createUser
      parameters:
        - name: body
          in: body
          required: true
          schema:
            $ref: "#/definitions/User"
      responses:
        "201":
          description: Created
definitions:
  User:
    type: object
    required: [id]
    properties:
      id:
        type: integer
      email:
        type: string
securityDefinitions:
  key:
    type: apiKey
    in: header
    name: X-Api-Key
"""

ASYNCAPI_DOC = """
asyncapi: "2.6.0"
info:
  title: Orders Events
  version: 2.0.0
servers:
  production:
    url: kafka://broker.internal:9092
    protocol: kafka
channels:
  orders.created:
    publish:
      operationId: onOrderCreated
      message:
        name: OrderCreated
        payload:
          type: object
          required: [orderId]
          properties:
            orderId:
              type: string
"""


def _write(tmp_path: Path, text: str, name: str) -> str:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


# --- Swagger 2.0 -------------------------------------------------------------


class TestSwagger2:
    def test_parses_operations(self, tmp_path: Path) -> None:
        svc, _findings = load_swagger2(_write(tmp_path, SWAGGER2_DOC, "swagger.yaml"))
        assert svc.title == "Legacy API"
        assert svc.version == "1.2.3"
        keys = svc.operation_keys()
        assert "GET /users/{id}" in keys and "POST /users/{id}" in keys
        get_op = svc.find_operation("GET /users/{id}")
        assert get_op is not None
        assert get_op.parameters[0].schema_node is not None
        assert get_op.parameters[0].schema_node.type == "integer"
        assert get_op.responses[0].content["application/json"].properties["id"].type == "integer"

    def test_body_param_becomes_request_body(self, tmp_path: Path) -> None:
        svc, _ = load_swagger2(_write(tmp_path, SWAGGER2_DOC, "swagger.yaml"))
        op = svc.find_operation("POST /users/{id}")
        assert op is not None and op.request_body is not None
        schema = op.request_body.content["application/json"]
        assert schema.properties["email"].type == "string"

    def test_server_synthesized_with_finding(self, tmp_path: Path) -> None:
        svc, findings = load_swagger2(_write(tmp_path, SWAGGER2_DOC, "swagger.yaml"))
        assert svc.servers[0].url == "https://api.example.com/v1"
        assert any(f.rule_id == "SWAGGER2-SERVER-SYNTHESIZED" for f in findings)

    def test_security_scheme_mapped(self, tmp_path: Path) -> None:
        svc, _ = load_swagger2(_write(tmp_path, SWAGGER2_DOC, "swagger.yaml"))
        assert "key" in svc.security_schemes
        assert svc.security_schemes["key"].type == "apiKey"

    def test_loader_detects_swagger2(self, tmp_path: Path) -> None:
        src = _write(tmp_path, SWAGGER2_DOC, "legacy.yaml")
        svc, _, plugin = detect_and_load(src)
        assert svc.protocol.value == "openapi"
        assert type(plugin).__name__ == "Swagger2SpecPlugin"


# --- AsyncAPI ----------------------------------------------------------------


class TestAsyncApi:
    def test_channel_message_normalized(self, tmp_path: Path) -> None:
        svc, _findings = load_asyncapi(_write(tmp_path, ASYNCAPI_DOC, "orders.yaml"))
        assert svc.protocol.value == "asyncapi"
        assert len(svc.operations) == 1
        op = svc.operations[0]
        assert op.kind == OperationKind.EVENT
        assert op.channel == "orders.created"
        assert op.message_name == "OrderCreated"
        # `direction` is normalized to the application's point of view, so an
        # AsyncAPI 2 `publish` -- which describes messages the application
        # *consumes* -- reads as "receive". The word the document used is kept
        # separately. Without this, a 2.x document and its own 3.x migration
        # compare as two unrelated contracts.
        assert op.direction == "receive"
        assert op.source_action == "publish"
        assert op.request_body is not None
        schema = op.request_body.content["application/json"]
        assert (
            schema.properties["orderId"].type == "integer"
            or schema.properties["orderId"].type == "string"
        )

    def test_servers_parsed(self, tmp_path: Path) -> None:
        svc, _ = load_asyncapi(_write(tmp_path, ASYNCAPI_DOC, "orders.yaml"))
        assert svc.servers[0].url.startswith("kafka://")

    def test_loader_detects_asyncapi(self, tmp_path: Path) -> None:
        src = _write(tmp_path, ASYNCAPI_DOC, "events.yaml")
        svc, _, plugin = detect_and_load(src)
        assert svc.protocol.value == "asyncapi"
        assert type(plugin).__name__ == "AsyncApiSpecPlugin"


# --- Protocol v2 -------------------------------------------------------------


class TestLifecycle:
    def test_transition_rules(self) -> None:
        assert LifecycleState.STABLE in LIFECYCLE_TRANSITIONS[LifecycleState.BETA]
        assert LifecycleState.EXPERIMENTAL not in LIFECYCLE_TRANSITIONS[LifecycleState.STABLE]
        assert LIFECYCLE_TRANSITIONS[LifecycleState.RETIRED] == set()

    def test_deprecation_metadata_roundtrip(self) -> None:
        from apiverity.core.model import DeprecationInfo

        op = Operation(
            method="GET",
            path="/old",
            lifecycle_state=LifecycleState.DEPRECATED,
            deprecation=DeprecationInfo(announced_date="2026-01-01", sunset_date="2026-12-31"),
        )
        data = json.loads(op.model_dump_json())
        assert data["deprecation"]["sunset_date"] == "2026-12-31"
