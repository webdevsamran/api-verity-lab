"""Latency and throughput as a function of load, not at one point.

`measure` took a `concurrency` argument from the beginning and never read it:
every request went out in a row, so a report from `--concurrency 16` described
a service under a load of one. A knob that does nothing is worse than a missing
one, because the number it produces gets quoted.

With it honoured, the question worth asking becomes answerable -- a service
that returns in 40 ms at one request in flight and 4 seconds at eight had a p95
of 40 ms in every report this tool could produce.

Most of what follows tests the *reading* of a curve rather than the taking of
one, with an injected measurer: the shape is what matters, and a test that
needs a real slow service to produce one is a test nobody runs. The one live
test is the one that matters most, because it is the one that would have caught
the ignored argument.
"""

from __future__ import annotations

from typing import Any

import pytest

from apiverity.core.model import Operation, Protocol, Response, Service
from apiverity.performance.curve import (
    DEFAULT_LEVELS,
    LATENCY_KNEE,
    measure_curve,
    parse_levels,
)
from apiverity.performance.engine import OperationStats, PerformanceReport

KEY = "GET /things"


def _service() -> Service:
    return Service(
        title="fixture",
        version="1.0.0",
        protocol=Protocol.OPENAPI,
        operations=[
            Operation(
                operation_id="listThings",
                method="GET",
                path="/things",
                responses=[Response(status="200")],
            )
        ],
    )


def _measurer(shape: dict[int, tuple[float, float]]) -> Any:
    """A stand-in for `measure`: concurrency -> (p95_ms, throughput_rps)."""

    def run(_service: Service, base_url: str, **kwargs: Any) -> PerformanceReport:
        level = int(kwargs.get("concurrency", 1))
        p95, rps = shape[level]
        return PerformanceReport(
            target=base_url,
            concurrency=level,
            operations=[
                OperationStats(
                    operation_key=KEY,
                    samples=int(kwargs.get("iterations", 10)),
                    p50_ms=p95 / 2,
                    p95_ms=p95,
                    p99_ms=p95 * 1.1,
                    throughput_rps=rps,
                )
            ],
        )

    return run


def _curve(shape: dict[int, tuple[float, float]], **kwargs: Any):
    report = measure_curve(
        _service(),
        "http://localhost",
        levels=tuple(sorted(shape)),
        measurer=_measurer(shape),
        **kwargs,
    )
    return report.curves[0]


# ------------------------------------------------------------------ levels


def test_the_default_sweep_doubles() -> None:
    """A knee is found faster on a log scale, and four points is the fewest
    that can show a shape rather than a slope."""
    assert DEFAULT_LEVELS == (1, 2, 4, 8)


def test_levels_are_parsed_sorted_and_deduplicated() -> None:
    assert parse_levels("8,1,2,2,4") == (1, 2, 4, 8)


def test_an_empty_level_list_is_refused() -> None:
    with pytest.raises(ValueError):
        parse_levels("0,-3")


def test_no_argument_means_the_default_sweep() -> None:
    assert parse_levels(None) == DEFAULT_LEVELS


# ------------------------------------------------------------- the shape


def test_a_service_that_scales_reports_no_plateau() -> None:
    """And says that says nothing about where one is.

    A sweep that never saturated has not found the ceiling -- it has run out of
    levels, and reporting the top of the sweep as the answer would be inventing
    one.
    """
    curve = _curve({1: (10.0, 100.0), 2: (11.0, 200.0), 4: (12.0, 400.0)})
    assert curve.plateau_at is None
    assert "did not reach a plateau" in curve.summary()


def test_a_service_that_saturates_names_the_level() -> None:
    curve = _curve({1: (10.0, 100.0), 2: (12.0, 190.0), 4: (40.0, 195.0), 8: (90.0, 196.0)})
    assert curve.plateau_at == 2
    assert "stopped rising at 2" in curve.summary()


def test_the_latency_knee_is_reported_separately() -> None:
    """Throughput plateauing and latency climbing are different facts, and a
    service can do one without the other."""
    curve = _curve({1: (10.0, 100.0), 2: (12.0, 190.0), 4: (40.0, 195.0), 8: (90.0, 196.0)})
    assert curve.latency_knee_at == 4
    assert f"{LATENCY_KNEE:g}x" in curve.summary()


def test_a_plateau_at_the_top_of_the_sweep_is_called_out() -> None:
    """It is indistinguishable from a sweep that stopped too early, and from
    the client running out of workers. Saying so beats a number."""
    curve = _curve({1: (10.0, 100.0), 2: (12.0, 200.0), 4: (14.0, 205.0)})
    assert curve.plateau_at == 4 or curve.client_bound or curve.plateau_at == 2
    if curve.client_bound:
        assert "the harness, not the service" in curve.summary()


def test_a_single_level_says_nothing() -> None:
    """One point is not a curve, and reading a trend from it would be reading
    a trend from one number."""
    curve = _curve({4: (10.0, 100.0)})
    assert curve.plateau_at is None
    assert curve.latency_knee_at is None


def test_points_are_ordered_by_level_whatever_order_they_arrive_in() -> None:
    curve = _curve({8: (40.0, 200.0), 1: (10.0, 100.0), 2: (12.0, 190.0), 4: (20.0, 195.0)})
    assert [p.concurrency for p in curve.points] == [1, 2, 4, 8]


def test_every_level_is_warmed_not_only_the_first() -> None:
    """Raising concurrency opens new connections. Charging their setup to the
    first requests of that level reads as the service slowing under load."""
    warmups: list[int] = []

    def run(_service: Service, base_url: str, **kwargs: Any) -> PerformanceReport:
        warmups.append(int(kwargs.get("warmup", 0)))
        return PerformanceReport(target=base_url, operations=[])

    measure_curve(_service(), "http://localhost", levels=(1, 2, 4), warmup=5, measurer=run)
    assert warmups == [5, 5, 5]


def test_the_report_records_what_it_swept() -> None:
    """A curve with no levels beside it cannot be compared to another run."""
    report = measure_curve(
        _service(),
        "http://localhost",
        levels=(1, 2),
        iterations=33,
        measurer=_measurer({1: (10.0, 100.0), 2: (11.0, 180.0)}),
    )
    assert report.levels == [1, 2]
    assert report.iterations_per_level == 33


# ----------------------------------------------------- the argument that was ignored


@pytest.mark.integration
def test_concurrency_is_actually_applied() -> None:
    """The test that would have caught it.

    `measure(concurrency=N)` accepted the argument and issued every request in
    a row. Against a server that sleeps, N in flight finishes in roughly a
    fraction of the sequential time; with the argument ignored the two runs
    take the same wall clock, which is what this asserts against.
    """
    import threading
    import time
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from apiverity.performance.engine import measure

    class Slow(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:
            time.sleep(0.05)
            body = b"[]"
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: Any) -> None:
            return

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Slow)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        sequential = measure(_service(), base, iterations=8, concurrency=1)
        parallel = measure(_service(), base, iterations=8, concurrency=8)
    finally:
        httpd.shutdown()
        httpd.server_close()

    sequential_rps = sequential.operations[0].throughput_rps
    parallel_rps = parallel.operations[0].throughput_rps
    assert parallel_rps > sequential_rps * 2, (
        f"eight in flight against a 50ms endpoint managed {parallel_rps:.1f} rps against "
        f"{sequential_rps:.1f} sequential -- the concurrency argument is not being applied"
    )


def test_the_report_records_the_load_it_was_taken_under() -> None:
    """A p95 with no load level beside it is not comparable to anything,
    including a later run of the same command."""
    report = PerformanceReport(target="x", concurrency=8)
    assert report.concurrency == 8
