"""Percentiles and confidence intervals for latency samples (#24).

A regression gate that compares two point estimates fails the same way every
time: twenty requests produce a p95 that moves by tens of percent between
identical runs, so the gate either fires constantly and gets disabled, or is
loosened until it cannot detect anything. The fix is not a bigger tolerance,
it is reporting how uncertain the number is and refusing to call a difference
a regression when the two intervals overlap.

Bootstrap rather than a closed form: latency distributions are heavily
right-skewed and a percentile of a skewed sample has no usable normal
approximation. Resampling makes no distributional assumption, and the seed is
fixed so the same samples always produce the same interval -- a gate whose
verdict changes when nothing changed is not a gate.

No numpy or scipy: this is a CLI whose install cost matters, and the whole
implementation is fifty lines.
"""

from __future__ import annotations

import random
from typing import NamedTuple

__all__ = [
    "Interval",
    "bootstrap_percentile_ci",
    "bootstrap_throughput_ci",
    "overlaps",
    "percentile",
    "wilson_interval",
]

# Enough resamples that the interval is stable to the two decimals we report;
# beyond this the endpoints stop moving and it is just slower.
_RESAMPLES = 2000
_SEED = 20260907


class Interval(NamedTuple):
    """A confidence interval, and the sample size it was computed from.

    `samples` travels with the bounds on purpose: an interval from 5 requests
    and one from 500 are not comparable claims, and a reader who sees only the
    bounds cannot tell them apart.
    """

    low: float
    high: float
    samples: int


def percentile(samples: list[float], pct: float) -> float:
    """The `pct`-th percentile by the nearest-rank method, on unsorted input.

    Nearest rank (ceil(n * p / 100), 1-based) rather than the floor-index
    arithmetic this replaced: with 20 samples, `int(20 * 50 / 100)` selects
    index 10, the 11th value, so a p50 was reported one rank above the median
    and every percentile was biased upward by one position. Nearest rank is
    also the definition the docs claim, which the old code did not implement.
    """
    if not samples:
        return 0.0
    ordered = sorted(samples)
    rank = max(1, min(len(ordered), -(-len(ordered) * int(pct) // 100)))
    return ordered[rank - 1]


def bootstrap_percentile_ci(
    samples: list[float], pct: float, *, confidence: float = 0.95
) -> Interval | None:
    """A percentile bootstrap interval for a percentile of `samples`.

    Returns None below four samples. An interval from three requests is
    arithmetically computable and completely uninformative, and reporting one
    invites a reader to believe a gate is measuring something it is not.
    """
    n = len(samples)
    if n < 4:
        return None
    rng = random.Random(_SEED)
    ordered = sorted(samples)
    estimates = []
    for _ in range(_RESAMPLES):
        resample = [ordered[rng.randrange(n)] for _ in range(n)]
        estimates.append(percentile(resample, pct))
    estimates.sort()
    tail = (1.0 - confidence) / 2.0
    low = estimates[max(0, int(tail * _RESAMPLES) - 1)]
    high = estimates[min(_RESAMPLES - 1, int((1.0 - tail) * _RESAMPLES))]
    return Interval(round(low, 2), round(high, 2), n)


def overlaps(a: Interval | None, b: Interval | None) -> bool:
    """Whether two intervals overlap, i.e. the difference is not resolvable.

    Missing intervals count as overlapping. "We do not know" must not be
    reported as "we detected a regression"; the caller falls back to the
    tolerance check, which is what it did before intervals existed.
    """
    if a is None or b is None:
        return True
    return a.low <= b.high and b.low <= a.high


def bootstrap_throughput_ci(samples: list[float], *, confidence: float = 0.95) -> Interval | None:
    """An interval for sequential throughput, derived from the same samples.

    Throughput was reported as `iterations / wall_clock`: a single ratio from
    a single measurement, with nothing to say how much it would move on a
    rerun. It is also the noisiest thing in the report, because one scheduler
    hiccup anywhere in the run moves the denominator. Gating on it with a flat
    percentage was the least reliable check in the gate.

    Resampling the per-request latencies instead gives requests-per-second the
    same footing as the percentiles beside it. Sequential only, which is what
    `measure` does; under real concurrency this would understate the rate.
    """
    n = len(samples)
    if n < 4:
        return None
    rng = random.Random(_SEED + 1)
    estimates = []
    for _ in range(_RESAMPLES):
        total = 0.0
        for _ in range(n):
            total += samples[rng.randrange(n)]
        estimates.append(n / total * 1000.0 if total > 0 else 0.0)
    estimates.sort()
    tail = (1.0 - confidence) / 2.0
    low = estimates[max(0, int(tail * _RESAMPLES) - 1)]
    high = estimates[min(_RESAMPLES - 1, int((1.0 - tail) * _RESAMPLES))]
    return Interval(round(low, 2), round(high, 2), n)


def wilson_interval(successes: int, n: int, *, confidence: float = 0.95) -> Interval | None:
    """A Wilson score interval for a proportion, as a percentage.

    Error rate is a proportion, not a percentile, so it gets the estimator
    that suits it rather than a bootstrap. Wilson rather than Wald because the
    normal approximation collapses exactly where error rates live: at zero
    errors, Wald gives the interval [0, 0], which claims certainty from a
    sample that has merely not seen a failure yet.
    """
    if n <= 0:
        return None
    # 1.959964 is the two-sided 95% normal quantile; the only confidence
    # levels a CI gate needs are 95% and 99%, so they are tabulated rather
    # than pulling in an inverse-normal implementation for two constants.
    z = {0.95: 1.959964, 0.99: 2.575829}.get(round(confidence, 2), 1.959964)
    phat = successes / n
    denom = 1 + z * z / n
    centre = (phat + z * z / (2 * n)) / denom
    margin = z * ((phat * (1 - phat) / n + z * z / (4 * n * n)) ** 0.5) / denom
    return Interval(
        round(max(0.0, centre - margin) * 100, 4),
        round(min(1.0, centre + margin) * 100, 4),
        n,
    )
