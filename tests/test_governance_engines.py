"""Tests for lint, policy packs, suppressions and deepened compatibility."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from apiverity.core.model import (
    DeprecationInfo,
    Finding,
    Operation,
    Parameter,
    ParameterLocation,
    Protocol,
    RequestBody,
    Response,
    SchemaNode,
    SecurityScheme,
    Server,
    Service,
    Severity,
)
from apiverity.diff.compat import analyze_compat
from apiverity.rules.lint import lint_service
from apiverity.rules.policy import PolicyEngine
from apiverity.rules.suppressions import (
    Suppression,
    apply_suppressions,
    expired_suppression_findings,
    load_suppressions,
)


def _svc(**kw) -> Service:
    base: dict = {
        "title": "T",
        "version": "1.0.0",
        "protocol": Protocol.OPENAPI,
        "servers": [Server(url="https://api.example.com")],
    }
    base.update(kw)
    return Service(**base)


def _op(method: str = "GET", path: str = "/a", **kw) -> Operation:
    base: dict = {"method": method, "path": path, "responses": [Response(status="200")]}
    base.update(kw)
    return Operation(**base)


# --- Lint ---------------------------------------------------------------------


class TestLint:
    def test_duplicate_operation_ids(self) -> None:
        svc = _svc(operations=[_op(operation_id="same"), _op(path="/b", operation_id="same")])
        ids = [f.rule_id for f in lint_service(svc)]
        assert "LINT-DUP-OPID" in ids

    def test_no_responses_flagged(self) -> None:
        svc = _svc(operations=[_op(responses=[])])
        ids = [f.rule_id for f in lint_service(svc)]
        assert "LINT-NO-RESPONSES" in ids

    def test_contradictory_requiredness(self) -> None:
        schema = SchemaNode(type="object", required=["ghost"], properties={"real": SchemaNode()})
        svc = _svc(operations=[_op(request_body=RequestBody(content={"application/json": schema}))])
        ids = [f.rule_id for f in lint_service(svc)]
        assert "LINT-CONTRADICTORY-REQUIRED" in ids

    def test_ambiguous_composition(self) -> None:
        branch_a = SchemaNode(type="object")
        branch_b = SchemaNode(type="string")
        union = SchemaNode(one_of=[branch_a, branch_b])
        svc = _svc(operations=[_op(request_body=RequestBody(content={"application/json": union}))])
        ids = [f.rule_id for f in lint_service(svc)]
        assert "LINT-AMBIGUOUS-COMPOSITION" in ids

    def test_invalid_example_detected(self) -> None:
        schema = SchemaNode(type="object", required=["id"], properties={"id": SchemaNode(type="integer")})
        op = _op(
            request_body=RequestBody(content={"application/json": schema}),
            examples=[],  # examples live on operation; inject via model below
        )
        from apiverity.core.model import Example

        op.examples = [Example(name="bad", value={"id": "not-an-int"})]
        svc = _svc(operations=[op])
        ids = [f.rule_id for f in lint_service(svc)]
        assert "LINT-INVALID-EXAMPLE" in ids


# --- Policy packs ---------------------------------------------------------------


class TestPolicy:
    def test_default_pack_runs(self) -> None:
        engine = PolicyEngine()
        findings = engine.evaluate(_svc(servers=[Server(url="http://insecure.example.com")]))
        ids = {f.rule_id for f in findings}
        assert "GOV-INSECURE-SERVER" in ids

    def test_deprecation_metadata_rule(self) -> None:
        op = _op(deprecated=True)
        svc = _svc(operations=[op])
        ids = {f.rule_id for f in PolicyEngine().evaluate(svc)}
        assert "GOV-DEPRECATION-METADATA" in ids
        # with metadata but no sunset date -> GOV-SUNSET-MISSING
        op2 = _op(path="/c", deprecated=True, deprecation=DeprecationInfo(announced_date="2026-01-01"))
        ids2 = {f.rule_id for f in PolicyEngine().evaluate(_svc(operations=[op2]))}
        assert "GOV-SUNSET-MISSING" in ids2

    def test_unused_security_scheme(self) -> None:
        svc = _svc(security_schemes={"dead": SecurityScheme(name="dead", type="apiKey")})
        ids = {f.rule_id for f in PolicyEngine().evaluate(svc)}
        assert "GOV-UNUSED-SECURITY-SCHEME" in ids

    def test_protocol_applicability_filtering(self) -> None:
        grpc_svc = Service(title="G", version="1", protocol=Protocol.GRPC)
        findings = PolicyEngine().evaluate(grpc_svc)
        assert all(f.rule_id != "GOV-MISSING-OPERATION-ID" for f in findings)

    def test_crashing_rule_is_isolated(self) -> None:
        from apiverity.rules.policy import RuleDefinition, RulePack

        def boom(svc):
            raise RuntimeError("boom")

        pack = RulePack(
            name="crashy",
            version="1.0.0",
            description="d",
            rules=(
                RuleDefinition(rule_id="CRASH", severity=Severity.WARN, rationale="r", remediation="x", check=boom),
            ),
        )
        findings = PolicyEngine(packs=[pack]).evaluate(_svc())
        assert any(f.rule_id == "POLICY-RULE-CRASHED" for f in findings)

    def test_duplicate_rule_ids_rejected(self) -> None:
        import pytest

        from apiverity.rules.policy import RuleDefinition, RulePack

        rule = lambda svc: []  # noqa: E731
        mk = lambda name: RulePack(  # noqa: E731
            name=name,
            version="1.0.0",
            description="d",
            rules=(RuleDefinition(rule_id="X", severity=Severity.INFO, rationale="r", remediation="x", check=rule),),
        )
        with pytest.raises(ValueError):
            PolicyEngine(packs=[mk("a"), mk("b")])


# --- Suppressions ----------------------------------------------------------------


class TestSuppressions:
    def test_load_and_apply(self, tmp_path: Path) -> None:
        path = tmp_path / "suppressions.json"
        path.write_text(
            json.dumps(
                {
                    "suppressions": [
                        {
                            "rule_id": "LINT-DUP-OPID",
                            "operation_key": "GET /a",
                            "owner": "team-core",
                            "reason": "legacy client depends on it",
                            "expires": "2099-12-31",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        sups = load_suppressions(path)
        findings = [
            Finding(rule_id="LINT-DUP-OPID", severity=Severity.ERROR, message="m", operation_key="GET /a"),
            Finding(rule_id="LINT-DUP-OPID", severity=Severity.ERROR, message="m", operation_key="GET /b"),
        ]
        result = apply_suppressions(findings, sups, today=date(2026, 1, 1))
        assert len(result.active) == 1
        assert result.active[0].operation_key == "GET /b"
        assert len(result.suppressed) == 1
        assert result.suppressed[0][1].owner == "team-core"

    def test_expired_suppression_fails_open(self) -> None:
        sups = [Suppression(rule_id="R", owner="o", reason="r", expires="2020-01-01")]
        findings = [Finding(rule_id="R", severity=Severity.WARN, message="m")]
        result = apply_suppressions(findings, sups, today=date(2026, 1, 1))
        assert len(result.active) == 1
        expired_findings = expired_suppression_findings(result.expired)
        assert expired_findings[0].rule_id == "SUPPRESSION-EXPIRED"

    def test_malformed_expiry_fails_closed(self) -> None:
        sups = [Suppression(rule_id="R", expires="not-a-date")]
        findings = [Finding(rule_id="R", severity=Severity.WARN, message="m")]
        result = apply_suppressions(findings, sups)
        assert len(result.active) == 1


# --- Deepened compatibility --------------------------------------------------------


class TestCompatAnalyzer:
    def test_status_code_removal(self) -> None:
        old = _svc(operations=[_op(responses=[Response(status="200"), Response(status="404")])])
        new = _svc(operations=[_op(responses=[Response(status="200")])])
        findings = analyze_compat(old, new)
        removed = [f for f in findings if f.rule_id == "COMPAT-STATUS-REMOVED"]
        assert len(removed) == 1
        # Removing a documented error status is informational; a 2xx outcome is riskier.
        assert removed[0].severity == Severity.INFO

    def test_success_status_removal_is_riskier(self) -> None:
        old = _svc(operations=[_op(responses=[Response(status="200"), Response(status="201")])])
        new = _svc(operations=[_op(responses=[Response(status="200")])])
        findings = analyze_compat(old, new)
        removed = [f for f in findings if f.rule_id == "COMPAT-STATUS-REMOVED"]
        assert removed and removed[0].severity == Severity.WARN

    def test_media_type_removed(self) -> None:
        old = _svc(
            operations=[
                _op(request_body=RequestBody(content={"application/xml": SchemaNode(type="object")}))
            ]
        )
        new = _svc(operations=[_op()])
        findings = analyze_compat(old, new)
        assert any(f.rule_id == "COMPAT-MEDIA-REMOVED" for f in findings)

    def test_required_header_added(self) -> None:
        hdr = Parameter(name="X-Trace", location=ParameterLocation.HEADER, required=True)
        old = _svc(operations=[_op()])
        new = _svc(operations=[_op(parameters=[hdr])])
        findings = analyze_compat(old, new)
        assert any(f.rule_id == "COMPAT-HEADER-REQUIRED" for f in findings)

    def test_security_scheme_removed(self) -> None:
        old = _svc(security_schemes={"k": SecurityScheme(name="k", type="apiKey")})
        new = _svc()
        findings = analyze_compat(old, new)
        assert any(f.rule_id == "COMPAT-SECURITY-SCHEME-REMOVED" for f in findings)

    def test_server_change_environment_aware(self) -> None:
        old = _svc(servers=[Server(url="https://localhost:9000")])
        new = _svc(servers=[Server(url="https://api.example.com")])
        findings = analyze_compat(old, new)
        removed = [f for f in findings if f.rule_id == "COMPAT-SERVER-REMOVED"]
        assert removed and removed[0].severity == Severity.WARN  # local target removal is low risk

    def test_idempotency_revoked(self) -> None:
        old = _svc(operations=[_op(idempotent=True)])
        new = _svc(operations=[_op(idempotent=False)])
        findings = analyze_compat(old, new)
        assert any(f.rule_id == "COMPAT-IDEMPOTENCY-REVOKED" for f in findings)
