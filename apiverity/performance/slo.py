"""Objectives the contract itself declares, and what one run can say about them.

Budgets already existed, as flags: `--policy "GET /users p95 <= 250ms"`. That
number lives in whoever's CI file typed it, which is not where the promise
lives. The promise is in the contract, the contract is the thing consumers
read, and a budget that disagrees with it is a budget nobody agreed to.

So an operation may declare its own:

    paths:
      /users:
        get:
          x-slo:
            p95_ms: 250
            error_rate_pct: 1
            bytes_p95: 262144

and `apiverity regression --slo` measures against that instead of against a
flag. `x-` because no OpenAPI version has a field for it; `Operation.extensions`
already carries every `x-*` key verbatim, for exactly this reason.

## The thing this must not be mistaken for

**An SLO is a promise over a window. A run is a sample.**

"99.9% of requests under 250 ms over 30 days" is not a claim any load run can
confirm or refute -- not this one, not a longer one. Twenty samples against a
mock say something about twenty samples against a mock.

Everything in this module is named accordingly. The finding is
`SLO-RUN-EXCEEDS-OBJECTIVE`, not `SLO-BREACHED`, and its message says *this
run* rather than *your service*. A tool that printed "SLO breached" off twenty
requests would be making the claim its own documentation says it cannot, and
the first person to check would stop believing the rest of the output.

`availability` is refused outright rather than approximated: a run measures
what it asked for and cannot see the requests it did not make, so an
availability number computed here would be a fabrication with a decimal point
on it.
"""

from __future__ import annotations

from typing import Any

from apiverity.core.model import Finding, Operation, Service, Severity

#: The extension key an operation declares its objectives under.
SLO_KEY = "x-slo"

#: Objective -> the `OperationStats` attribute it is measured against, and
#: which direction is bad. Every one of these is a *ceiling*: an objective
#: where lower is worse would need its own comparison, and none of the ones
#: below are that.
MEASURABLE: dict[str, str] = {
    "p50_ms": "p50_ms",
    "p90_ms": "p90_ms",
    "p95_ms": "p95_ms",
    "p99_ms": "p99_ms",
    "error_rate_pct": "error_rate_pct",
    "bytes_p50": "bytes_p50",
    "bytes_p95": "bytes_p95",
    "bytes_max": "bytes_max",
}

#: Declared, understood, and deliberately not measured -- with the reason,
#: because silence about an objective somebody wrote down reads as a pass.
NOT_MEASURABLE: dict[str, str] = {
    "availability": (
        "a run measures the requests it made and cannot see the ones it did not; an "
        "availability figure computed from one run would be a fabrication with a decimal "
        "point on it"
    ),
    "window": (
        "the period an objective is promised over. Recorded so the report can quote it, "
        "and no run is long enough to evaluate it"
    ),
    "uptime_pct": "the same as availability, under another name",
}


def declared(operation: Operation) -> dict[str, Any] | None:
    """The `x-slo` block on an operation, if it declared one."""
    value = operation.extensions.get(SLO_KEY)
    return value if isinstance(value, dict) else None


def operations_with_objectives(service: Service) -> list[Operation]:
    return [op for op in service.operations if declared(op)]


def validate(service: Service) -> list[Finding]:
    """Check the objectives themselves, before anything is measured.

    A malformed objective is worse than a missing one: `p95_ms: "250ms"` looks
    declared, reads as declared in a review, and is compared against nothing.
    """
    findings: list[Finding] = []
    declaring = operations_with_objectives(service)
    for op in declaring:
        block = declared(op) or {}
        for name, value in sorted(block.items()):
            if name in NOT_MEASURABLE:
                findings.append(
                    Finding(
                        rule_id="SLO-NOT-MEASURABLE",
                        severity=Severity.INFO,
                        message=(
                            f"operation '{op.key}' declares '{name}', which no run evaluates: "
                            f"{NOT_MEASURABLE[name]}"
                        ),
                        operation_key=op.key,
                        location=op.source_location,
                        hint=(
                            "Nothing to fix. It is carried into the report so a reader can "
                            "see the objective beside the measurement that does not test it."
                        ),
                    )
                )
                continue
            if name not in MEASURABLE:
                findings.append(
                    Finding(
                        rule_id="SLO-UNKNOWN-OBJECTIVE",
                        severity=Severity.WARN,
                        message=(
                            f"operation '{op.key}' declares objective '{name}', which this "
                            "tool does not measure"
                        ),
                        operation_key=op.key,
                        location=op.source_location,
                        hint=(
                            "Known objectives: "
                            + ", ".join(sorted(MEASURABLE))
                            + ". An objective nothing compares against is a promise nobody "
                            "checks."
                        ),
                    )
                )
                continue
            if not isinstance(value, int | float) or isinstance(value, bool):
                findings.append(
                    Finding(
                        rule_id="SLO-MALFORMED",
                        severity=Severity.WARN,
                        message=(
                            f"operation '{op.key}' declares {name}={value!r}, which is not a "
                            "number, so nothing can be compared against it"
                        ),
                        operation_key=op.key,
                        location=op.source_location,
                        hint="Write it as a bare number: `p95_ms: 250`, not `p95_ms: 250ms`.",
                    )
                )

    # An operation with no objective, in a contract where others have one --
    # the same shape as the 429 check, and reported for the same reason. A
    # contract that declares none anywhere is a choice, not an oversight, and
    # a finding per operation for it would be a wall.
    if declaring and len(declaring) != len(service.operations):
        named = ", ".join(sorted(op.key for op in declaring)[:3])
        for op in service.operations:
            if declared(op):
                continue
            findings.append(
                Finding(
                    rule_id="SLO-UNDECLARED",
                    severity=Severity.INFO,
                    message=(
                        f"operation '{op.key}' declares no objective, though "
                        f"{len(declaring)} operation(s) in this contract do ({named})"
                    ),
                    operation_key=op.key,
                    location=op.source_location,
                    hint=(
                        "Add an `x-slo` block, or leave it: an operation with no stated "
                        "objective is not a defect, it is an operation nobody promised "
                        "anything about."
                    ),
                )
            )
    return findings


def evaluate(service: Service, report: Any) -> list[Finding]:
    """Compare a measurement against the objectives the contract declared.

    `report` is a `PerformanceReport`; typed loosely to keep this module out of
    an import cycle with the engine, which imports nothing from here.
    """
    by_key = {stats.operation_key: stats for stats in report.operations}
    findings: list[Finding] = []
    for op in operations_with_objectives(service):
        block = declared(op) or {}
        stats = by_key.get(op.key)
        if stats is None:
            findings.append(
                Finding(
                    rule_id="SLO-NOT-MEASURED",
                    severity=Severity.WARN,
                    message=(
                        f"operation '{op.key}' declares an objective and this run measured "
                        "nothing for it"
                    ),
                    operation_key=op.key,
                    location=op.source_location,
                    hint=(
                        "A declared objective with no measurement beside it reads as a pass. "
                        "Check the operation is reachable at the target."
                    ),
                )
            )
            continue
        # Refused *or* timed out: a closed port refuses on some platforms and
        # hangs until the timeout on others, and both mean the same thing here.
        # Guarding on `unreachable` alone let a timing-out target through, and
        # its p95 -- the timeout duration -- was then reported as an exceeded
        # objective, blaming the service for being unreachable.
        silent = stats.unreachable + stats.timeouts
        if stats.samples and silent == stats.samples:
            findings.append(
                Finding(
                    rule_id="SLO-NOT-MEASURED",
                    severity=Severity.WARN,
                    message=(
                        f"operation '{op.key}' declares an objective and nothing answered: "
                        f"{silent} of {stats.samples} requests were refused or timed out"
                    ),
                    operation_key=op.key,
                    location=op.source_location,
                    hint=(
                        "A p95 of a connection timeout is not a latency. Reporting it against "
                        "an objective would blame the service for being unreachable."
                    ),
                )
            )
            continue
        for name, value in sorted(block.items()):
            if name not in MEASURABLE or not isinstance(value, int | float):
                continue
            if isinstance(value, bool):
                continue
            actual = float(getattr(stats, MEASURABLE[name], 0.0))
            if actual <= float(value):
                continue
            findings.append(
                Finding(
                    rule_id="SLO-RUN-EXCEEDS-OBJECTIVE",
                    severity=Severity.ERROR,
                    message=(
                        f"operation '{op.key}': this run measured {name}={actual:g} against a "
                        f"declared objective of {value:g}"
                    ),
                    operation_key=op.key,
                    location=op.source_location,
                    # The distinction the whole module exists to keep. An SLO is
                    # a promise over a window; this is one run of N samples, and
                    # saying "SLO breached" off it would be the claim this tool
                    # documents that it cannot make.
                    hint=(
                        f"This is one run of {stats.samples} sample(s), not a judgement about "
                        "the objective, which is a promise over a window no single run covers. "
                        "It is a reason to look."
                    ),
                    metadata={
                        "objective": name,
                        "declared": value,
                        "measured": actual,
                        "samples": stats.samples,
                    },
                )
            )
    return findings


__all__ = [
    "MEASURABLE",
    "NOT_MEASURABLE",
    "SLO_KEY",
    "declared",
    "evaluate",
    "operations_with_objectives",
    "validate",
]
