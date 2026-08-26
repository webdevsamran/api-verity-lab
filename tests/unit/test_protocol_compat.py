"""Protocol-specific compatibility: GraphQL breaking/dangerous and gRPC wire rules."""

from __future__ import annotations

from pathlib import Path

import pytest

from apiverity.core.model import (
    Operation,
    OperationKind,
    Parameter,
    ParameterLocation,
    Protocol,
    RequestBody,
    Response,
    SchemaNode,
    Service,
)
from apiverity.diff.protocol_compat import analyze_protocol_compat


def _gql_op(root: str, field: str, *, args=None, ret=None) -> Operation:
    return Operation(
        kind=OperationKind.GRAPHQL_FIELD,
        rpc_name=field,
        service_name=root,
        summary=f"{root}.{field}",
        parameters=args or [],
        responses=[Response(status="OK", content={"application/graphql": ret})] if ret else [],
    )


def _svc(protocol: Protocol, ops: list[Operation]) -> Service:
    return Service(title="T", version="1", protocol=protocol, operations=ops)


def _arg(name: str, required: bool) -> Parameter:
    return Parameter(name=name, location=ParameterLocation.QUERY, required=required)


def _ret(title: str, nullable: bool) -> SchemaNode:
    return SchemaNode(type="object", title=title, nullable=nullable)


class TestGraphqlCompat:
    def test_field_removed_is_breaking(self) -> None:
        old = _svc(Protocol.GRAPHQL, [_gql_op("Query", "users")])
        new = _svc(Protocol.GRAPHQL, [])
        ids = [f.rule_id for f in analyze_protocol_compat(old, new)]
        assert "GQL-FIELD-REMOVED" in ids

    def test_field_added_is_dangerous_not_breaking(self) -> None:
        old = _svc(Protocol.GRAPHQL, [])
        new = _svc(Protocol.GRAPHQL, [_gql_op("Query", "users")])
        findings = analyze_protocol_compat(old, new)
        assert all(f.severity.value != "ERROR" for f in findings)
        assert any(f.rule_id == "GQL-DANGEROUS-FIELD-ADDED" for f in findings)

    def test_required_argument_added_breaks(self) -> None:
        old = _svc(Protocol.GRAPHQL, [_gql_op("Query", "user")])
        new = _svc(
            Protocol.GRAPHQL,
            [_gql_op("Query", "user", args=[_arg("id", required=True)])],
        )
        ids = [f.rule_id for f in analyze_protocol_compat(old, new)]
        assert "GQL-REQUIRED-ARGUMENT-ADDED" in ids

    def test_argument_removed_breaks(self) -> None:
        old = _svc(Protocol.GRAPHQL, [_gql_op("Query", "user", args=[_arg("id", True)])])
        new = _svc(Protocol.GRAPHQL, [_gql_op("Query", "user")])
        ids = [f.rule_id for f in analyze_protocol_compat(old, new)]
        assert "GQL-ARGUMENT-REMOVED" in ids

    def test_return_nonnull_to_nullable_is_dangerous(self) -> None:
        # User! -> User : not strictly breaking but clients may assume non-null
        old = _svc(Protocol.GRAPHQL, [_gql_op("Query", "user", ret=_ret("User", False))])
        new = _svc(Protocol.GRAPHQL, [_gql_op("Query", "user", ret=_ret("User", True))])
        findings = analyze_protocol_compat(old, new)
        assert any(f.rule_id == "GQL-DANGEROUS-RETURN-RELAXED" for f in findings)

    def test_return_nullable_to_nonnull_breaks(self) -> None:
        old = _svc(Protocol.GRAPHQL, [_gql_op("Query", "user", ret=_ret("User", True))])
        new = _svc(Protocol.GRAPHQL, [_gql_op("Query", "user", ret=_ret("User", False))])
        ids = [f.rule_id for f in analyze_protocol_compat(old, new)]
        assert "GQL-RETURN-NONNULL-TIGHTENED" in ids

    def test_openapi_contracts_produce_no_protocol_findings(self) -> None:
        assert analyze_protocol_compat(_svc(Protocol.OPENAPI, []), _svc(Protocol.OPENAPI, [])) == []


class TestGrpcCompat:
    @staticmethod
    def _rpc(svc_name: str, rpc: str, req: SchemaNode | None, resp: SchemaNode | None) -> Operation:
        op = Operation(
            kind=OperationKind.GRPC_RPC,
            rpc_name=rpc,
            service_name=svc_name,
            summary=f"{svc_name}.{rpc}",
        )
        if req is not None:
            op.request_body = RequestBody(required=True, content={"application/x-protobuf": req})
        if resp is not None:
            op.responses.append(Response(status="OK", content={"application/x-protobuf": resp}))
        return op

    def test_rpc_removed_breaks(self) -> None:
        old = _svc(Protocol.GRPC, [self._rpc("Pay", "Charge", None, None)])
        new = _svc(Protocol.GRPC, [])
        ids = [f.rule_id for f in analyze_protocol_compat(old, new)]
        assert "PROTO-RPC-REMOVED" in ids

    def test_message_type_changed_breaks(self) -> None:
        old = _svc(
            Protocol.GRPC,
            [
                self._rpc(
                    "Pay",
                    "Charge",
                    SchemaNode(type="object", title="ChargeReq"),
                    SchemaNode(type="object", title="Receipt"),
                )
            ],
        )
        new = _svc(
            Protocol.GRPC,
            [
                self._rpc(
                    "Pay",
                    "Charge",
                    SchemaNode(type="object", title="ChargeReqV2"),
                    SchemaNode(type="object", title="Receipt"),
                )
            ],
        )
        ids = [f.rule_id for f in analyze_protocol_compat(old, new)]
        assert "PROTO-MESSAGE-TYPE-CHANGED" in ids

    def test_wire_type_change_detected(self) -> None:
        old = _svc(
            Protocol.GRPC,
            [
                self._rpc(
                    "Pay",
                    "Charge",
                    SchemaNode(
                        type="object",
                        title="ChargeReq",
                        properties={"amount": SchemaNode(type="string")},
                    ),
                    None,
                )
            ],
        )
        new = _svc(
            Protocol.GRPC,
            [
                self._rpc(
                    "Pay",
                    "Charge",
                    SchemaNode(
                        type="object",
                        title="ChargeReq",
                        properties={"amount": SchemaNode(type="integer", format="int64")},
                    ),
                    None,
                )
            ],
        )
        ids = [f.rule_id for f in analyze_protocol_compat(old, new)]
        assert "PROTO-WIRE-TYPE-CHANGED" in ids

    def test_int_width_change_warns(self) -> None:
        old = _svc(
            Protocol.GRPC,
            [
                self._rpc(
                    "Pay",
                    "Charge",
                    SchemaNode(
                        type="object",
                        title="Q",
                        properties={"n": SchemaNode(type="integer", format="int32")},
                    ),
                    None,
                )
            ],
        )
        new = _svc(
            Protocol.GRPC,
            [
                self._rpc(
                    "Pay",
                    "Charge",
                    SchemaNode(
                        type="object",
                        title="Q",
                        properties={"n": SchemaNode(type="integer", format="int64")},
                    ),
                    None,
                )
            ],
        )
        findings = analyze_protocol_compat(old, new)
        assert any(f.rule_id == "PROTO-WIRE-WIDTH-CHANGED" for f in findings)
        assert all(f.rule_id != "PROTO-WIRE-TYPE-CHANGED" for f in findings)

    def test_enum_value_removed_breaks(self) -> None:
        old = _svc(
            Protocol.GRPC,
            [
                self._rpc(
                    "Pay",
                    "Status",
                    SchemaNode(
                        type="object",
                        title="S",
                        properties={"state": SchemaNode(type="string", enum=["OK", "FAILED"])},
                    ),
                    None,
                )
            ],
        )
        new = _svc(
            Protocol.GRPC,
            [
                self._rpc(
                    "Pay",
                    "Status",
                    SchemaNode(
                        type="object",
                        title="S",
                        properties={"state": SchemaNode(type="string", enum=["OK"])},
                    ),
                    None,
                )
            ],
        )
        ids = [f.rule_id for f in analyze_protocol_compat(old, new)]
        assert "PROTO-ENUM-VALUE-REMOVED" in ids


class TestLoaderIntegration:
    def test_graphql_sdl_end_to_end_diff(self, tmp_path: Path) -> None:
        pytest.importorskip("graphql")
        from apiverity.specs.graphql import GraphQlSpecPlugin

        v1 = tmp_path / "v1.graphql"
        v2 = tmp_path / "v2.graphql"
        v1.write_text("type Query { user(id: Int!): String userByName(name: String): String }\n")
        v2.write_text(
            "type Query { user(id: Int!, verbose: Boolean): User }\ntype User { id: Int }\n"
        )
        old, _ = GraphQlSpecPlugin().load(str(v1))
        new, _ = GraphQlSpecPlugin().load(str(v2))
        findings = analyze_protocol_compat(old, new)
        ids = [f.rule_id for f in findings]
        assert "GQL-FIELD-REMOVED" in ids  # userByName gone
        assert "GQL-REQUIRED-ARGUMENT-ADDED" not in ids  # id was already required
        dangerous = [f.rule_id for f in findings if f.rule_id.startswith("GQL-DANGEROUS")]
        assert dangerous  # optional verbose arg added + return relaxed to nullable
