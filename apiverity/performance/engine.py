"""Performance budgets: latency percentiles, throughput, error rates.

Policies like ``GET /users p95 <= 250ms`` are parsed and evaluated
against measured samples; baselines enable regression gates with stable
CI exit codes.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import BaseModel, Field

from apiverity.core.model import Service
from apiverity.fuzz.generate import fill_path, generate_valid
from apiverity.performance.connection import ConnectionProbe
from apiverity.performance.connection import probe as probe_connection
from apiverity.performance.stats import (
    Interval,
    bootstrap_percentile_ci,
    bootstrap_throughput_ci,
    overlaps,
    percentile,
    wilson_interval,
)

_POLICY_RE = re.compile(
    r"^(?P<method>GET|POST|PUT|PATCH|DELETE)\s+(?P<path>\S+)\s+"
    r"(?P<metric>p50|p90|p95|p99|error_rate|throughput|bytes_p50|bytes_p95|bytes_max)"
    r"\s*<=\s*(?P<value>[\d.]+)(?P<unit>ms|%|rps|B|KB|MB)?$"
)

#: A size suffix, in the sense a person means it when writing a budget.
#: Decimal, not binary: `256KB` in a budget somebody typed means 256,000, and
#: silently reading it as 262,144 would make a limit 2.4% looser than written.
_SIZE_UNITS = {"B": 1, "KB": 1_000, "MB": 1_000_000}


class Policy(BaseModel):
    operation_key: str
    metric: str
    value: float


def parse_policy(text: str) -> Policy:
    m = _POLICY_RE.match(text.strip())
    if not m:
        raise ValueError(f"invalid policy '{text}'; expected e.g. 'GET /users p95 <= 250ms'")
    value = float(m["value"])
    unit = m["unit"]
    if unit in _SIZE_UNITS:
        value *= _SIZE_UNITS[unit]
    return Policy(operation_key=f"{m['method']} {m['path']}", metric=m["metric"], value=value)


class OperationStats(BaseModel):
    operation_key: str
    requests: int = 0
    errors: int = 0
    timeouts: int = 0
    #: Measurements the percentiles were computed from. Distinct from
    #: `requests`: warmup requests are made but not measured, so a reader can
    #: tell "p95 of 100 samples" from "p95 of 4" without recomputing it.
    samples: int = 0
    warmup: int = 0
    #: Requests where nothing answered at all, as opposed to answering badly.
    unreachable: int = 0
    p50_ms: float = 0.0
    p90_ms: float = 0.0
    p95_ms: float = 0.0
    p99_ms: float = 0.0
    #: 95% bootstrap intervals, or None when there were too few samples to
    #: say anything. None means "unknown", never "zero width".
    p50_ci95: tuple[float, float] | None = None
    p90_ci95: tuple[float, float] | None = None
    p95_ci95: tuple[float, float] | None = None
    p99_ci95: tuple[float, float] | None = None
    throughput_rps: float = 0.0
    #: Resampled from the same latencies, so requests-per-second is on the
    #: same footing as the percentiles rather than a single wall-clock ratio.
    throughput_ci95: tuple[float, float] | None = None
    #: Wilson score interval for the error proportion, as a percentage.
    error_rate_pct: float = 0.0
    error_rate_ci95: tuple[float, float] | None = None
    #: Decoded response size, in bytes. Percentiles rather than a mean,
    #: because the response that hurts is the largest one a client hit and a
    #: mean hides it behind a hundred small ones. Zero for an operation where
    #: nothing answered, which `unreachable` above already distinguishes from
    #: an operation that really returns nothing.
    bytes_p50: int = 0
    bytes_p95: int = 0
    bytes_max: int = 0
    bytes_total: int = 0
    #: Decoded bytes per second over the measured window. Not wire bandwidth:
    #: the client decompresses before anything here sees the body, so a gzipped
    #: response is counted at its parsed size, which is the number a payload
    #: budget cares about and is larger than what crossed the network.
    bytes_per_second: float = 0.0


class PerformanceReport(BaseModel):
    """A measurement, and the load it was taken under.

    `concurrency` is recorded because a p95 with no load level beside it is not
    comparable to anything -- including a later run of the same command.
    """

    target: str = ""
    duration_s: float = 0.0
    #: Requests in flight at once during this measurement.
    concurrency: int = 1
    #: One cold connection to the target, timed phase by phase before the load
    #: run. Beside the percentiles rather than inside them: the run pools
    #: connections, so the handshake is paid once and amortising it into a p95
    #: would describe a service nobody is running.
    connection: ConnectionProbe | None = None
    operations: list[OperationStats] = Field(default_factory=list)
    policy_violations: list[str] = Field(default_factory=list)
    #: Differences the run could not resolve: over tolerance, but with
    #: overlapping intervals. Reported, never fatal -- see `Comparison`.
    inconclusive: list[str] = Field(default_factory=list)

    def nothing_answered(self) -> bool:
        """True when every request to every operation failed to connect.

        `measure` catches connection errors per request so one dead endpoint
        does not abort the run, which meant a wholly unreachable target came
        back as a clean report of zero violations and exit 0 -- the documented
        exit code 3 was unreachable code. A target where literally nothing
        answered is not a passing run.
        """
        if not self.operations:
            return False
        return all(op.samples > 0 and op.unreachable == op.samples for op in self.operations)


@dataclass(frozen=True)
class Comparison:
    """The outcome of comparing a run to a baseline.

    Two lists rather than one, because they mean different things to CI.
    `regressions` should fail a build. `inconclusive` should not: it says the
    run was too short to decide, and failing on that is how a gate earns a
    reputation for crying wolf and gets switched off. Both get printed.
    """

    regressions: list[str]
    inconclusive: list[str]


def _bounds(interval: Interval | None) -> tuple[float, float] | None:
    """Drop the sample count for storage; it lives on the stats object."""
    return None if interval is None else (interval.low, interval.high)


def _timed_request(
    client: httpx.Client,
    method: str,
    path: str,
    query: dict[str, Any] | None,
    body: Any,
) -> tuple[float, str, int]:
    """One request; returns (duration_ms, outcome, response bytes).

    The byte count is the decoded body. Not the compressed transfer size:
    `httpx` decompresses before this code sees anything, and reporting the
    decoded length as though it were bandwidth would overstate the wire cost of
    every gzipped JSON response -- which is most of them. What it does answer
    is the question a payload budget is actually about: how much a client has
    to parse and hold.

    Timed individually rather than derived from a running total minus the sum
    of everything measured before it, which is what this did: that is O(n^2)
    and every sample carries the accumulated floating-point error of all its
    predecessors. `perf_counter` rather than `monotonic` because the interval
    being measured is often under a millisecond.
    """
    start = time.perf_counter()
    outcome = "ok"
    size = 0
    try:
        resp = client.request(method, path, params=query or None, json=body)
        size = len(resp.content)
        if resp.status_code >= 500 or resp.status_code == 429:
            outcome = "error"
    except httpx.ConnectError:
        # Distinct from a 5xx: nothing answered. Kept separate so an
        # unreachable target reports as unreachable rather than as a service
        # with a 100% error rate, which is a different thing to tell someone.
        outcome = "unreachable"
    except httpx.TimeoutException:
        outcome = "timeout"
    except httpx.HTTPError:
        outcome = "error"
    return (time.perf_counter() - start) * 1000.0, outcome, size


def _run(
    client: httpx.Client,
    method: str,
    path: str,
    query: dict[str, Any],
    body: Any,
    iterations: int,
    concurrency: int,
) -> list[tuple[float, str, int]]:
    """Issue `iterations` requests, at most `concurrency` of them in flight.

    `concurrency` was a parameter of `measure` from the beginning and nothing
    read it: every request went out in a row, and a report from
    `--concurrency 16` described a service under a load of one. A knob that
    does nothing is worse than a missing one, because the number it produces
    gets quoted.

    Threads rather than asyncio because `httpx.Client` is what the rest of this
    module already uses, and it is safe to share across threads. The
    connection pool is sized to the level so the client is not the thing being
    measured -- though it may still be: see `_client_bound` on the report.
    """
    if concurrency <= 1:
        return [_timed_request(client, method, path, query, body) for _ in range(iterations)]

    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [
            pool.submit(_timed_request, client, method, path, query, body)
            for _ in range(iterations)
        ]
        return [f.result() for f in futures]


def measure(
    service: Service,
    base_url: str,
    *,
    iterations: int = 20,
    warmup: int = 0,
    concurrency: int = 1,
    timeout: float = 10.0,
) -> PerformanceReport:
    """Measure each operation, optionally discarding a warmup phase.

    The first requests to a cold target measure connection setup, JIT, lazy
    imports and an empty cache -- not the thing under test. They are made
    (the warming is the point) and then dropped, so `samples` is `iterations`
    and `requests` is `iterations + warmup`.

    `concurrency` is the number of requests in flight at once. It is honoured
    now; it was accepted and ignored before.
    """
    started = time.monotonic()
    report = PerformanceReport(target=base_url, concurrency=max(1, concurrency))
    # Before the client is built, so it is a genuinely cold connection rather
    # than one the pool already opened.
    report.connection = probe_connection(base_url, timeout=min(timeout, 5.0))
    rng = __import__("random").Random(7)
    limits = httpx.Limits(
        max_connections=max(concurrency * 2, 10),
        max_keepalive_connections=max(concurrency, 10),
    )
    with httpx.Client(base_url=base_url, timeout=timeout, limits=limits) as client:
        for op in service.operations:
            if not op.method or not op.path:
                continue
            method: str = op.method
            params = {p.name: generate_valid(p.schema_node, rng) for p in op.parameters}
            path = fill_path(op.path, params)
            query = {p.name: params[p.name] for p in op.parameters if p.location.value == "query"}
            body = None
            if op.request_body is not None and op.request_body.content:
                schema = next(iter(op.request_body.content.values()))
                body = generate_valid(schema, rng)
            latencies: list[float] = []
            sizes: list[int] = []
            errors = timeouts = unreachable = 0

            for _ in range(max(0, warmup)):
                # Made, then discarded: warming is the point, measuring it is
                # not. Errors here are not counted either -- a target that is
                # still starting up should not fail an error-rate policy.
                _timed_request(client, method, path, query, body)

            t0 = time.monotonic()
            outcomes = _run(client, method, path, query, body, iterations, concurrency)
            elapsed = max(time.monotonic() - t0, 1e-9)
            for duration, outcome, size in outcomes:
                latencies.append(duration)
                sizes.append(size)
                if outcome == "timeout":
                    timeouts += 1
                elif outcome == "unreachable":
                    errors += 1
                    unreachable += 1
                elif outcome == "error":
                    errors += 1

            def _ci(pct: float, values: list[float] = latencies) -> tuple[float, float] | None:
                return _bounds(bootstrap_percentile_ci(values, pct))

            stats = OperationStats(
                operation_key=op.key,
                requests=iterations + max(0, warmup),
                errors=errors,
                timeouts=timeouts,
                samples=len(latencies),
                warmup=max(0, warmup),
                unreachable=unreachable,
                p50_ms=round(percentile(latencies, 50), 2),
                p90_ms=round(percentile(latencies, 90), 2),
                p95_ms=round(percentile(latencies, 95), 2),
                p99_ms=round(percentile(latencies, 99), 2),
                p50_ci95=_ci(50),
                p90_ci95=_ci(90),
                p95_ci95=_ci(95),
                p99_ci95=_ci(99),
                throughput_rps=round(iterations / elapsed, 2),
                throughput_ci95=_bounds(bootstrap_throughput_ci(latencies)),
                error_rate_pct=round(100.0 * (errors + timeouts) / max(len(latencies), 1), 4),
                error_rate_ci95=_bounds(wilson_interval(errors + timeouts, len(latencies))),
                bytes_p50=int(percentile([float(b) for b in sizes], 50)),
                bytes_p95=int(percentile([float(b) for b in sizes], 95)),
                bytes_max=max(sizes, default=0),
                bytes_total=sum(sizes),
                bytes_per_second=round(sum(sizes) / elapsed, 2),
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
            violations.append(
                f"{policy.operation_key}: no measurements for policy "
                f"'{policy.metric} <= {policy.value}'"
            )
            continue
        actual_map = {
            "p50": stats.p50_ms,
            "p90": stats.p90_ms,
            "p95": stats.p95_ms,
            "p99": stats.p99_ms,
            "error_rate": (100.0 * (stats.errors + stats.timeouts) / max(stats.requests, 1)),
            "throughput": stats.throughput_rps,
            # Response size, budgeted like latency is. Without this the size
            # metrics would be numbers in an artifact that nothing can fail a
            # build on -- and a measurement nothing acts on is a measurement
            # nobody reads.
            "bytes_p50": float(stats.bytes_p50),
            "bytes_p95": float(stats.bytes_p95),
            "bytes_max": float(stats.bytes_max),
        }
        actual = actual_map[policy.metric]
        if actual > policy.value:
            violations.append(
                f"{policy.operation_key}: {policy.metric}={actual} exceeds budget {policy.value}"
            )
    return violations


#: Metrics `compare_baseline` knows how to compare, and which direction is
#: bad. Throughput is the one where smaller is worse.
_REGRESSION_METRICS = {
    "p50": ("p50_ms", "higher"),
    "p90": ("p90_ms", "higher"),
    "p95": ("p95_ms", "higher"),
    "p99": ("p99_ms", "higher"),
    "error_rate": ("error_rate_pct", "higher"),
    "throughput": ("throughput_rps", "lower"),
}


def parse_tolerance(values: list[str] | None, default_pct: float = 20.0) -> dict[str, float]:
    """Parse `--tolerance` into per-metric percentages.

    Accepts a bare number for every metric (`--tolerance 15`) or a metric
    assignment (`--tolerance p95=10 --tolerance error_rate=0`), so a project
    can be strict about correctness and loose about latency without needing
    two separate gates. Later assignments win; a bare number resets the
    default without discarding assignments already made.
    """
    tolerances = dict.fromkeys(_REGRESSION_METRICS, default_pct)
    explicit: dict[str, float] = {}
    for raw in values or []:
        text = str(raw).strip()
        if "=" in text:
            metric, _, number = text.partition("=")
            metric = metric.strip()
            if metric not in _REGRESSION_METRICS:
                known = ", ".join(sorted(_REGRESSION_METRICS))
                raise ValueError(f"unknown metric '{metric}' in tolerance (known: {known})")
            try:
                explicit[metric] = float(number)
            except ValueError as exc:
                raise ValueError(f"tolerance for '{metric}' is not a number: {number!r}") from exc
        else:
            try:
                tolerances = dict.fromkeys(_REGRESSION_METRICS, float(text))
            except ValueError as exc:
                raise ValueError(f"tolerance is not a number: {text!r}") from exc
    tolerances.update(explicit)
    return tolerances


def _actual(stats: OperationStats, field: str) -> float:
    return float(getattr(stats, field))


def _interval(source: OperationStats | dict[str, Any], field: str) -> Interval | None:
    """The stored 95% interval for a metric, from either a report or a baseline.

    Baselines are read as raw JSON, so an older one simply has no interval and
    the caller falls back to the tolerance check.
    """
    key = f"{field.removesuffix('_ms').removesuffix('_rps').removesuffix('_pct')}_ci95"
    raw = getattr(source, key, None) if isinstance(source, OperationStats) else source.get(key)
    if not raw or len(raw) != 2:
        return None
    samples = (
        source.samples if isinstance(source, OperationStats) else int(source.get("samples") or 0)
    )
    return Interval(float(raw[0]), float(raw[1]), samples)


def compare_baseline(
    current: PerformanceReport,
    baseline: dict[str, Any],
    tolerance_pct: float | dict[str, float] = 20.0,
) -> Comparison:
    """Flag regressions against a stored baseline.

    Two guards, in this order:

    1. The change must exceed the tolerance for that metric.
    2. The two confidence intervals must not overlap.

    The second is what makes the gate usable. Twenty requests produce a p95
    that moves by tens of percent between identical runs, so a point-estimate
    comparison fires on noise until someone widens the tolerance far enough
    that it stops detecting anything. Overlapping intervals mean the run
    cannot tell the two apart, which is not the same as "no regression" -- it
    is reported as an inconclusive note rather than silently passed, so a gate
    that is measuring too little to say anything looks like one.

    When either side has no interval -- an older baseline, or too few samples
    -- the tolerance check stands alone, as it did before.
    """
    tolerances = (
        tolerance_pct
        if isinstance(tolerance_pct, dict)
        else dict.fromkeys(_REGRESSION_METRICS, float(tolerance_pct))
    )
    regressions: list[str] = []
    inconclusive: list[str] = []
    base_ops = {o["operation_key"]: o for o in baseline.get("operations", [])}
    for op in current.operations:
        prev = base_ops.get(op.operation_key)
        if not prev:
            continue
        for metric, (field, worse) in _REGRESSION_METRICS.items():
            if field not in prev:
                # An older baseline predates this metric. Comparing against a
                # missing value would read as a change from zero.
                continue
            tolerance = tolerances.get(metric)
            if tolerance is None:
                continue
            before = (
                100.0
                * (prev.get("errors", 0) + prev.get("timeouts", 0))
                / max(int(prev.get("samples") or prev.get("requests") or 0), 1)
                if metric == "error_rate"
                else float(prev.get(field) or 0.0)
            )
            after = _actual(op, field)
            if before <= 0 and metric != "error_rate":
                # No baseline value to compare a ratio against.
                continue

            if worse == "higher":
                limit = before * (1 + tolerance / 100.0)
                over = after > limit
            else:
                limit = before * (1 - tolerance / 100.0)
                over = after < limit
            if not over:
                continue

            # Every gated metric has an interval, so this guard applies
            # uniformly rather than only to the percentiles. It only applies
            # when *both* sides have one: a baseline written before intervals
            # existed, or a run with too few samples, falls back to the
            # tolerance check rather than silently passing everything.
            now, then = _interval(op, field), _interval(prev, field)
            if now is not None and then is not None and overlaps(now, then):
                inconclusive.append(
                    f"{op.operation_key}: {metric} moved {before} -> {after} "
                    f"but the 95% intervals overlap ({then.low}-{then.high} vs "
                    f"{now.low}-{now.high}, n={now.samples}); inconclusive, "
                    f"raise --iterations to decide"
                )
                continue
            regressions.append(
                f"{op.operation_key}: {metric} regressed {before} -> {after} "
                f"(tolerance {tolerance}%)"
            )

        if prev.get("errors", 0) == 0 and op.errors > 0:
            regressions.append(f"{op.operation_key}: new errors appeared ({op.errors})")
    return Comparison(regressions, inconclusive)
