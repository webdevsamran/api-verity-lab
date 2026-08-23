"""Load profiles and capacity search for authorized performance testing.

Profiles generate deterministic request schedules (offsets in seconds):
constant-rate, ramp, spike, soak, closed-loop and Poisson arrivals. The
executor drives a transport callable ``(method, path) -> (status, latency_ms)``
so tests run against httpx or an in-process fake deterministically.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass, field

Transport = Callable[[str, str], tuple[int, float]]


@dataclass(frozen=True)
class LoadProfile:
    kind: str  # constant | ramp | spike | soak | closed-loop
    duration_seconds: float
    rate_start: float  # requests/second
    rate_end: float | None = None  # for ramp; None = constant
    spike_at: float | None = None  # fraction of duration where spike occurs
    spike_multiplier: float = 5.0
    poisson: bool = False
    seed: int = 0


@dataclass
class ProfileResult:
    profile: str
    sent: int = 0
    errors: int = 0
    latencies_ms: list[float] = field(default_factory=list)
    status_counts: dict[str, int] = field(default_factory=dict)

    @property
    def p50(self) -> float:
        return _pct(self.latencies_ms, 50)

    @property
    def p95(self) -> float:
        return _pct(self.latencies_ms, 95)

    @property
    def p99(self) -> float:
        return _pct(self.latencies_ms, 99)


def _pct(sorted_or_unsorted: list[float], pct: float) -> float:
    if not sorted_or_unsorted:
        return 0.0
    s = sorted(sorted_or_unsorted)
    idx = min(len(s) - 1, round((pct / 100.0) * (len(s) - 1)))
    return s[idx]


def schedule(profile: LoadProfile) -> list[float]:
    """Deterministic request offsets in seconds for the profile."""
    rng = random.Random(profile.seed)
    offsets: list[float] = []
    rate_end = profile.rate_end if profile.rate_end is not None else profile.rate_start
    t = 0.0
    step = 0.05  # 20 Hz scheduling resolution
    while t < profile.duration_seconds:
        frac = t / max(profile.duration_seconds, 1e-9)
        rate = profile.rate_start + (rate_end - profile.rate_start) * frac
        if profile.kind == "spike" and profile.spike_at is not None:
            window = abs(frac - profile.spike_at) < 0.02
            if window:
                rate *= profile.spike_multiplier
        expected = rate * step
        n = 1 if rng.random() < expected else 0
        if profile.poisson:
            # exponential inter-arrival sampling folded into the grid
            n = 1 if rng.expovariate(max(rate, 1e-9)) < step else 0
        for _ in range(n):
            offsets.append(t)
        t += step
    return offsets


def execute(
    profile: LoadProfile,
    transport: Transport,
    *,
    method: str = "GET",
    path: str = "/",
    max_requests: int = 100_000,
) -> ProfileResult:
    """Run the schedule against the transport (virtual time between sends)."""
    result = ProfileResult(profile=profile.kind)
    for _offset in schedule(profile)[:max_requests]:
        try:
            status, latency = transport(method, path)
            result.sent += 1
            result.latencies_ms.append(latency)
            key = f"{int(status) // 100}xx"
            result.status_counts[key] = result.status_counts.get(key, 0) + 1
        except Exception:
            result.errors += 1
            result.status_counts["error"] = result.status_counts.get("error", 0) + 1
    return result


@dataclass(frozen=True)
class CapacityPoint:
    concurrency: int
    throughput_rps: float
    error_rate: float
    p99_ms: float


def capacity_search(
    transport_factory: Callable[[int], Transport],
    *,
    method: str = "GET",
    path: str = "/",
    concurrency_levels: tuple[int, ...] = (1, 2, 4, 8, 16),
    requests_per_level: int = 200,
    saturation_error_rate: float = 0.05,
) -> list[CapacityPoint]:
    """Find the saturation point by sweeping concurrency levels.

    ``transport_factory(concurrency)`` returns a transport that simulates the
    target at that concurrency (e.g. a thread pool or a model). Deterministic.
    """
    points: list[CapacityPoint] = []
    for conc in concurrency_levels:
        transport = transport_factory(conc)
        latencies: list[float] = []
        errors = 0
        for _ in range(requests_per_level):
            try:
                _, latency = transport(method, path)
                latencies.append(latency)
            except Exception:
                errors += 1
        total = len(latencies) + errors
        err_rate = errors / max(total, 1)
        # throughput modeled as concurrency / mean latency
        mean_s = (sum(latencies) / len(latencies) / 1000.0) if latencies else 1.0
        points.append(
            CapacityPoint(
                concurrency=conc,
                throughput_rps=conc / max(mean_s, 1e-9),
                error_rate=err_rate,
                p99_ms=_pct(latencies, 99),
            )
        )
        if err_rate > saturation_error_rate:
            break  # saturated; stop climbing
    return points
