"""Executes generated cases against an explicitly supplied base URL.

Safety: the runner only ever sends requests to ``base_url`` provided by
the caller — it never discovers or follows other hosts.
"""

from __future__ import annotations

import json
import time
import zlib
from typing import Any

import httpx

from apiverity.core.model import Operation, Service
from apiverity.core.validation import validate_value
from apiverity.fuzz.generate import fill_path, operation_cases
from apiverity.fuzz.models import TestCase, TestResult


def build_cases(
    service: Service,
    seed: int = 0,
    *,
    generators: list[str] | None = None,
) -> list[TestCase]:
    """Build the case set for a service.

    `generators` selects strategies beyond the schema-derived ones -- see
    `apiverity.fuzz.generators`. The default is the schema strategy alone,
    which is what this produced before: the extra strategies multiply the case
    count substantially, and a `test` run that silently got ten times longer
    would be a worse default than an opt-in.
    """
    from apiverity.fuzz.generators import load_generators

    extra = load_generators(generators) if generators else {}
    cases: list[TestCase] = []
    for i, op in enumerate(service.operations):
        produced: list[tuple[str, dict[str, Any]]] = [
            ("schema", raw) for raw in operation_cases(op, seed + i)
        ]
        for name, generator in sorted(extra.items()):
            # Seeded per generator so adding one does not renumber the cases
            # of the ones beside it -- a case id in a bug report has to keep
            # pointing at the same case.
            generator_seed = seed + i + (zlib.crc32(name.encode()) % 100_000)
            try:
                produced.extend((name, raw) for raw in generator.generate(op, generator_seed))
            except Exception as exc:  # a third-party generator must not abort the run
                produced.append(
                    (
                        name,
                        {
                            "kind": "negative",
                            "description": f"generator '{name}' failed: {exc}",
                            "path_params": {},
                            "query": {},
                            "headers": {},
                            "body": None,
                            "media": None,
                        },
                    )
                )
        for j, (origin, raw) in enumerate(produced):
            description = raw["description"]
            if origin != "schema":
                description = f"[{origin}] {description}"
            cases.append(
                TestCase(
                    id=f"TC-{i:03d}-{j:03d}",
                    operation_key=op.key,
                    kind=raw["kind"],
                    description=description,
                    method=op.method or "GET",
                    url_path=fill_path(op.path or "", raw["path_params"]),
                    query=raw["query"],
                    headers=raw["headers"],
                    body=raw["body"],
                    media=raw["media"],
                    expected="2xx" if raw["kind"] == "positive" else "4xx",
                )
            )
    return cases


def _curl_reproduction(base_url: str, case: TestCase) -> str:
    url = base_url.rstrip("/") + case.url_path
    if case.query:
        from urllib.parse import urlencode

        url += "?" + urlencode(case.query)
    parts = [f"curl -X {case.method} '{url}'"]
    for k, v in case.headers.items():
        parts.append(f"-H '{k}: {v}'")
    if case.body is not None and case.media:
        parts.append(f"-H 'Content-Type: {case.media}'")
        parts.append(f"-d '{json.dumps(case.body)}'")
    return " ".join(parts)


def _declared_success(op: Operation) -> str:
    for resp in op.responses:
        if resp.status.startswith("2"):
            return resp.status
    return "2xx"


def _check_response(op: Operation, case: TestCase, response: httpx.Response) -> list[str]:
    """Contract checks applied to every response."""
    violations: list[str] = []
    status = response.status_code

    if status >= 500:
        violations.append(f"server returned 5xx ({status})")
        return violations

    if case.kind == "positive":
        if not 200 <= status < 300:
            violations.append(
                f"valid input rejected with {status} (expected {_declared_success(op)})"
            )
            return violations
    else:
        if 200 <= status < 300:
            violations.append(f"invalid input accepted with {status} (expected 4xx)")
            return violations
        if 400 <= status < 500:
            return violations  # correctly rejected

    # find the declared response for this status (or default)
    declared = None
    for resp in op.responses:
        if resp.status == str(status):
            declared = resp
            break
    if declared is None:
        for resp in op.responses:
            if resp.status == "default":
                declared = resp
                break
    if declared is None:
        if case.kind == "positive":
            violations.append(f"status {status} is not declared in the contract")
        return violations

    # content type check
    content_type = response.headers.get("content-type", "")
    if declared.content:
        media = content_type.split(";")[0].strip()
        if media and media not in declared.content:
            violations.append(
                f"content type '{media}' not declared (declared: {sorted(declared.content)})"
            )
        schema = declared.content.get(media) or next(iter(declared.content.values()), None)
        if schema is not None and "json" in content_type:
            try:
                body = response.json()
            except ValueError:
                violations.append("declared JSON response body is not valid JSON")
                body = None
            if body is not None:
                violations.extend(f"response body: {v}" for v in validate_value(schema, body))

    # declared response headers present?
    for header in declared.headers:
        if header.lower() not in {h.lower() for h in response.headers}:
            violations.append(f"declared response header '{header}' missing")

    return violations


def run_cases(
    service: Service,
    base_url: str,
    cases: list[TestCase],
    *,
    timeout: float = 10.0,
    max_cases: int | None = None,
    headers: dict[str, str] | None = None,
    cert: Any = None,
) -> list[TestResult]:
    """Run cases sequentially against ``base_url``.

    `headers` and `cert` carry whatever `--auth-profiles` resolved. They are
    applied to the client rather than to each request so a case that sets its
    own headers cannot drop the credential by replacing the dict.
    """
    ops = {op.key: op for op in service.operations}
    results: list[TestResult] = []
    selected = cases if max_cases is None else cases[:max_cases]

    with httpx.Client(
        base_url=base_url,
        timeout=timeout,
        follow_redirects=False,
        headers=headers or None,
        cert=cert,
    ) as client:
        for case in selected:
            op = ops.get(case.operation_key)
            started = time.monotonic()
            try:
                response = client.request(
                    case.method,
                    case.url_path,
                    params=case.query or None,
                    headers=case.headers or None,
                    json=case.body if case.body is not None and case.media else None,
                )
                duration_ms = int((time.monotonic() - started) * 1000)
                violations = (
                    _check_response(op, case, response)
                    if op is not None
                    else ["operation not found in contract"]
                )
                results.append(
                    TestResult(
                        case_id=case.id,
                        operation_key=case.operation_key,
                        kind=case.kind,
                        description=case.description,
                        status="fail" if violations else "pass",
                        actual_status=response.status_code,
                        violations=violations,
                        reproduction=_curl_reproduction(base_url, case),
                        duration_ms=duration_ms,
                    )
                )
            except (httpx.HTTPError, UnicodeError, ValueError, TypeError) as exc:
                # Not just HTTPError: a case can be unsendable before it
                # reaches the network -- a header value the transport cannot
                # encode, a body that will not serialise. That is a fact about
                # the case, and it belongs against the case. Letting it
                # propagate aborted the whole run and, worse, surfaced as
                # "target unreachable" when the target was fine.
                duration_ms = int((time.monotonic() - started) * 1000)
                results.append(
                    TestResult(
                        case_id=case.id,
                        operation_key=case.operation_key,
                        kind=case.kind,
                        description=case.description,
                        status="error",
                        violations=[f"request failed: {exc}"],
                        reproduction=_curl_reproduction(base_url, case),
                        duration_ms=duration_ms,
                    )
                )
    return results
