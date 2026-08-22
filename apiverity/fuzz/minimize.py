"""Failure minimization: shrink failing requests to small reproductions.

For a failing case whose body is an object, greedily remove optional
fields while the failure persists (a lightweight ddmin over body fields),
then emit a sanitized curl reproduction.
"""

from __future__ import annotations

import json
from typing import Any, Optional

import httpx

from apiverity.fuzz.models import TestCase, TestResult
from apiverity.fuzz.runner import _check_response, _curl_reproduction


def minimize_case(
    op: Any,
    base_url: str,
    case: TestCase,
    *,
    timeout: float = 10.0,
) -> TestResult:
    """Re-run a failing case, shrinking its body while the failure persists."""
    if case.body is None or not isinstance(case.body, dict) or op is None:
        return TestResult(
            case_id=case.id,
            operation_key=case.operation_key,
            kind=case.kind,
            description=case.description,
            status="fail",
            violations=["not minimizable (no object body)"],
            reproduction=_curl_reproduction(base_url, case),
        )

    body = dict(case.body)
    # determine required fields from the first content schema, if available
    req_fields: set[str] = set()
    rb = getattr(op, "request_body", None)
    if rb is not None and rb.content:
        first = next(iter(rb.content.values()), None)
        if first is not None:
            req_fields = set(first.required)

    changed = True
    while changed:
        changed = False
        for field in sorted(body):
            if field in req_fields:
                continue
            candidate = {k: v for k, v in body.items() if k != field}
            probe = case.model_copy(update={"body": candidate})
            try:
                with httpx.Client(base_url=base_url, timeout=timeout) as client:
                    response = client.request(
                        probe.method,
                        probe.url_path,
                        params=probe.query or None,
                        headers=probe.headers or None,
                        json=probe.body if probe.body is not None else None,
                    )
                if _check_response(op, probe, response):
                    body = candidate
                    changed = True
                    break
            except httpx.HTTPError:
                continue

    minimized = case.model_copy(update={"body": body})
    try:
        with httpx.Client(base_url=base_url, timeout=timeout) as client:
            response = client.request(
                minimized.method,
                minimized.url_path,
                params=minimized.query or None,
                headers=minimized.headers or None,
                json=minimized.body if minimized.body is not None else None,
            )
        violations = _check_response(op, minimized, response)
        status = "fail" if violations else "pass"
        actual = response.status_code
    except httpx.HTTPError as exc:
        violations = [f"request failed: {exc}"]
        status = "error"
        actual = None

    return TestResult(
        case_id=case.id,
        operation_key=case.operation_key,
        kind=case.kind,
        description=case.description,
        status=status,
        actual_status=actual,
        violations=violations,
        reproduction=_curl_reproduction(base_url, minimized),
        minimized=True,
    )


def minimize_failures(
    service: Any,
    base_url: str,
    results: list[TestResult],
    cases: list[TestCase],
    *,
    timeout: float = 10.0,
    max_minimize: int = 10,
) -> list[TestResult]:
    """Minimize up to ``max_minimize`` failing cases."""
    ops = {op.key: op for op in service.operations}
    case_by_id = {c.id: c for c in cases}
    out: list[TestResult] = []
    budget = max_minimize
    for result in results:
        if (
            budget > 0
            and result.status == "fail"
            and result.case_id in case_by_id
            and isinstance(case_by_id[result.case_id].body, dict)
        ):
            out.append(
                minimize_case(
                    ops.get(result.operation_key),
                    base_url,
                    case_by_id[result.case_id],
                    timeout=timeout,
                )
            )
            budget -= 1
        else:
            out.append(result)
    return out