"""Latency and throughput as a function of load, rather than at one point.

`measure` produces a p95 at one concurrency level. That answers "is it fast
right now" and cannot answer the question anyone actually has before a release:
*what happens when more of them arrive*. A service that returns in 40 ms at one
request in flight and 4 seconds at eight has a p95 of 40 ms in every report this
tool produced.

So the same measurement is repeated across a sweep of levels and the shape is
reported: where throughput stops rising, and where latency starts climbing.

What this measures, and what it does not
----------------------------------------
It measures **the pair** -- this client, that service, over this network. A
sweep run from a laptop against a service across the internet is partly a
measurement of the laptop and mostly a measurement of the link, and the numbers
will be lower than the service can serve. That is not a caveat to be waved
away; it is why the report records the levels it swept and why saturation is
reported as "throughput stopped rising here", which is a statement about the
run, rather than "the service saturates at N", which is a statement about the
service that this cannot support.

The client's own ceiling is checked for and named. If throughput plateaus at
exactly the point where every worker is busy and no request is queueing, the
plateau is the harness, and saying so is more useful than a number.
"""

from __future__ import annotations

from itertools import pairwise
from typing import Any

from pydantic import BaseModel, Field

from apiverity.core.model import Service

__all__ = [
    "DEFAULT_LEVELS",
    "ConcurrencyCurve",
    "CurvePoint",
    "CurveReport",
    "measure_curve",
    "parse_levels",
]

#: Doubling, because the interesting behaviour is a knee and a knee is found
#: faster on a log scale than a linear one. Four points is the fewest that can
#: show a shape rather than a slope.
DEFAULT_LEVELS: tuple[int, ...] = (1, 2, 4, 8)

#: Throughput within this fraction of the previous level counts as "stopped
#: rising". Measurement noise at small sample sizes is easily 10%.
PLATEAU_RATIO = 1.1

#: p95 above this multiple of the single-request p95 counts as climbing.
LATENCY_KNEE = 2.0


class CurvePoint(BaseModel):
    """One operation at one concurrency level."""

    concurrency: int
    samples: int = 0
    p50_ms: float = 0.0
    p95_ms: float = 0.0
    p99_ms: float = 0.0
    throughput_rps: float = 0.0
    error_rate_pct: float = 0.0


class ConcurrencyCurve(BaseModel):
    operation_key: str
    points: list[CurvePoint] = Field(default_factory=list)
    #: The level at which throughput stopped rising, or None when it never did
    #: within the sweep -- which means the sweep did not go far enough, not
    #: that the service is unbounded.
    plateau_at: int | None = None
    #: The level at which p95 first exceeded `LATENCY_KNEE` times the
    #: single-request p95.
    latency_knee_at: int | None = None
    #: Set when the plateau is indistinguishable from the client's own limit.
    client_bound: bool = False

    def summary(self) -> str:
        if not self.points:
            return "no measurements"
        if self.plateau_at is None:
            top = self.points[-1].concurrency
            return (
                f"throughput was still rising at {top} in flight; the sweep did not reach a "
                "plateau, so this says nothing about where one is"
            )
        if self.client_bound:
            return (
                f"throughput stopped rising at {self.plateau_at} in flight, which is where "
                "this client runs out of workers -- the plateau is the harness, not the "
                "service"
            )
        knee = (
            f", and p95 passed {LATENCY_KNEE:g}x its single-request value at {self.latency_knee_at}"
            if self.latency_knee_at
            else ""
        )
        return f"throughput stopped rising at {self.plateau_at} in flight{knee}"


class CurveReport(BaseModel):
    target: str = ""
    levels: list[int] = Field(default_factory=list)
    iterations_per_level: int = 0
    curves: list[ConcurrencyCurve] = Field(default_factory=list)
    duration_s: float = 0.0


def parse_levels(raw: str | None) -> tuple[int, ...]:
    """`"1,2,4,8"` -> `(1, 2, 4, 8)`, sorted, deduplicated, positive."""
    if not raw:
        return DEFAULT_LEVELS
    levels = sorted({int(part) for part in raw.split(",") if part.strip()})
    positive = tuple(level for level in levels if level > 0)
    if not positive:
        raise ValueError(f"no usable concurrency levels in {raw!r}")
    return positive


def _analyse(curve: ConcurrencyCurve, levels: tuple[int, ...]) -> None:
    """Find the plateau and the latency knee, or leave both unset."""
    usable = [p for p in curve.points if p.samples]
    if len(usable) < 2:
        return

    baseline_p95 = usable[0].p95_ms
    for point in usable[1:]:
        if baseline_p95 > 0 and point.p95_ms >= baseline_p95 * LATENCY_KNEE:
            curve.latency_knee_at = point.concurrency
            break

    for previous, point in pairwise(usable):
        if previous.throughput_rps <= 0:
            continue
        if point.throughput_rps < previous.throughput_rps * PLATEAU_RATIO:
            curve.plateau_at = previous.concurrency
            # A plateau at the top of the sweep is indistinguishable from a
            # sweep that stopped too early, and one at exactly the client's
            # worker count is indistinguishable from the client's own limit.
            curve.client_bound = previous.concurrency == max(levels)
            return


def measure_curve(
    service: Service,
    base_url: str,
    *,
    levels: tuple[int, ...] = DEFAULT_LEVELS,
    iterations: int = 40,
    warmup: int = 5,
    timeout: float = 10.0,
    measurer: Any = None,
) -> CurveReport:
    """Sweep concurrency levels, measuring every operation at each.

    `measurer` is injectable so this can be exercised without a network: the
    shape of a curve is what matters here, and a test that needs a real slow
    service to produce one is a test nobody runs.
    """
    import time

    from apiverity.performance.engine import measure

    run = measurer or measure
    started = time.monotonic()
    report = CurveReport(
        target=base_url,
        levels=list(levels),
        iterations_per_level=iterations,
    )
    by_operation: dict[str, ConcurrencyCurve] = {}

    for level in levels:
        # Warmed at every level, not only the first: raising concurrency opens
        # new connections, and their setup would otherwise be charged to the
        # first few requests of that level and read as the service slowing
        # down under load.
        measurement = run(
            service,
            base_url,
            iterations=iterations,
            warmup=warmup,
            concurrency=level,
            timeout=timeout,
        )
        for stats in measurement.operations:
            curve = by_operation.setdefault(
                stats.operation_key, ConcurrencyCurve(operation_key=stats.operation_key)
            )
            curve.points.append(
                CurvePoint(
                    concurrency=level,
                    samples=stats.samples,
                    p50_ms=stats.p50_ms,
                    p95_ms=stats.p95_ms,
                    p99_ms=stats.p99_ms,
                    throughput_rps=stats.throughput_rps,
                    error_rate_pct=stats.error_rate_pct,
                )
            )

    for curve in by_operation.values():
        curve.points.sort(key=lambda p: p.concurrency)
        _analyse(curve, levels)

    report.curves = sorted(by_operation.values(), key=lambda c: c.operation_key)
    report.duration_s = round(time.monotonic() - started, 3)
    return report
