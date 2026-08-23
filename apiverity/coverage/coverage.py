"""Coverage computation over the normalized contract."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from apiverity.core.model import Service


class OperationCoverage(BaseModel):
    operation_key: str
    exercised: bool = False
    statuses_seen: list[int] = Field(default_factory=list)
    declared_statuses: list[str] = Field(default_factory=list)
    parameters_exercised: list[str] = Field(default_factory=list)
    parameters_declared: list[str] = Field(default_factory=list)
    body_constraints_exercised: int = 0
    body_constraints_declared: int = 0
    security_schemes: list[str] = Field(default_factory=list)


class CoverageReport(BaseModel):
    operations_total: int = 0
    operations_exercised: int = 0
    statuses_declared: int = 0
    statuses_covered: int = 0
    parameters_declared: int = 0
    parameters_covered: int = 0
    constraints_declared: int = 0
    constraints_covered: int = 0
    workflow_edges_declared: int = 0
    workflow_edges_covered: int = 0
    security_schemes_declared: list[str] = Field(default_factory=list)
    security_schemes_exercised: list[str] = Field(default_factory=list)
    operations: list[OperationCoverage] = Field(default_factory=list)

    def overall_percent(self) -> float:
        if self.operations_total == 0:
            return 100.0
        return round(100.0 * self.operations_exercised / self.operations_total, 1)


def _count_constraints(schema: Any) -> int:
    """Count leaf constraint checks implied by a schema tree."""
    from apiverity.core.model import SchemaNode

    if not isinstance(schema, SchemaNode):
        return 0
    count = 0
    if schema.enum is not None:
        count += 1
    for attr in (
        "minimum",
        "maximum",
        "exclusive_minimum",
        "exclusive_maximum",
        "multiple_of",
        "min_length",
        "max_length",
        "pattern",
        "min_items",
        "max_items",
        "unique_items",
    ):
        if getattr(schema, attr) is not None:
            count += 1
    for sub in schema.properties.values():
        count += _count_constraints(sub)
    if schema.items is not None:
        count += _count_constraints(schema.items)
    return count


def measure_coverage(
    service: Service,
    *,
    exercised_operations: set[str] | None = None,
    statuses_by_operation: dict[str, set[int]] | None = None,
    parameters_by_operation: dict[str, set[str]] | None = None,
    negative_cases_by_operation: dict[str, int] | None = None,
    workflow_edges: tuple[int, int] = (0, 0),
    security_schemes_exercised: set[str] | None = None,
) -> CoverageReport:
    """Build a coverage report.

    ``exercised_operations``: operation keys that received at least one request.
    ``statuses_by_operation``: actual status codes observed per operation key.
    ``parameters_by_operation``: parameter names actually sent per operation.
    ``negative_cases_by_operation``: count of constraint-violating cases run.
    """
    exercised = exercised_operations or set()
    statuses = statuses_by_operation or {}
    params = parameters_by_operation or {}
    negatives = negative_cases_by_operation or {}
    schemes_used = security_schemes_exercised or set()

    report = CoverageReport()
    report.workflow_edges_declared, report.workflow_edges_covered = workflow_edges

    for op in service.operations:
        oc = OperationCoverage(
            operation_key=op.key,
            exercised=op.key in exercised,
            declared_statuses=[r.status for r in op.responses],
            parameters_declared=[p.name for p in op.parameters],
            parameters_exercised=sorted(
                p.name for p in op.parameters if p.name in params.get(op.key, set())
            ),
            security_schemes=[
                r.scheme_name
                for r in (op.security if op.security is not None else service.global_security) or []
            ],
        )
        oc.statuses_seen = sorted(statuses.get(op.key, set()))
        oc.body_constraints_declared = sum(
            _count_constraints(s)
            for s in (op.request_body.content.values() if op.request_body else [])
        )
        # each executed negative case exercises roughly one constraint
        oc.body_constraints_exercised = min(negatives.get(op.key, 0), oc.body_constraints_declared)

        report.operations.append(oc)
        report.operations_total += 1
        report.operations_exercised += 1 if oc.exercised else 0
        report.statuses_declared += len(oc.declared_statuses)
        report.statuses_covered += len(set(oc.statuses_seen))
        report.parameters_declared += len(oc.parameters_declared)
        report.parameters_covered += len(oc.parameters_exercised)
        report.constraints_declared += oc.body_constraints_declared
        report.constraints_covered += oc.body_constraints_exercised

    report.security_schemes_declared = sorted(service.security_schemes)
    report.security_schemes_exercised = sorted(schemes_used & set(service.security_schemes))
    return report
