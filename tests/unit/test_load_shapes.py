"""Load shapes, and the schedule that used to be thrown away.

`PRODUCT_GAPS.md` answers "why is there no scripting-language load engine" with
"declarative profiles + budgets". Two things were wrong with that.

`apiverity.performance.profiles` was reachable from no command -- `--profile`
is the *severity* profile and there was no flag anywhere that took a load
shape. And `execute` computed the schedule and discarded every offset
(`for _offset in schedule(profile)`), firing requests back to back as fast as
the transport returned. A ramp, a spike, a soak and a Poisson arrival process
produced the same run, differing only in how many requests it contained.

So the shape -- the entire content of a load profile -- did nothing, in the
module named as this project's answer to k6.
"""

from __future__ import annotations

import contextlib
import io
import json
from typing import Any

import pytest

from apiverity.cli.main import main
from apiverity.performance.profiles import (
    LoadProfile,
    execute,
    parse_profile,
    schedule,
)

_SPEC = "fixtures/apis/crud/openapi.yaml"


class Clock:
    """Virtual time: nothing passes except what `sleep` is told to pass.

    A test that had to wait sixty seconds to check a sixty-second ramp is a
    test nobody runs, and a load generator whose tests nobody runs is where
    a discarded schedule survives for a release.
    """

    def __init__(self, overshoot: float = 0.0) -> None:
        self.t = 0.0
        self.overshoot = overshoot
        self.slept: list[float] = []

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.t += seconds + self.overshoot


def _transport(status: int = 200, latency: float = 5.0) -> Any:
    def send(_method: str, _path: str) -> tuple[int, float]:
        return status, latency

    return send


# ------------------------------------------------------------------ parsing


@pytest.mark.parametrize(
    ("text", "kind", "duration", "rate"),
    [
        ("constant:30s@10", "constant", 30.0, 10.0),
        ("soak:600s@5", "soak", 600.0, 5.0),
        ("ramp:60s@1..20", "ramp", 60.0, 1.0),
        ("spike:60s@10x6@50%", "spike", 60.0, 10.0),
    ],
)
def test_the_four_shapes_parse(text: str, kind: str, duration: float, rate: float) -> None:
    profile = parse_profile(text)
    assert (profile.kind, profile.duration_seconds, profile.rate_start) == (kind, duration, rate)


def test_a_ramp_carries_its_end_rate_and_a_spike_its_multiplier() -> None:
    assert parse_profile("ramp:60s@1..20").rate_end == 20.0
    spike = parse_profile("spike:60s@10x6@50%")
    assert (spike.spike_multiplier, spike.spike_at) == (6.0, 0.5)


def test_flags_are_read_and_unknown_ones_are_refused() -> None:
    profile = parse_profile("constant:30s@10+poisson+seed=7")
    assert profile.poisson and profile.seed == 7
    with pytest.raises(ValueError, match="unknown load-shape flag"):
        parse_profile("constant:30s@10+gaussian")


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("ramp:60s@10", "a ramp needs an end rate"),
        ("constant:60s@1..20", "'\\.\\.' is for a ramp"),
        ("spike:60s@10", "a spike needs a multiplier"),
        ("60s@10", "cannot read load shape"),
        ("constant:60@10", "cannot read load shape"),
        ("stampede:60s@10", "cannot read load shape"),
    ],
)
def test_what_cannot_be_read_is_refused_rather_than_defaulted(text: str, message: str) -> None:
    """A generator that quietly ran `constant` when the operator typed `ramp`
    would produce a report describing a shape that never happened."""
    with pytest.raises(ValueError, match=message):
        parse_profile(text)


def test_the_description_says_what_will_run() -> None:
    assert parse_profile("ramp:60s@1..20+poisson").describe() == (
        "ramp 60s at 1/s -> 20/s (Poisson arrivals, seed 0)"
    )


# ------------------------------------------------- the schedule is honoured


def test_requests_go_out_at_the_times_the_schedule_names() -> None:
    """The defect this file exists for. Every offset was discarded, so a
    profile's shape changed nothing but the request count."""
    profile = LoadProfile(kind="constant", duration_seconds=2.0, rate_start=10)
    offsets = schedule(profile)
    clock = Clock()

    result = execute(profile, _transport(), sleep=clock.sleep, clock=clock.now)

    assert result.scheduled == len(offsets)
    # Time advanced to the last offset, which only happens if each one was
    # waited for. Back-to-back dispatch leaves the clock at zero.
    assert clock.now() == pytest.approx(offsets[-1], abs=1e-6)
    assert sum(clock.slept) == pytest.approx(offsets[-1], abs=1e-6)


def test_a_ramp_and_a_soak_of_the_same_length_take_the_same_time_and_differ_in_load() -> None:
    """Under the old `execute` these two were indistinguishable except by
    count. The distinguishing fact is *when* the requests went out."""
    ramp = LoadProfile(kind="ramp", duration_seconds=4.0, rate_start=1, rate_end=20)
    soak = LoadProfile(kind="soak", duration_seconds=4.0, rate_start=10)
    early_ramp = len([o for o in schedule(ramp) if o < 1.0])
    early_soak = len([o for o in schedule(soak) if o < 1.0])
    assert early_ramp < early_soak


def test_a_generator_that_falls_behind_says_so() -> None:
    """A load generator that cannot keep up with its own schedule is measuring
    itself, and a p99 from such a run describes a load nobody asked for."""
    profile = LoadProfile(kind="constant", duration_seconds=1.0, rate_start=10)
    behind = Clock(overshoot=0.4)

    result = execute(profile, _transport(), sleep=behind.sleep, clock=behind.now)

    assert result.max_late_ms > 250
    assert not result.kept_up()


def test_a_generator_that_keeps_up_says_that_too() -> None:
    profile = LoadProfile(kind="constant", duration_seconds=1.0, rate_start=10)
    result = execute(profile, _transport(), sleep=Clock().sleep, clock=Clock().now)
    assert result.kept_up()


def test_every_scheduled_request_is_accounted_for() -> None:
    """`scheduled == sent + errors`. A generator that silently discarded a
    backlog would report a clean run of a profile it did not execute."""
    calls = {"n": 0}

    def flaky(_method: str, _path: str) -> tuple[int, float]:
        calls["n"] += 1
        if calls["n"] % 4 == 0:
            raise ConnectionError("refused")
        return (500 if calls["n"] % 3 == 0 else 200), 8.0

    clock = Clock()
    profile = LoadProfile(kind="constant", duration_seconds=1.0, rate_start=20)
    result = execute(profile, flaky, sleep=clock.sleep, clock=clock.now)

    assert result.scheduled == result.sent + result.errors
    assert result.status_counts.get("2xx") and result.status_counts.get("5xx")
    assert result.status_counts.get("error") == result.errors


def test_the_achieved_rate_is_measured_not_assumed() -> None:
    profile = LoadProfile(kind="constant", duration_seconds=2.0, rate_start=10)
    clock = Clock()
    result = execute(profile, _transport(), sleep=clock.sleep, clock=clock.now)
    assert result.achieved_rps == pytest.approx(result.sent / result.duration_s)
    assert 8.0 < result.achieved_rps < 12.0


def test_an_empty_schedule_runs_nothing_rather_than_dividing_by_zero() -> None:
    result = execute(
        LoadProfile(kind="constant", duration_seconds=0.0, rate_start=10), _transport()
    )
    assert (result.scheduled, result.sent, result.achieved_rps) == (0, 0, 0.0)


def test_capacity_search_is_gone() -> None:
    """It swept concurrency against a transport the *caller* supplied, so it
    never sent a request and its numbers were whatever the caller's model
    said. `regression --curve` does the real version against a real target."""
    import apiverity.performance.profiles as profiles

    assert not hasattr(profiles, "capacity_search")
    assert not hasattr(profiles, "CapacityPoint")


# ------------------------------------------------------------ the command


def _run(argv: list[str]) -> tuple[int, str, dict[str, Any]]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    try:
        return code, err.getvalue(), json.loads(out.getvalue())
    except ValueError:
        return code, err.getvalue(), {}


def _shape(*extra: str) -> list[str]:
    return [
        "--no-config",
        "regression",
        _SPEC,
        "--base-url",
        "http://127.0.0.1:1",
        "--shape",
        "constant:1s@2",
        *extra,
    ]


def test_a_shape_without_an_operation_is_refused() -> None:
    """A rate is stated for one endpoint. Applying `constant:60s@50` to forty
    operations means two thousand requests a second at a target the operator
    asked fifty of."""
    code, err, _ = _run(_shape())
    assert code != 0
    assert "--shape needs --operation" in err


def test_an_unknown_operation_lists_the_ones_there_are() -> None:
    code, err, _ = _run(_shape("--operation", "GET /nope"))
    assert code != 0
    assert "no operation 'GET /nope'" in err
    assert "GET /users" in err


def test_an_unreadable_shape_is_refused_by_the_command_too() -> None:
    argv = _shape("--operation", "GET /users")
    argv[argv.index("constant:1s@2")] = "constant:1s"
    code, err, _ = _run(argv)
    assert code != 0
    assert "cannot read load shape" in err


def test_a_templated_path_is_refused_with_the_flag_that_fixes_it() -> None:
    """`/users/{id}` is not a URL, and there is nothing here that knows a real
    id -- filling one in would send thousands of requests at a guess."""
    code, err, _ = _run(_shape("--operation", "GET /users/{id}"))
    assert code != 0
    assert "--path" in err and "template" in err


def test_a_mutating_method_needs_saying_so() -> None:
    code, err, _ = _run(_shape("--operation", "POST /users"))
    assert code != 0
    assert "--include-mutations" in err
    assert "writes to the target" in err
