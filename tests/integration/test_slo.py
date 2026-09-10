"""Objectives the contract declares, and the sentence that keeps them honest.

A budget in a CI file is a number whoever wrote the CI file typed. The promise
lives in the contract, which is the thing consumers read, and a budget that
disagrees with it is a budget nobody agreed to. `x-slo` moves it.

The load-bearing test in this file is not that a breach is detected. It is
that a breach is not *called* a breach.

An SLO is a promise over a window: "99.9% of requests under 250 ms over 30
days". Twenty samples against a mock cannot confirm or refute that, and a tool
that printed "SLO breached" off them would be making the claim its own
documentation says it cannot make. The rule is
`SLO-RUN-EXCEEDS-OBJECTIVE`, the message says *this run*, and the hint says how
many samples it was. `availability` is refused outright rather than
approximated -- a run cannot see the requests it did not make.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from apiverity.core.model import Finding, Operation, OperationKind, Protocol, Service
from apiverity.mock import MockServer
from apiverity.performance.engine import OperationStats, PerformanceReport, measure
from apiverity.performance.slo import (
    MEASURABLE,
    NOT_MEASURABLE,
    SLO_KEY,
    declared,
    evaluate,
    operations_with_objectives,
    validate,
)
from apiverity.specs.loader import detect_and_load

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[2]
_FIXTURE = _ROOT / "fixtures" / "apis" / "slo" / "openapi.yaml"


@pytest.fixture(scope="module")
def service() -> Service:
    loaded, _findings, _plugin = detect_and_load(str(_FIXTURE))
    return loaded


def _ids(findings: list[Finding]) -> list[str]:
    return [f.rule_id for f in findings]


def _op(key: str, slo: object) -> Operation:
    method, path = key.split(" ", 1)
    return Operation(kind=OperationKind.HTTP, method=method, path=path, extensions={SLO_KEY: slo})


# -------------------------------------------------------------- reading them


def test_an_objective_block_is_read_off_the_contract(service: Service) -> None:
    op = service.find_operation("GET /users")
    assert op is not None
    assert (declared(op) or {})["p95_ms"] == 250


def test_an_operation_without_one_declares_nothing(service: Service) -> None:
    op = service.find_operation("GET /health")
    assert op is not None
    assert declared(op) is None


def test_a_non_object_x_slo_is_not_an_objective_block() -> None:
    """`x-slo: "fast"` is somebody's note, not a declaration. Reading it as one
    would produce findings about a promise nobody made."""
    assert declared(_op("GET /a", "fast")) is None
    assert (
        operations_with_objectives(
            Service(
                title="t",
                version="1",
                protocol=Protocol.OPENAPI,
                operations=[_op("GET /a", "fast")],
            )
        )
        == []
    )


# ---------------------------------------------------------- checking them


def test_a_number_with_a_unit_stuck_on_it_is_reported(service: Service) -> None:
    """`p95_ms: "250ms"` looks declared, reads as declared in a review, and is
    compared against nothing. That is worse than a missing objective."""
    findings = [f for f in validate(service) if f.rule_id == "SLO-MALFORMED"]
    assert [f.operation_key for f in findings] == ["GET /users/{id}"]
    assert "250ms" in findings[0].message


def test_an_objective_this_tool_never_heard_of_is_reported(service: Service) -> None:
    """An objective nothing compares against is a promise nobody checks."""
    findings = [f for f in validate(service) if f.rule_id == "SLO-UNKNOWN-OBJECTIVE"]
    assert findings
    assert "time_to_first_byte_ms" in findings[0].message
    assert "p95_ms" in (findings[0].hint or "")


def test_availability_is_named_as_not_measured_rather_than_ignored(service: Service) -> None:
    """Silence about an objective somebody wrote down reads as a pass."""
    findings = [f for f in validate(service) if f.rule_id == "SLO-NOT-MEASURABLE"]
    names = {f.message.split("declares '")[1].split("'")[0] for f in findings}
    assert "availability" in names
    assert "window" in names


def test_the_reason_availability_is_not_measured_is_given(service: Service) -> None:
    finding = next(
        f
        for f in validate(service)
        if f.rule_id == "SLO-NOT-MEASURABLE" and "availability" in f.message
    )
    assert "cannot see the ones it did not" in finding.message


def test_not_measured_is_informational_and_asks_for_nothing(service: Service) -> None:
    finding = next(f for f in validate(service) if f.rule_id == "SLO-NOT-MEASURABLE")
    assert finding.severity.value == "INFO"
    assert (finding.hint or "").lower().startswith("nothing")


def test_an_operation_with_no_objective_is_noted_only_beside_ones_that_have(
    service: Service,
) -> None:
    """The same noise discipline as the 429 check: a contract that declares
    none anywhere is a choice, not an oversight."""
    findings = [f for f in validate(service) if f.rule_id == "SLO-UNDECLARED"]
    assert [f.operation_key for f in findings] == ["GET /health"]

    bare = Service(
        title="t",
        version="1",
        protocol=Protocol.OPENAPI,
        operations=[Operation(kind=OperationKind.HTTP, method="GET", path="/a")],
    )
    assert validate(bare) == []


def test_an_undeclared_objective_is_not_a_defect(service: Service) -> None:
    finding = next(f for f in validate(service) if f.rule_id == "SLO-UNDECLARED")
    assert finding.severity.value == "INFO"
    assert "not a defect" in (finding.hint or "")


def test_every_measurable_objective_names_a_real_statistic() -> None:
    """A mapping onto an attribute `OperationStats` does not have would
    compare every measurement against zero and report a breach every time."""
    from apiverity.performance.engine import OperationStats

    stats = OperationStats(operation_key="GET /a")
    for objective, attribute in MEASURABLE.items():
        assert hasattr(stats, attribute), f"{objective} maps onto a missing {attribute}"


def test_nothing_is_both_measurable_and_not() -> None:
    assert not (set(MEASURABLE) & set(NOT_MEASURABLE))


# ------------------------------------------------------------- measuring


def _report(p95_by_key: dict[str, float]) -> PerformanceReport:
    """A measurement with the p95 values a test wants to reason about.

    Everything else is left at zero, so a rule that read some other metric
    would fail rather than pass by coincidence.
    """
    return PerformanceReport(
        target="http://127.0.0.1:0",
        operations=[
            OperationStats(operation_key=key, samples=20, p95_ms=p95)
            for key, p95 in p95_by_key.items()
        ],
    )


@pytest.fixture(scope="module")
def measured(service: Service):
    with MockServer(service, port=8134) as mock:
        # Warmed, and more than five samples. `GET /users` declares 250 ms and
        # is the *met* case this file needs it to be -- but the first request
        # to a fresh server pays connection setup and the handler's first
        # import, and with five unwarmed samples that one is the p95. On a
        # loaded runner it crossed 250 ms and the met case became the exceeded
        # one, so the fixture stopped exercising the case it exists for.
        #
        # This is the same reasoning `performance/curve.py` gives for warming
        # at every concurrency level: setup charged to the first few requests
        # reads as the service being slow.
        yield measure(service, mock.base_url, iterations=12, warmup=3)


def test_an_exceeded_objective_is_reported(service: Service, measured) -> None:
    """`POST /reports` declares `p95_ms: 0`, which nothing can meet."""
    findings = [f for f in evaluate(service, measured) if f.rule_id == "SLO-RUN-EXCEEDS-OBJECTIVE"]
    assert any(f.operation_key == "POST /reports" for f in findings)


def test_the_finding_says_this_run_not_your_service(service: Service, measured) -> None:
    """The whole point. An SLO is a promise over a window; this is N samples.
    "SLO breached" off twenty requests is a claim this tool documents that it
    cannot make, and the first person to check would stop believing the rest
    of the output."""
    finding = next(
        f for f in evaluate(service, measured) if f.rule_id == "SLO-RUN-EXCEEDS-OBJECTIVE"
    )
    assert "this run measured" in finding.message
    assert "not a judgement about the objective" in (finding.hint or "")
    assert "promise over a window" in (finding.hint or "")


def test_the_finding_carries_the_numbers_it_compared(service: Service, measured) -> None:
    finding = next(
        f for f in evaluate(service, measured) if f.rule_id == "SLO-RUN-EXCEEDS-OBJECTIVE"
    )
    assert finding.metadata["objective"]
    assert finding.metadata["declared"] is not None
    assert finding.metadata["samples"] > 0


def test_a_met_objective_produces_nothing(service: Service) -> None:
    """`GET /users` declares 250 ms; a run that measured 40 ms says nothing.

    Measured values are constructed rather than timed. This assertion used a
    live mock and `p95_ms: 250`, which made it a stopwatch: on a loaded runner
    the p95 of a handful of local requests crosses 250 ms, the met case becomes
    the exceeded case, and the test fails for a reason that has nothing to do
    with the code it covers. The other tests in this file still measure a real
    server, because what they check needs one.
    """
    findings = evaluate(service, _report({"GET /users": 40.0}))
    keys = [f.operation_key for f in findings if f.rule_id == "SLO-RUN-EXCEEDS-OBJECTIVE"]
    assert "GET /users" not in keys


def test_the_same_objective_missed_by_the_same_run_is_reported(service: Service) -> None:
    """The control. Without it the test above passes against an `evaluate`
    that never reports anything at all."""
    findings = evaluate(service, _report({"GET /users": 400.0}))
    keys = [f.operation_key for f in findings if f.rule_id == "SLO-RUN-EXCEEDS-OBJECTIVE"]
    assert "GET /users" in keys


def test_a_malformed_objective_is_not_compared_against(service: Service, measured) -> None:
    """It was already reported by `validate`. Comparing a float against a
    string here would raise in the middle of a measurement."""
    keys = [
        f.operation_key
        for f in evaluate(service, measured)
        if f.rule_id == "SLO-RUN-EXCEEDS-OBJECTIVE"
    ]
    assert "GET /users/{id}" not in keys


def test_an_operation_nothing_answered_for_is_not_reported_as_exceeding(
    service: Service,
) -> None:
    """A p95 of a connection timeout is not a latency, and reporting it as an
    exceeded objective would blame the service for being unreachable."""
    dead = measure(service, "http://127.0.0.1:9", iterations=2, timeout=0.5)
    findings = evaluate(service, dead)
    assert "SLO-RUN-EXCEEDS-OBJECTIVE" not in _ids(findings)
    assert "SLO-NOT-MEASURED" in _ids(findings)


def test_an_objective_with_no_measurement_at_all_is_reported(service: Service) -> None:
    """A declared objective with no measurement beside it reads as a pass."""

    class _Empty:
        def __init__(self) -> None:
            self.operations: list[object] = []

    findings = evaluate(service, _Empty())
    assert set(_ids(findings)) == {"SLO-NOT-MEASURED"}
    assert "reads as a pass" in (findings[0].hint or "")
