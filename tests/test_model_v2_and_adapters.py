"""Tests for protocol v2 (entity IDs, hashes, migrations, bundles) and the
Swagger 2.0 / AsyncAPI adapters."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from apiverity.core.model import LIFECYCLE_TRANSITIONS, LifecycleState, Operation, OperationKind
from apiverity.core.model_v2 import (
    ARTIFACT_SCHEMA_VERSION,
    ContractBundle,
    apply_ownership,
    build_catalog_index,
    entity_hash,
    fingerprint_findings,
    load_ownership_mapping,
    migrate_artifact,
    operation_entity_id,
    service_id,
)
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
        assert op.direction == "publish"
        assert op.request_body is not None
        schema = op.request_body.content["application/json"]
        assert schema.properties["orderId"].type == "integer" or schema.properties[
            "orderId"
        ].type == "string"

    def test_servers_parsed(self, tmp_path: Path) -> None:
        svc, _ = load_asyncapi(_write(tmp_path, ASYNCAPI_DOC, "orders.yaml"))
        assert svc.servers[0].url.startswith("kafka://")

    def test_loader_detects_asyncapi(self, tmp_path: Path) -> None:
        src = _write(tmp_path, ASYNCAPI_DOC, "events.yaml")
        svc, _, plugin = detect_and_load(src)
        assert svc.protocol.value == "asyncapi"
        assert type(plugin).__name__ == "AsyncApiSpecPlugin"


# --- Protocol v2 -------------------------------------------------------------


class TestEntityIdsAndHashes:
    def test_operation_entity_id_stable_across_reorder(self) -> None:
        a = Operation(method="GET", path="/users")
        b = Operation(method="get", path="/users", summary="x")
        assert operation_entity_id(a) == operation_entity_id(b)
        assert operation_entity_id(a).startswith("op:http:get-users")

    def test_service_id_includes_version(self) -> None:
        from apiverity.core.model import Protocol, Service

        s = Service(title="Users API", version="1.0.0", protocol=Protocol.OPENAPI)
        assert service_id(s) == "svc:openapi:users-api:1.0.0"

    def test_entity_hash_excludes_source_location(self) -> None:
        from apiverity.core.model import SourceLocation

        a = Operation(method="GET", path="/users")
        b = Operation(
            method="GET",
            path="/users",
            source_location=SourceLocation(file="x.yaml", line=9),
        )
        assert entity_hash(a) == entity_hash(b)

    def test_fingerprint_dedupes_repeats(self) -> None:
        base = {"rule_id": "R1", "severity": "ERROR", "operation_key": "GET /a", "message": "m"}
        dup = dict(base)
        other = {**base, "rule_id": "R2"}
        prints = fingerprint_findings([base, dup, other])
        assert prints[0] == prints[1] != prints[2]


class TestMigration:
    def test_migrates_v1_artifact(self) -> None:
        artifact = {
            "result_schema_version": "1.0",
            "findings": [
                {"rule_id": "R1", "severity": "ERROR", "operation_key": "GET /a", "message": "m"}
            ],
        }
        migrated, rec = migrate_artifact(artifact)
        assert migrated["artifact_schema_version"] == ARTIFACT_SCHEMA_VERSION
        assert migrated["superseded_schema_version"] == "1.0"
        assert migrated["findings"][0]["fingerprint"]
        assert rec.lossy is False

    def test_current_version_is_noop(self) -> None:
        artifact = {"artifact_schema_version": ARTIFACT_SCHEMA_VERSION}
        migrated, rec = migrate_artifact(artifact)
        assert migrated == artifact
        assert rec.notes == ["already current"]

    def test_unsupported_version_raises(self) -> None:
        with pytest.raises(ValueError):
            migrate_artifact({"result_schema_version": "9.9"})


class TestBundlesCatalogOwnership:
    def _service(self, title: str, product: str | None, team: str | None, file: str):
        from apiverity.core.model import Protocol, Service

        return Service(
            title=title,
            version="1.0.0",
            protocol=Protocol.OPENAPI,
            product=product,
            team=team,
            source_file=file,
        )

    def test_bundle_from_services(self) -> None:
        from apiverity.core.model import Protocol, Service

        svcs = [
            Service(title="A", version="1.0.0", protocol=Protocol.OPENAPI),
            Service(title="B", version="2.0.0", protocol=Protocol.GRPC),
        ]
        bundle = ContractBundle.from_services("platform", "2026.08", svcs)
        data = bundle.to_dict()
        assert data["name"] == "platform"
        assert {e.protocol for e in bundle.entries} == {"openapi", "grpc"}

    def test_catalog_grouping(self) -> None:
        svcs = [
            self._service("A", "checkout", "payments", "specs/a.yaml"),
            self._service("B", "checkout", "identity", "specs/b.yaml"),
            self._service("C", None, None, "specs/c.yaml"),
        ]
        by_product = build_catalog_index(svcs, group_by="product")
        assert set(by_product) == {"checkout", "ungrouped"}
        by_team = build_catalog_index(svcs, group_by="team")
        assert set(by_team) == {"payments", "identity", "ungrouped"}

    def test_ownership_mapping_applied(self, tmp_path: Path) -> None:
        owner_file = tmp_path / "OWNERS"
        owner_file.write_text("# comment\nspecs/payments/** @payments-team", encoding="utf-8")
        mapping = load_ownership_mapping(owner_file)
        svc = self._service("Pay", None, None, "specs\\payments\\api.yaml")
        applied = apply_ownership([svc], mapping)
        assert applied == ["specs/payments/**"]
        assert svc.owner == "payments-team"


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
