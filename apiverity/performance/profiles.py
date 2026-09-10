"""Declarative arrival-rate load: constant, ramp, spike, soak, Poisson.

`PRODUCT_GAPS.md` answers "why is there no scripting-language load engine"
with *"declarative profiles + budgets"*. This module is the first half of that
sentence, and until now no command reached it -- `--profile` on the command
line is the *severity* profile, and there is no flag anywhere that takes a
load shape. `apiverity regression --shape` is that flag.

## Open loop, which is the whole point

`regression` and `regression --curve` are **closed loop**: N workers each send
a request, wait for the answer, and send the next. Offered load falls as the
service slows, which is what you want when the question is "how does it behave
at concurrency 16".

A profile is **open loop**: requests are due at fixed times regardless of
whether earlier ones have come back. That is the only way to ask "what happens
at 200 requests per second" -- under a closed loop, a service that stalls
simply receives less traffic and never shows the queue building.

The two answer different questions and neither replaces the other.

## The schedule used to be decorative

`execute` took the offsets `schedule` computes and threw every one of them
away: `for _offset in schedule(profile)`. Requests went out back to back as
fast as the transport returned. So a ramp, a spike, a soak and a Poisson
arrival process all produced the same run, differing only in how many requests
it contained -- and the shape, which is the entire content of a load profile,
did nothing. Offsets are honoured now, and `ProfileResult` reports how well.

## Reporting the generator's own failure

A load generator that cannot keep up with its own schedule is measuring itself.
`ProfileResult.late_ms` is the gap between when each request was due and when
it actually went out, and `achieved_rps` is what the run offered against what
the profile asked for -- measured over the dispatch window, not over the total,
because how long the last responses take to drain is the service's business
and dividing by it reports a rate nobody offered. Both are reported beside the latencies rather than
folded into them, because "p99 was 900ms" means something different when the
client was three seconds behind schedule -- the distinction k6 draws with
`dropped_iterations`, and one this project would otherwise be silently on the
wrong side of.

Nothing is dropped. Every scheduled request is dispatched, late if it has to
be, and `scheduled == sent + errors` always holds. A generator that silently
discarded a backlog would report a clean run of a profile it did not execute.

## What was deleted

`capacity_search` was here, reachable from nothing, and published as EXISTING.
It swept concurrency levels against a `transport_factory(concurrency)` the
caller supplies -- so it never sent a request, and the numbers it produced were
whatever the caller's model said. `apiverity/performance/curve.py` does the
real version against a real target and `regression --curve` runs it. Two
implementations of one idea, one of them a simulation nothing called, is worse
than one.
"""

from __future__ import annotations

import random
import re
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field

Transport = Callable[[str, str], tuple[int, float]]

#: Scheduling resolution. 20 Hz: fine enough that a 60-second ramp changes rate
#: 1,200 times, coarse enough that the scheduler is not itself the load.
_STEP = 0.05

#: How late a dispatch may be before the run stops describing its own profile.
#:
#: One scheduling step, because that is the resolution the schedule is built at
#: and being under one step late is the closest a run can come to honouring it.
#: A fixed wall-clock figure would mean different things at different rates:
#: 250 ms is five slots at 20 requests a second and a fiftieth of one at 4.
SCHEDULE_TOLERANCE_MS = _STEP * 1000.0


@dataclass(frozen=True)
class LoadProfile:
    kind: str  # constant | ramp | spike | soak
    duration_seconds: float
    rate_start: float  # requests/second
    rate_end: float | None = None  # for ramp; None = constant
    spike_at: float | None = None  # fraction of duration where spike occurs
    spike_multiplier: float = 5.0
    poisson: bool = False
    seed: int = 0

    def describe(self) -> str:
        """One line, for a report that has to say what it ran."""
        rate = f"{self.rate_start:g}/s"
        if self.kind == "ramp" and self.rate_end is not None:
            rate = f"{self.rate_start:g}/s -> {self.rate_end:g}/s"
        if self.kind == "spike" and self.spike_at is not None:
            rate += f", {self.spike_multiplier:g}x at {self.spike_at * 100:.0f}%"
        arrivals = "Poisson arrivals" if self.poisson else "even arrivals"
        return f"{self.kind} {self.duration_seconds:g}s at {rate} ({arrivals}, seed {self.seed})"


#: `constant:30s@10`, `ramp:60s@1..20`, `spike:60s@10x6@50%`, `soak:600s@5`,
#: with an optional `+poisson` and `+seed=N`.
_SPEC = re.compile(
    r"^(?P<kind>constant|ramp|spike|soak)"
    r":(?P<duration>\d+(?:\.\d+)?)s"
    r"@(?P<rate>\d+(?:\.\d+)?)"
    r"(?:\.\.(?P<rate_end>\d+(?:\.\d+)?))?"
    r"(?:x(?P<multiplier>\d+(?:\.\d+)?))?"
    r"(?:@(?P<at>\d+(?:\.\d+)?)%)?"
    r"(?P<flags>(?:\+[a-z]+(?:=\d+)?)*)$"
)


def parse_profile(text: str) -> LoadProfile:
    """A profile from the string a command line carries.

    Refuses what it cannot read rather than falling back to a default. A load
    generator that quietly ran `constant` when the operator typed `ramp` would
    produce a report describing a shape that never happened.
    """
    match = _SPEC.match(text.strip())
    if not match:
        raise ValueError(
            f"cannot read load shape {text!r}; expected forms like 'constant:30s@10', "
            "'ramp:60s@1..20', 'spike:60s@10x6@50%', 'soak:600s@5', "
            "each optionally '+poisson' and '+seed=7'"
        )
    flags = match.group("flags") or ""
    seed_match = re.search(r"\+seed=(\d+)", flags)
    unknown = [f for f in re.findall(r"\+([a-z]+)", flags) if f not in ("poisson", "seed")]
    if unknown:
        raise ValueError(f"unknown load-shape flag(s) {unknown}; known: +poisson, +seed=N")

    kind = match.group("kind")
    rate_end = float(match.group("rate_end")) if match.group("rate_end") else None
    if kind == "ramp" and rate_end is None:
        raise ValueError("a ramp needs an end rate: 'ramp:60s@1..20'")
    if kind != "ramp" and rate_end is not None:
        raise ValueError(f"'{kind}' takes one rate; '..' is for a ramp")
    if kind == "spike" and match.group("multiplier") is None:
        raise ValueError("a spike needs a multiplier: 'spike:60s@10x6' (six times the rate)")
    return LoadProfile(
        kind=kind,
        duration_seconds=float(match.group("duration")),
        rate_start=float(match.group("rate")),
        rate_end=rate_end,
        spike_at=(float(match.group("at")) / 100.0 if match.group("at") else 0.5)
        if kind == "spike"
        else None,
        spike_multiplier=float(match.group("multiplier") or 5.0),
        poisson="+poisson" in flags,
        seed=int(seed_match.group(1)) if seed_match else 0,
    )


@dataclass
class ProfileResult:
    profile: str
    sent: int = 0
    errors: int = 0
    latencies_ms: list[float] = field(default_factory=list)
    status_counts: dict[str, int] = field(default_factory=dict)
    #: How many requests the schedule called for, all of which are dispatched.
    #: `scheduled == sent + errors`: `sent` counts the ones that came back with
    #: a status, `errors` the ones where the transport raised.
    scheduled: int = 0
    #: Per request, how far behind schedule its dispatch was.
    late_ms: list[float] = field(default_factory=list)
    #: Wall-clock seconds from the first dispatch to the last. This is the
    #: window the offered rate is measured over.
    dispatch_s: float = 0.0
    #: Wall-clock seconds until the last response came back, which is longer
    #: than `dispatch_s` by however long the tail took to drain. Reported
    #: separately: dividing requests by *this* would report a rate the profile
    #: never asked for and the generator never offered.
    duration_s: float = 0.0

    @property
    def p50(self) -> float:
        return _pct(self.latencies_ms, 50)

    @property
    def p95(self) -> float:
        return _pct(self.latencies_ms, 95)

    @property
    def p99(self) -> float:
        return _pct(self.latencies_ms, 99)

    @property
    def achieved_rps(self) -> float:
        """Requests put on the wire per second, over the dispatch window.

        Compare it against the profile's own rate: a large gap means the
        generator, not the service, decided how much traffic there was.

        Divided by `dispatch_s`, not `duration_s`. An open-loop profile
        controls when requests *go out*; how long the last responses take to
        come back is the service's business. Measured over the total, a 2-second
        profile whose tail drained for another second reported two thirds of the
        rate it had actually offered -- which reads as a generator that fell
        behind and was nothing of the kind.
        """
        return self.scheduled / self.dispatch_s if self.dispatch_s > 0 else 0.0

    @property
    def max_late_ms(self) -> float:
        return max(self.late_ms) if self.late_ms else 0.0

    def kept_up(self, tolerance_ms: float | None = None) -> bool:
        """Whether the generator stayed on schedule closely enough to believe.

        Not a pass/fail on the service. It is a statement about this run: with
        requests going out seconds after they were due, the latencies describe
        a service under a load nobody asked for.

        The default is `SCHEDULE_TOLERANCE_MS`, which is one scheduling step.
        """
        return self.max_late_ms <= (SCHEDULE_TOLERANCE_MS if tolerance_ms is None else tolerance_ms)


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
    while t < profile.duration_seconds:
        frac = t / max(profile.duration_seconds, 1e-9)
        rate = profile.rate_start + (rate_end - profile.rate_start) * frac
        if profile.kind == "spike" and profile.spike_at is not None:
            window = abs(frac - profile.spike_at) < 0.02
            if window:
                rate *= profile.spike_multiplier
        expected = rate * _STEP
        if profile.poisson:
            count = _poisson(rng, expected)
        else:
            count = int(expected) + (1 if rng.random() < (expected - int(expected)) else 0)
        for i in range(count):
            offsets.append(t + (i / max(count, 1)) * _STEP)
        t += _STEP
    return offsets


def _poisson(rng: random.Random, mean: float) -> int:
    """Knuth's algorithm. Small means only, which is all a 50ms window has."""
    if mean <= 0:
        return 0
    limit = pow(2.718281828459045, -mean)
    k = 0
    p = 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1
        if k > 1000:  # pragma: no cover - a 50ms window never reaches this
            return k


def execute(
    profile: LoadProfile,
    transport: Transport,
    *,
    method: str = "GET",
    path: str = "/",
    max_requests: int = 100_000,
    workers: int = 64,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> ProfileResult:
    """Run the schedule against the transport, at the times it names.

    Open loop: a request is dispatched when its offset arrives whether or not
    earlier ones have returned, which needs a worker pool -- with one thread,
    a slow response delays every arrival behind it and the run silently becomes
    closed-loop.

    `sleep` and `clock` are injected so a test can run a sixty-second profile
    without taking sixty seconds. A load test whose own tests need a minute
    each is a load test nobody changes.
    """
    offsets = schedule(profile)[:max_requests]
    result = ProfileResult(profile=profile.describe(), scheduled=len(offsets))
    if not offsets:
        return result

    started = clock()
    pending: list[tuple[Future[tuple[int, float]], float]] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for offset in offsets:
            due = started + offset
            wait = due - clock()
            if wait > 0:
                sleep(wait)
            # Measured after the sleep, not from it: the question is when the
            # request actually went out, and a sleep that overshoots is
            # exactly the case this is here to catch.
            result.late_ms.append(max(0.0, (clock() - due) * 1000.0))
            pending.append((pool.submit(transport, method, path), due))
        result.dispatch_s = clock() - started
        for future, _due in pending:
            _collect(result, future)
    result.duration_s = clock() - started
    return result


def _collect(result: ProfileResult, future: Future[tuple[int, float]]) -> None:
    try:
        status, latency = future.result()
    except Exception:
        result.errors += 1
        result.status_counts["error"] = result.status_counts.get("error", 0) + 1
        return
    result.sent += 1
    result.latencies_ms.append(latency)
    key = f"{int(status) // 100}xx"
    result.status_counts[key] = result.status_counts.get(key, 0) + 1


__all__ = [
    "SCHEDULE_TOLERANCE_MS",
    "LoadProfile",
    "ProfileResult",
    "Transport",
    "execute",
    "parse_profile",
    "schedule",
]
