"""Integration tests exercising the coverage, fuzz-runner, minimization,
workflow, performance and security engines against the in-process mock."""

from __future__ import annotations

from pathlib import Path

import pytest

from apiverity.coverage import measure_coverage
from apiverity.fuzz.minimize import minimize_failures
from apiverity.fuzz.runner import build_cases, run_cases
from apiverity.mock import MockServer
from apiverity.performance.engine import compare_baseline, evaluate_policies, measure
from apiverity.security import run_security_checks
from apiverity.specs.loader import detect_and_load
from apiverity.stateful.engine import WorkflowEngine, load_workflow_manifest

FIX = Path("fixtures")


@pytest.fixture(scope="module")
def crud_base() -> str:
    service, _, _ = detect_and_load(str(FIX / "apis/crud/openapi.yaml"))
    with MockServer(service, port=8097) as mock:
        yield mock.base_url


@pytest.fixture(scope="module")
def crud_service():
    service, _, _ = detect_and_load(str(FIX / "apis/crud/openapi.yaml"))
    return service


def test_coverage_measurement(crud_service: object) -> None:
    exercised = {op.key for op in crud_service.operations}  # type: ignore[attr-defined]
    statuses = {
        op.key: [200]
        for op in crud_service.operations  # type: ignore[attr-defined]
    }
    report = measure_coverage(
        crud_service, exercised_operations=exercised, statuses_by_operation=statuses
    )
    assert report.overall_percent() == 100.0
    empty = measure_coverage(crud_service)
    assert empty.overall_percent() < 100.0


def test_fuzz_runner_against_mock(crud_service: object, crud_base: str) -> None:
    cases = build_cases(crud_service, seed=7)
    assert cases, "cases must be generated"
    # determinism
    again = build_cases(crud_service, seed=7)
    assert [c.id for c in cases] == [c.id for c in again]
    results = run_cases(crud_service, crud_base, cases)
    assert len(results) == len(cases)
    assert all(r.status in ("pass", "fail") for r in results)


def test_minimize_reduces_or_preserves(crud_service: object, crud_base: str) -> None:
    cases = build_cases(crud_service, seed=7)
    results = run_cases(crud_service, crud_base, cases)
    minimized = minimize_failures(crud_service, crud_base, results, cases)
    assert len(minimized) <= len(results)


def test_workflow_engine_lifecycle(crud_base: str) -> None:
    wf = load_workflow_manifest(str(FIX / "workflows/crud-lifecycle.yaml"))
    result = WorkflowEngine(wf, crud_base).run()
    assert result.status == "pass", [s.violations for s in result.steps]
    assert len(result.steps) >= 3
    assert result.variables.get("user_id")


def test_workflow_allowlist_refusal() -> None:
    wf = load_workflow_manifest(str(FIX / "workflows/crud-lifecycle.yaml"))
    from apiverity.stateful.engine import WorkflowEngine as WE

    with pytest.raises(ValueError, match="allowlist"):
        WE(wf, "http://evil.example.com")


def test_performance_measure_and_policies(crud_service: object, crud_base: str) -> None:
    report = measure(crud_service, crud_base, iterations=4)
    assert report.operations and all(o.requests == 4 for o in report.operations)
    violations = evaluate_policies(report, ["GET /users p95 <= 60000ms"])
    assert violations == []
    baseline = {"operations": [o.model_dump() for o in report.operations]}
    again = evaluate_policies(report, [])
    assert again == []
    regressed = compare_baseline(report, baseline, tolerance_pct=400)
    assert isinstance(regressed, list)


def test_security_checks_on_fixtures() -> None:
    service, _, _ = detect_and_load(str(FIX / "apis/crud/openapi.yaml"))
    findings = run_security_checks(service)
    assert all(f.rule_id.startswith("SEC-") for f in findings)


def test_core_hash_helper() -> None:
    from apiverity.core.hash import canonical_json, sha256_hex

    payload = {"b": 1, "a": [2, 3]}
    assert sha256_hex(payload) == sha256_hex({"a": [2, 3], "b": 1})
    assert json_loads(canonical_json(payload)) == payload


def json_loads(text: str) -> object:
    import json

    return json.loads(text)


def test_sdk_exports_importable() -> None:
    import apiverity.sdk as sdk

    for name in sdk.__all__:
        assert hasattr(sdk, name), name
