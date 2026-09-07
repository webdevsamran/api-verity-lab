"""Statistically sound regression gates (#24).

The point of these is not that the arithmetic is right -- it is that the gate
behaves correctly in the two situations that matter: it stays quiet when
nothing changed, and it fires when something did. Both are exercised against
samples rather than mocked verdicts.
"""

from __future__ import annotations

import random

import pytest

from apiverity.performance.engine import (
    OperationStats,
    PerformanceReport,
    compare_baseline,
    parse_tolerance,
)
from apiverity.performance.stats import (
    bootstrap_percentile_ci,
    bootstrap_throughput_ci,
    overlaps,
    percentile,
    wilson_interval,
)

_CI_FIELDS = (
    "p50_ci95",
    "p90_ci95",
    "p95_ci95",
    "p99_ci95",
    "throughput_ci95",
    "error_rate_ci95",
)


# ----------------------------------------------------------------- estimators


def test_percentile_uses_nearest_rank_not_a_floor_index() -> None:
    """The old `int(n * pct / 100)` was one rank high on every percentile.

    With 20 samples it selected index 10 for p50 -- the 11th value -- so the
    reported median was above the actual one, and every percentile inherited
    the same upward bias.
    """
    samples = [float(x) for x in range(1, 21)]
    assert percentile(samples, 50) == 10.0
    assert percentile(samples, 90) == 18.0
    assert percentile(samples, 95) == 19.0
    assert percentile(samples, 99) == 20.0
    # The defect, stated directly.
    assert percentile(samples, 50) != samples[int(len(samples) * 50 / 100)]


def test_percentile_handles_degenerate_input() -> None:
    assert percentile([], 95) == 0.0
    assert percentile([4.0], 50) == 4.0
    assert percentile([4.0], 99) == 4.0
    assert percentile([2.0, 1.0, 3.0], 50) == 2.0, "must sort its input"


def test_intervals_are_deterministic() -> None:
    """A gate whose verdict changes when nothing changed is not a gate."""
    samples = [float(x) for x in range(1, 41)]
    assert bootstrap_percentile_ci(samples, 95) == bootstrap_percentile_ci(samples, 95)
    assert bootstrap_throughput_ci(samples) == bootstrap_throughput_ci(samples)


def test_an_interval_needs_enough_samples_to_mean_anything() -> None:
    assert bootstrap_percentile_ci([1.0, 2.0, 3.0], 95) is None
    assert bootstrap_throughput_ci([1.0, 2.0, 3.0]) is None
    assert wilson_interval(0, 0) is None


def test_an_interval_brackets_its_estimate() -> None:
    rng = random.Random(11)
    samples = [rng.gauss(100, 10) for _ in range(80)]
    interval = bootstrap_percentile_ci(samples, 95)
    assert interval is not None
    assert interval.low <= percentile(samples, 95) <= interval.high
    assert interval.samples == 80


def test_more_samples_narrows_the_interval() -> None:
    rng = random.Random(5)
    small = [rng.gauss(50, 8) for _ in range(10)]
    large = [rng.gauss(50, 8) for _ in range(400)]
    narrow = bootstrap_percentile_ci(large, 50)
    wide = bootstrap_percentile_ci(small, 50)
    assert narrow is not None and wide is not None
    assert (narrow.high - narrow.low) < (wide.high - wide.low)


def test_wilson_does_not_claim_certainty_from_zero_errors() -> None:
    """Wald gives [0, 0] here, which is a claim 40 clean requests cannot make."""
    interval = wilson_interval(0, 40)
    assert interval is not None
    assert interval.low == 0.0
    assert interval.high > 0.0, "no errors yet is not the same as no errors possible"
    assert wilson_interval(0, 400) is not None
    tighter = wilson_interval(0, 400)
    assert tighter is not None and tighter.high < interval.high


def test_overlap_treats_the_unknown_as_indistinguishable() -> None:
    a = bootstrap_percentile_ci([float(x) for x in range(40)], 95)
    assert overlaps(a, None)
    assert overlaps(None, None)


# ----------------------------------------------------------------- tolerances


def test_tolerance_accepts_a_bare_number_and_per_metric_assignments() -> None:
    assert parse_tolerance(None)["p95"] == 20.0
    assert parse_tolerance(["15"])["p95"] == 15.0
    mixed = parse_tolerance(["5", "p95=10", "error_rate=0"])
    assert mixed["p95"] == 10.0
    assert mixed["error_rate"] == 0.0
    assert mixed["p50"] == 5.0, "a bare number sets the metrics not named explicitly"


def test_tolerance_rejects_an_unknown_metric_by_listing_the_real_ones() -> None:
    with pytest.raises(ValueError, match="unknown metric 'p42'"):
        parse_tolerance(["p42=1"])
    with pytest.raises(ValueError, match="p95"):
        parse_tolerance(["p42=1"])


def test_tolerance_rejects_a_non_number() -> None:
    with pytest.raises(ValueError, match="not a number"):
        parse_tolerance(["p95=fast"])
    with pytest.raises(ValueError, match="not a number"):
        parse_tolerance(["quite a lot"])


# ------------------------------------------------------------------ the gate


def _stats(key: str, samples: list[float], *, errors: int = 0) -> OperationStats:
    def bounds(pct: float) -> tuple[float, float] | None:
        interval = bootstrap_percentile_ci(samples, pct)
        return None if interval is None else (interval.low, interval.high)

    throughput = bootstrap_throughput_ci(samples)
    error_rate = wilson_interval(errors, len(samples))
    total = sum(samples) or 1.0
    return OperationStats(
        operation_key=key,
        requests=len(samples),
        samples=len(samples),
        errors=errors,
        p50_ms=round(percentile(samples, 50), 2),
        p90_ms=round(percentile(samples, 90), 2),
        p95_ms=round(percentile(samples, 95), 2),
        p99_ms=round(percentile(samples, 99), 2),
        p50_ci95=bounds(50),
        p90_ci95=bounds(90),
        p95_ci95=bounds(95),
        p99_ci95=bounds(99),
        throughput_rps=round(len(samples) / total * 1000, 2),
        throughput_ci95=None if throughput is None else (throughput.low, throughput.high),
        error_rate_pct=round(100.0 * errors / max(len(samples), 1), 4),
        error_rate_ci95=None if error_rate is None else (error_rate.low, error_rate.high),
    )


def _report(stats: OperationStats) -> PerformanceReport:
    return PerformanceReport(target="http://t", operations=[stats])


def _baseline(stats: OperationStats) -> dict:
    return _report(stats).model_dump(mode="json")


def test_noise_does_not_fire_the_gate() -> None:
    """Two draws from the same distribution. Any "regressed" here is false."""
    rng = random.Random(21)
    before = _stats("GET /a", [rng.gauss(100, 6) for _ in range(120)])
    after = _stats("GET /a", [rng.gauss(100, 6) for _ in range(120)])
    verdicts = compare_baseline(_report(after), _baseline(before))
    assert verdicts.regressions == [], verdicts.regressions


def test_a_real_slowdown_does_fire_the_gate() -> None:
    rng = random.Random(22)
    before = _stats("GET /a", [rng.gauss(100, 6) for _ in range(120)])
    after = _stats("GET /a", [rng.gauss(180, 6) for _ in range(120)])
    verdicts = compare_baseline(_report(after), _baseline(before))
    assert any("p95 regressed" in v for v in verdicts.regressions), verdicts
    assert any("throughput regressed" in v for v in verdicts.regressions), verdicts


def test_a_difference_inside_the_noise_is_called_inconclusive_not_clean() -> None:
    """The distinction that matters: "we cannot tell" is not "it is fine".

    A gate that silently passes a change it lacked the samples to evaluate
    looks identical to one that checked and found nothing.
    """
    rng = random.Random(23)
    before = _stats("GET /a", [rng.gauss(100, 30) for _ in range(12)])
    after = _stats("GET /a", [rng.gauss(140, 30) for _ in range(12)])
    verdicts = compare_baseline(_report(after), _baseline(before), tolerance_pct=5.0)
    assert verdicts.inconclusive, verdicts
    assert any("raise --iterations" in v for v in verdicts.inconclusive)
    assert verdicts.regressions == [], "an unresolvable difference must not fail a build"


def test_a_baseline_without_intervals_still_gates_on_tolerance() -> None:
    """Older baselines predate intervals; they must not silently pass.

    This is the failure the guard introduced and the reason it checks that
    *both* sides have an interval: `overlaps(None, None)` is True, so an
    unconditional skip turned every stale baseline into a no-op gate.
    """
    rng = random.Random(24)
    before = _stats("GET /a", [rng.gauss(100, 4) for _ in range(60)])
    after = _stats("GET /a", [rng.gauss(200, 4) for _ in range(60)])
    stale = _baseline(before)
    for op in stale["operations"]:
        for field in _CI_FIELDS:
            op[field] = None
    naked = after.model_copy(deep=True)
    for field in _CI_FIELDS:
        setattr(naked, field, None)
    verdicts = compare_baseline(_report(naked), stale)
    assert any("regressed" in v for v in verdicts.regressions), verdicts


def test_per_metric_tolerance_is_applied_per_metric() -> None:
    rng = random.Random(25)
    before = _stats("GET /a", [rng.gauss(100, 3) for _ in range(80)])
    after = _stats("GET /a", [rng.gauss(112, 3) for _ in range(80)])
    loose = compare_baseline(_report(after), _baseline(before), tolerance_pct={"p95": 50.0})
    strict = compare_baseline(_report(after), _baseline(before), tolerance_pct={"p95": 1.0})
    assert not [v for v in loose.regressions if "p95 regressed" in v]
    assert any("p95 regressed" in v for v in strict.regressions), strict


def test_a_new_error_is_always_reported() -> None:
    rng = random.Random(26)
    samples = [rng.gauss(100, 3) for _ in range(60)]
    before = _stats("GET /a", samples)
    after = _stats("GET /a", samples, errors=3)
    verdicts = compare_baseline(_report(after), _baseline(before))
    assert any("new errors appeared (3)" in v for v in verdicts.regressions), verdicts


def test_an_operation_missing_from_the_baseline_is_skipped_not_invented() -> None:
    rng = random.Random(27)
    after = _stats("GET /new", [rng.gauss(100, 3) for _ in range(40)])
    empty = compare_baseline(_report(after), {"operations": []})
    assert empty.regressions == [] and empty.inconclusive == []


# --------------------------------------------------------------------- warmup


def test_warmup_requests_are_made_but_not_measured() -> None:
    """`requests` counts what was sent, `samples` what was measured.

    Reporting only one number makes "p95 of 60 samples after 20 warmup" and
    "p95 of 80 cold samples" look identical.
    """
    import httpx

    from apiverity.core.model import Operation, Protocol, Server, Service

    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json={})

    service = Service(
        title="T",
        version="1.0.0",
        protocol=Protocol.OPENAPI,
        servers=[Server(url="http://t")],
        operations=[Operation(method="GET", path="/a", responses=[])],
    )
    transport = httpx.MockTransport(handler)
    real_client = httpx.Client

    class Patched(real_client):  # type: ignore[misc, valid-type]
        def __init__(self, **kwargs: object) -> None:
            kwargs["transport"] = transport
            super().__init__(**kwargs)  # type: ignore[arg-type]

    import apiverity.performance.engine as engine

    original = engine.httpx.Client
    engine.httpx.Client = Patched  # type: ignore[misc]
    try:
        report = engine.measure(service, "http://t", iterations=10, warmup=4)
    finally:
        engine.httpx.Client = original  # type: ignore[misc]

    stats = report.operations[0]
    assert len(seen) == 14, "warmup requests must actually be sent"
    assert stats.requests == 14
    assert stats.samples == 10
    assert stats.warmup == 4
