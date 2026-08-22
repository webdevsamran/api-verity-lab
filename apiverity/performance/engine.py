"""Performance budgets: latency percentiles, throughput, error rates.

Policies like ``GET /users p95 <= 250ms`` are parsed and evaluated
against measured samples; baselines enable regression gates with stable
CI exit codes.
"""
from __future__ import annotations
import re, statistics, time
from typing import Any, Optional
import httpx
from pydantic import BaseModel, Field
from apiverity.core.model import Service
from apiverity.fuzz.generate import fill_path, generate_valid

_POLICY_RE = re.compile(
    r"^(?P<method>GET|POST|PUT|PATCH|DELETE)\s+(?P<path>\S+)\s+"
    r"(?P<metric>p50|p90|p95|p99|error_rate|throughput)\s*<=\s*(?P<value>[\d.]+)(?P<unit>ms|%|rps)?$"
)


class Policy(BaseModel):
    operation_key: str
    metric: str
    value: float


def parse_policy(text: str) -> Policy:
    m = _POLICY_RE.match(text.strip())
    if not m:
        raise ValueError(f"invalid policy '{text}'; expected e.g. 'GET /users p95 <= 250ms'")
    return Policy(operation_key=f"{m['method']} {m['path']}", metric=m["metric"], value=float(m["value"]))


class OperationStats(BaseModel):
    operation_key: str
    requests: int = 0
    errors: int = 0
    timeouts: int = 0
    p50_ms: float = 0.0
    p90_ms: float = 0.0
    p95_ms: float = 0.0
    p99_ms: float = 0.0
    throughput_rps: float = 0.0


class PerformanceReport(BaseModel):
    target: str = ""
    duration_s: float = 0.0
    operations: list[OperationStats] = Field(default_factory=list)
    policy_violations: list[str] = Field(default_factory=list)


def _percentile(sorted_samples: list[float], pct: float) -> float:
    if not sorted_samples:
        return 0.0
    idx = min(int(len(sorted_samples) * pct / 100), len(sorted_samples) - 1)
    return sorted_samples[idx]


def measure(
    service: Service,
    base_url: str,
    *,
    iterations: int = 20,
    concurrency: int = 1,
    timeout: float = 10.0,
) -> PerformanceReport:
    started = time.monotonic()
    report = PerformanceReport(target=base_url)
    rng = __import__("random").Random(7)
    with httpx.Client(base_url=base_url, timeout=timeout) as client:
        for op in service.operations:
            if not op.method or not op.path:
                continue
            params = {p.name: generate_valid(p.schema_node, rng) for p in op.parameters}
            path = fill_path(op.path, params)
            query = {p.name: params[p.name] for p in op.parameters if p.location.value == "query"}
            body = None
            if op.request_body is not None and op.request_body.content:
                schema = next(iter(op.request_body.content.values()))
                body = generate_valid(schema, rng)
            latencies: list[float] = []
            errors = timeouts = 0
            t0 = time.monotonic()
            for _ in range(iterations):
                try:
                    resp = client.request(op.method, path, params=query or None,
                                          json=body if body is not None else None)
                    if resp.status_code >= 500 or resp.status_code == 429:
                        errors += 1
                except httpx.TimeoutException:
                    timeouts += 1
                except httpx.HTTPError:
                    errors += 1
                latencies.append((time.monotonic() - t0) * 1000 - sum(latencies))
            elapsed = max(time.monotonic() - t0, 1e-9)
            latencies.sort()
            stats = OperationStats(
                operation_key=op.key,
                requests=iterations,
                errors=errors,
                timeouts=timeouts,
                p50_ms=round(_percentile(latencies, 50), 2),
                p90_ms=round(_percentile(latencies, 90), 2),
                p95_ms=round(_percentile(latencies, 95), 2),
                p99_ms=round(_percentile(latencies, 99), 2),
                throughput_rps=round(iterations / elapsed, 2),
            )
            report.operations.append(stats)
    report.duration_s = round(time.monotonic() - started, 3)
    return report


def evaluate_policies(report: PerformanceReport, policies: list[str]) -> list[str]:
    violations = []
    parsed = [parse_policy(p) for p in policies]
    by_key = {o.operation_key: o for o in report.operations}
    for policy in parsed:
        stats = by_key.get(policy.operation_key)
        if stats is None:
            violations.append(f"{policy.operation_key}: no measurements for policy "
                              f"'{policy.metric} <= {policy.value}'")
            continue
        actual_map = {"p50": stats.p50_ms, "p90": stats.p90_ms, "p95": stats.p95_ms,
                      "p99": stats.p99_ms,
                      "error_rate": (100.0 * (stats.errors + stats.timeouts) / max(stats.requests, 1)),
                      "throughput": stats.throughput_rps}
        actual = actual_map[policy.metric]
        if actual > policy.value:
            violations.append(
                f"{policy.operation_key}: {policy.metric}={actual} exceeds budget "
                f"{policy.value}")
    return violations


def compare_baseline(current: PerformanceReport, baseline: dict[str, Any],
                     tolerance_pct: float = 20.0) -> list[str]:
    """Flag regressions vs a stored baseline (per-operation p95)."""
    regressions = []
    base_ops = {o["operation_key"]: o for o in baseline.get("operations", [])}
    for op in current.operations:
        prev = base_ops.get(op.operation_key)
        if not prev:
            continue
        limit = prev.get("p95_ms", 0) * (1 + tolerance_pct / 100.0)
        if op.p95_ms > limit and prev.get("p95_ms", 0) > 0:
            regressions.append(
                f"{op.operation_key}: p95 regressed {prev['p95_ms']}ms -> {op.p95_ms}ms "
                f"(tolerance {tolerance_pct}%)")
        prev_err = prev.get("errors", 0)
        if prev_err == 0 and op.errors > 0:
            regressions.append(f"{op.operation_key}: new errors appeared ({op.errors})")
    return regressions