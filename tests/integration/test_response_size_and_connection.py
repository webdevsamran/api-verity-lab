"""Two things `capability-status.md` called PARTIAL, and why one of them was.

**Response size** was easy and simply absent: every request already read a
body and nothing counted it, so a performance report could tell you an
operation answered in 12 ms and not that it answered with four megabytes.

**TLS timing breakdown** was harder, and the honest reason it stayed PARTIAL is
that the obvious version of it is a lie. `httpx` exposes no hook between
"resolve" and "handshake", and the load run pools connections on purpose -- so
for every request after the first, DNS and the handshake cost exactly nothing.
A per-request breakdown would be a number describing a service nobody runs.

So it is measured as what it is: one cold connection, timed phase by phase,
reported *beside* the percentiles with a sentence saying it is not inside them.
The tests here are mostly about that boundary being honest -- that `None` means
"not measured" rather than "zero", that a plain-HTTP target reports no
handshake instead of an instant one, and that an unreachable host produces a
probe with an error rather than an exception halfway through a load run.
"""

from __future__ import annotations

import pytest

from apiverity.mock import MockServer
from apiverity.performance.connection import ConnectionProbe, probe
from apiverity.performance.engine import evaluate_policies, measure, parse_policy
from apiverity.specs.loader import detect_and_load

pytestmark = pytest.mark.integration

_FIXTURE = "fixtures/apis/crud/openapi.yaml"


@pytest.fixture(scope="module")
def measured():
    service, _findings, _plugin = detect_and_load(_FIXTURE)
    with MockServer(service, port=8123) as mock:
        yield service, measure(service, mock.base_url, iterations=6)


# ------------------------------------------------------------ response size


def test_a_report_now_says_how_large_the_answers_were(measured) -> None:
    """A p95 of 12 ms and a response of four megabytes are both facts about
    the same call, and only one of them used to be in the report."""
    _service, report = measured
    answered = [op for op in report.operations if op.samples and not op.unreachable]
    assert answered
    assert any(op.bytes_max > 0 for op in answered)


def test_size_is_reported_as_percentiles_not_a_mean(measured) -> None:
    """The response that hurts is the largest one a client hit, and a mean
    hides it behind a hundred small ones."""
    _service, report = measured
    op = next(o for o in report.operations if o.bytes_max > 0)
    assert op.bytes_p50 <= op.bytes_p95 <= op.bytes_max
    assert op.bytes_total >= op.bytes_max


def test_bytes_per_second_is_derived_from_the_measured_window(measured) -> None:
    _service, report = measured
    op = next(o for o in report.operations if o.bytes_total > 0)
    assert op.bytes_per_second > 0


def test_an_operation_nothing_answered_reports_zero_bytes_and_says_why(measured) -> None:
    """Zero bytes because nothing replied and zero bytes because the reply was
    empty are different, and the outcome counters are what distinguish them.

    Which counter depends on the platform: a closed local port refuses on some
    and hangs until the timeout on others, so this asserts what both mean --
    nothing answered -- rather than picking one.
    """
    service, _report = measured
    dead = measure(service, "http://127.0.0.1:9", iterations=2, timeout=0.5)
    for op in dead.operations:
        assert op.bytes_total == 0
        assert op.unreachable + op.timeouts == op.samples


# ------------------------------------------------------- the payload budget


def test_a_size_budget_parses_with_the_units_a_person_would_type() -> None:
    assert parse_policy("GET /users bytes_p95 <= 256KB").value == 256_000
    assert parse_policy("GET /users bytes_max <= 4096B").value == 4096
    assert parse_policy("GET /users bytes_p50 <= 1MB").value == 1_000_000


def test_size_units_are_decimal_not_binary() -> None:
    """`256KB` in a budget somebody typed means 256,000. Reading it as 262,144
    would make the limit 2.4% looser than it was written."""
    assert parse_policy("GET /users bytes_p95 <= 1KB").value == 1000


def test_a_size_budget_can_fail_a_run(measured) -> None:
    """Without this the size metrics would be numbers nothing can gate on, and
    a measurement nothing acts on is a measurement nobody reads."""
    _service, report = measured
    op = next(o for o in report.operations if o.bytes_p95 > 0)
    violations = evaluate_policies(report, [f"{op.operation_key} bytes_p95 <= 1B"])
    assert violations
    assert "bytes_p95" in violations[0]


def test_a_generous_size_budget_passes(measured) -> None:
    _service, report = measured
    op = next(o for o in report.operations if o.bytes_p95 > 0)
    assert evaluate_policies(report, [f"{op.operation_key} bytes_p95 <= 10MB"]) == []


# ----------------------------------------------------- the connection probe


def test_the_report_carries_a_connection_probe(measured) -> None:
    _service, report = measured
    assert isinstance(report.connection, ConnectionProbe)
    assert report.connection.tcp_ms is not None


def test_the_probe_says_it_is_not_inside_the_percentiles(measured) -> None:
    """In the artifact, not only in a docstring. Somebody reading a p95 beside
    a 40 ms handshake will otherwise add them together."""
    _service, report = measured
    assert report.connection is not None
    assert "reuse a pooled connection" in report.connection.note


def test_a_plain_http_target_reports_no_handshake_rather_than_an_instant_one() -> None:
    """`None` means not measured. `0.0` would read as a TLS handshake that
    took no time, which is not a thing."""
    result = probe("http://127.0.0.1:9")
    assert result.scheme == "http"
    assert result.tls_ms is None
    assert result.tls_version is None


def test_a_dead_port_produces_a_probe_with_an_error_not_an_exception() -> None:
    """It runs immediately before a load run. Raising here would take down a
    measurement over a target that was merely down."""
    result = probe("http://127.0.0.1:9", timeout=0.5)
    assert result.error
    assert result.dns_ms is not None  # resolving localhost still worked
    assert result.tcp_ms is None


def test_a_url_with_no_host_is_refused_by_name() -> None:
    result = probe("not-a-url")
    assert result.error and "no host" in result.error


def test_the_default_port_follows_the_scheme() -> None:
    assert probe("https://127.0.0.1", timeout=0.2).port == 443
    assert probe("http://127.0.0.1", timeout=0.2).port == 80


def test_an_explicit_port_wins(measured) -> None:
    _service, report = measured
    assert report.connection is not None
    assert report.connection.port == 8123
