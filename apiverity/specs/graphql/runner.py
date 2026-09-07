"""Execute GraphQL cases against a live endpoint (#16).

Separate from `fuzz/runner.py` on purpose. That runner decides pass or fail
from the HTTP status code, and a GraphQL server answers a malformed query with
**200** and an `errors` array -- so running these through it would mark every
failure a pass. The judgement here is `check_envelope`, and the status code is
only consulted for the cases where it genuinely means something (a 5xx, or a
transport error).
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx

from apiverity.specs.graphql.operations import (
    INTROSPECTION_QUERY,
    GraphQLCase,
    check_envelope,
    compare_introspection,
)

__all__ = ["GraphQLResult", "introspect", "run_cases", "run_drift"]


class GraphQLResult:
    """One executed case."""

    def __init__(
        self,
        case: GraphQLCase,
        *,
        status: str,
        http_status: int | None = None,
        violations: list[str] | None = None,
        duration_ms: int = 0,
    ) -> None:
        self.case = case
        self.status = status  # pass | fail | error
        self.http_status = http_status
        self.violations = violations or []
        self.duration_ms = duration_ms

    def as_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case.name,
            "kind": self.case.kind,
            "description": self.case.description,
            "status": self.status,
            "actual_status": self.http_status,
            "violations": self.violations,
            "reproduction": _curl(self.case),
            "duration_ms": self.duration_ms,
        }


def _curl(case: GraphQLCase, base_url: str = "$BASE_URL") -> str:
    payload = json.dumps({"query": case.query, "variables": case.variables})
    return f"curl -X POST '{base_url}' -H 'Content-Type: application/json' -d {json.dumps(payload)}"


def _post(client: httpx.Client, query: str, variables: dict[str, Any]) -> tuple[int, Any]:
    response = client.post("", json={"query": query, "variables": variables or {}})
    try:
        body = response.json()
    except ValueError:
        body = None
    return response.status_code, body


def run_cases(
    base_url: str,
    cases: list[GraphQLCase],
    *,
    timeout: float = 10.0,
    headers: dict[str, str] | None = None,
) -> list[GraphQLResult]:
    """POST each case and judge it by its envelope."""
    results: list[GraphQLResult] = []
    with httpx.Client(
        base_url=base_url, timeout=timeout, headers=headers or {}, follow_redirects=False
    ) as client:
        for case in cases:
            started = time.monotonic()
            try:
                status, body = _post(client, case.query, case.variables)
            except httpx.HTTPError as exc:
                results.append(
                    GraphQLResult(
                        case,
                        status="error",
                        violations=[f"request failed: {exc}"],
                        duration_ms=int((time.monotonic() - started) * 1000),
                    )
                )
                continue
            problems = check_envelope(case, status, body)
            fatal = [p.message for p in problems if p.fatal]
            results.append(
                GraphQLResult(
                    case,
                    status="fail" if fatal else "pass",
                    http_status=status,
                    violations=[p.message for p in problems],
                    duration_ms=int((time.monotonic() - started) * 1000),
                )
            )
    return results


def introspect(
    base_url: str, *, timeout: float = 10.0, headers: dict[str, str] | None = None
) -> Any:
    """Ask the endpoint what it serves.

    Raises rather than returning an empty result when introspection is
    disabled: "the server told us nothing" and "the server serves nothing" are
    different, and reporting the first as the second would produce a drift
    report claiming every declared type is missing.
    """
    with httpx.Client(
        base_url=base_url, timeout=timeout, headers=headers or {}, follow_redirects=False
    ) as client:
        status, body = _post(client, INTROSPECTION_QUERY, {})
    if status >= 400 or not isinstance(body, dict):
        raise ValueError(f"introspection request failed with HTTP {status}")
    if body.get("errors"):
        messages = "; ".join(
            str(e.get("message", "")) for e in body["errors"] if isinstance(e, dict)
        )
        raise ValueError(
            f"introspection was refused by the endpoint: {messages}. Many servers "
            "disable it in production; run drift against a staging endpoint, or "
            "enable introspection there."
        )
    if not (body.get("data") or {}).get("__schema"):
        raise ValueError("introspection returned no __schema")
    return body


def run_drift(
    schema: Any,
    base_url: str,
    *,
    timeout: float = 10.0,
    headers: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Compare the committed SDL against what the endpoint actually serves."""
    return compare_introspection(schema, introspect(base_url, timeout=timeout, headers=headers))
