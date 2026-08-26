"""Tests for the defensive security pack, OAuth scope coverage and the
service virtualization workspace."""

from __future__ import annotations

import httpx

from apiverity.core.model import (
    Example,
    Operation,
    Protocol,
    RequestBody,
    SchemaNode,
    SecurityRequirement,
    SecurityScheme,
    Server,
    Service,
)
from apiverity.mock.virtualization import workspace_from_services
from apiverity.rules.policy import PolicyEngine
from apiverity.security.oauth_scopes import analyze_scope_coverage
from apiverity.security.packs import SECURITY_PACK


def _svc(**kw) -> Service:
    base: dict = {
        "title": "T",
        "version": "1.0.0",
        "protocol": Protocol.OPENAPI,
        "servers": [Server(url="https://api.example.com")],
        "operations": [Operation(method="GET", path="/a", responses=[])],
    }
    base.update(kw)
    return Service(**base)


class TestSecurityPack:
    def test_missing_auth_declared(self) -> None:
        findings = PolicyEngine(packs=[SECURITY_PACK]).evaluate(_svc())
        assert any(f.rule_id == "SEC-NO-AUTH-DECLARED" for f in findings)

    def test_global_security_satisfies(self) -> None:
        svc = _svc(
            global_security=[SecurityRequirement(scheme_name="k")],
            security_schemes={"k": SecurityScheme(name="k", type="apiKey")},
        )
        findings = PolicyEngine(packs=[SECURITY_PACK]).evaluate(svc)
        assert not any(f.rule_id == "SEC-NO-AUTH-DECLARED" for f in findings)

    def test_secret_in_example_detected(self) -> None:
        op = Operation(
            method="POST",
            path="/login",
            responses=[],
            examples=[Example(name="creds", value={"api_key": "sk-live-abcdef1234567890ab"})],
        )
        svc = _svc(operations=[op])
        findings = PolicyEngine(packs=[SECURITY_PACK]).evaluate(svc)
        assert any(f.rule_id == "SEC-SECRET-IN-CONTRACT" for f in findings)

    def test_sensitive_field_flagged(self) -> None:
        schema = SchemaNode(
            type="object",
            properties={"password": SchemaNode(type="string")},
        )
        op = Operation(
            method="POST",
            path="/u",
            request_body=RequestBody(content={"application/json": schema}),
        )
        svc = _svc(operations=[op])
        findings = PolicyEngine(packs=[SECURITY_PACK]).evaluate(svc)
        assert any(f.rule_id == "SEC-SENSITIVE-FIELD" for f in findings)

    def test_cors_wildcard(self) -> None:
        op = Operation(
            method="GET",
            path="/c",
            examples=[
                Example(name="resp", value={"headers": {"Access-Control-Allow-Origin": "*"}})
            ],
        )
        svc = _svc(operations=[op])
        findings = PolicyEngine(packs=[SECURITY_PACK]).evaluate(svc)
        assert any(f.rule_id == "SEC-CORS-WILDCARD" for f in findings)


class TestOAuthScopes:
    def test_scope_coverage(self) -> None:
        svc = _svc(
            security_schemes={
                "oauth": SecurityScheme(
                    name="oauth",
                    type="oauth2",
                    scopes={"read:items": "Read items", "write:items": "Write items"},
                )
            },
            global_security=[SecurityRequirement(scheme_name="oauth", scopes=["read:items"])],
            operations=[
                Operation(
                    method="GET",
                    path="/items",
                    security=[SecurityRequirement(scheme_name="oauth", scopes=["read:items"])],
                ),
                Operation(
                    method="POST",
                    path="/items",
                    security=[
                        SecurityRequirement(scheme_name="oauth", scopes=["admin"])
                    ],  # undeclared
                ),
            ],
        )
        cov = analyze_scope_coverage(svc)
        assert cov.declared_scopes == {"read:items", "write:items"}
        assert "undeclared_but_used" in cov.summary()
        assert cov.undeclared_used == {"admin"}
        assert cov.unused_declared == {"write:items"}
        assert cov.used_scopes["read:items"] == ["GET /items"]


class TestVirtualization:
    def _service(self, title: str, path: str) -> Service:
        return Service(
            title=title,
            version="1.0.0",
            protocol=Protocol.OPENAPI,
            servers=[Server(url="http://localhost")],
            operations=[Operation(method="GET", path=path, responses=[])],
        )

    def test_workspace_starts_and_stops(self) -> None:
        ws = workspace_from_services(
            "bundle",
            [self._service("Catalog", "/catalog"), self._service("Orders", "/orders")],
            seed=42,
        )
        with ws:
            urls = {name: ws.base_url(name) for name in ("Catalog", "Orders")}
            assert all(u.startswith("http://127.0.0.1:") for u in urls.values())
            for name, url in urls.items():
                resp = httpx.get(url + ("/catalog" if name == "Catalog" else "/orders"))
                assert resp.status_code == 200
        assert ws.servers == {}

    def test_unknown_service_raises(self) -> None:
        ws = workspace_from_services("b", [self._service("A", "/a")])
        with ws:
            try:
                ws.base_url("nope")
                raised = False
            except KeyError:
                raised = True
            assert raised
