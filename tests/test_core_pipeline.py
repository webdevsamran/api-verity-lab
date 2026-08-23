"""Core pipeline tests: parsing, diff, breaking, semver, changelog, security."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from apiverity.core.model import SchemaNode
from apiverity.diff.engine import diff_services
from apiverity.rules.breaking import evaluate_breaking
from apiverity.rules.changelog import generate_changelog
from apiverity.rules.semver import SemverPolicy
from apiverity.security import run_security_checks


def test_openapi_parse_with_source_locations(crud_service):
    assert len(crud_service.operations) == 4
    op = crud_service.find_operation("GET /users")
    assert op is not None and op.source_location.line > 0
    assert op.parameters[0].schema_node.minimum == 1


def test_unresolved_ref_generates_finding(tmp_path):
    lines = [
        "openapi: 3.1.0",
        "info: {title: T, version: 1.0.0}",
        "paths:",
        "  /x:",
        "    get:",
        "      responses:",
        "        '200':",
        "          content:",
        "            application/json:",
        "              schema: {$ref: '#/components/schemas/Missing'}",
    ]
    spec = chr(10).join(lines)
    p = tmp_path / "s.yaml"
    p.write_text(spec, encoding="utf-8")
    from apiverity.specs.loader import detect_and_load

    _, findings, _ = detect_and_load(str(p))
    assert any(f.rule_id == "SPEC-REF-UNRESOLVED" for f in findings)


def test_diff_detects_removals_and_semantics(v1_service, v2_service):
    changes = diff_services(v1_service, v2_service)
    kinds = {c.kind.value for c in changes}
    assert "operation_removed" in kinds
    assert "parameter_requiredness" in kinds
    assert "enum_changed" in kinds


def test_breaking_rules_direction_aware(v1_service, v2_service):
    findings = evaluate_breaking(diff_services(v1_service, v2_service))
    ids = {f.rule_id for f in findings}
    # request narrowing = ERROR; response narrowing = WARN only
    assert "BRK-ENUM-NARROWED-REQUEST" in ids
    assert "BRK-ENUM-NARROWED-RESPONSE" in ids
    sev = {f.rule_id: f.severity.value for f in findings}
    assert sev["BRK-ENUM-NARROWED-REQUEST"] == "ERROR"
    assert sev["BRK-ENUM-NARROWED-RESPONSE"] == "WARN"


def test_semver_major_required(v1_service, v2_service):
    changes = diff_services(v1_service, v2_service)
    findings = evaluate_breaking(changes)
    policy = SemverPolicy("1.2.0", "1.3.0")
    out = policy.evaluate(findings, changes)
    assert any(f.rule_id == "SEMVER-MAJOR-REQUIRED" for f in out)


def test_semver_decrease_flagged():
    policy = SemverPolicy("2.0.0", "1.9.0")
    out = policy.evaluate([], [])
    assert any(f.rule_id == "SEMVER-DECREASE" for f in out)


def test_changelog_markdown_and_html(v1_service, v2_service):
    changes = diff_services(v1_service, v2_service)
    findings = evaluate_breaking(changes)
    md = generate_changelog("T", "1", "2", changes, findings)
    html = generate_changelog("T", "1", "2", changes, findings, fmt="html")
    assert "BREAKING" in md and "<!doctype html>" in html


def test_security_checks(crud_service):
    findings = run_security_checks(crud_service)
    ids = {f.rule_id for f in findings}
    assert "SEC-RATE-LIMIT-METADATA" in ids


# property-based: validator accepts anything it generates as valid
@given(st.integers(min_value=0, max_value=150))
def test_validator_numeric_bounds(value):
    from apiverity.core.validation import validate_value

    schema = SchemaNode(type="integer", minimum=0, maximum=150)
    errors = validate_value(schema, value)
    assert errors == []
    if value < 0 or value > 150:
        assert errors


@given(st.text(min_size=0, max_size=20))
def test_validator_string_length(text):
    from apiverity.core.validation import validate_value

    schema = SchemaNode(type="string", min_length=3)
    errors = validate_value(schema, text)
    assert (len(text) >= 3) == (errors == [])


def test_deterministic_case_generation(crud_service):
    from apiverity.fuzz.runner import build_cases

    a = build_cases(crud_service, seed=42)
    b = build_cases(crud_service, seed=42)
    assert [c.model_dump() for c in a] == [c.model_dump() for c in b]
    assert all(c.kind in ("positive", "negative") for c in a)


def test_mock_server_stateful_crud(crud_service):
    import httpx

    from apiverity.mock import MockServer

    with MockServer(crud_service, port=0) as mock:
        r = httpx.post(mock.base_url + "/users", json={"name": "alice"})
        assert r.status_code == 201
        user_id = r.json()["id"]
        r2 = httpx.get(mock.base_url + f"/users/{user_id}")
        assert r2.status_code == 200 and r2.json()["name"] == "alice"


def test_workflow_allowlist_refuses_unknown_host():
    from apiverity.stateful.engine import WorkflowEngine, load_workflow_manifest

    wf = load_workflow_manifest("fixtures/workflows/crud-lifecycle.yaml")
    try:
        WorkflowEngine(wf, "http://evil.example.com")
        raised = False
    except ValueError:
        raised = True
    assert raised


def test_redaction_removes_secrets():
    from apiverity.traffic.redact import RedactionConfig, redact_headers, redact_json

    cfg = RedactionConfig()
    hdrs = redact_headers({"Authorization": "Bearer abc.def", "Cookie": "x=1"}, cfg)
    assert hdrs["Authorization"] == "[REDACTED]" and hdrs["Cookie"] == "[REDACTED]"
    body = redact_json({"api_key": "sk-1234567890abcdef", "data": {"token": "t"}}, cfg)
    assert body["api_key"] == "[REDACTED]" and body["data"]["token"] == "[REDACTED]"


def test_performance_policy_parsing_and_evaluation():
    from apiverity.performance.engine import (
        OperationStats,
        PerformanceReport,
        evaluate_policies,
        parse_policy,
    )

    p = parse_policy("GET /users p95 <= 250ms")
    assert p.operation_key == "GET /users" and p.metric == "p95" and p.value == 250.0
    report = PerformanceReport(
        operations=[OperationStats(operation_key="GET /users", requests=10, p95_ms=300)]
    )
    violations = evaluate_policies(report, ["GET /users p95 <= 250ms"])
    assert len(violations) == 1


def test_cli_json_smoke():
    from apiverity.cli.main import main

    rc = main(["rules", "--json"])
    assert rc == 0
    rc = main(
        ["diff", "fixtures/apis/versioned/v1.yaml", "fixtures/apis/versioned/v2.yaml", "--json"]
    )
    assert rc == 0
