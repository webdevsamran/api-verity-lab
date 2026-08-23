"""Workflow graph validation (stateful engine v2).

Validates a workflow manifest as a graph before execution:
- variable dependency ordering (a step may only use variables extracted earlier);
- destructive operations must have matching cleanup;
- cleanup completeness for created resources;
- duplicate step names.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from apiverity.core.model import Finding, Severity
from apiverity.stateful.models import Workflow

_VAR_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
_DESTRUCTIVE = {"POST", "PUT", "PATCH", "DELETE"}


@dataclass(frozen=True)
class GraphIssue:
    rule_id: str
    severity: Severity
    message: str

    def to_finding(self) -> Finding:
        return Finding(rule_id=self.rule_id, severity=self.severity, message=self.message)


@dataclass
class GraphValidation:
    issues: list[GraphIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(i.severity == Severity.ERROR for i in self.issues)

    def findings(self) -> list[Finding]:
        return [i.to_finding() for i in self.issues]


def _vars_in(text: object) -> set[str]:
    if isinstance(text, str):
        return set(_VAR_RE.findall(text))
    return set()


def _deep_vars(value: object) -> set[str]:
    out: set[str] = set()
    if isinstance(value, dict):
        for k, v in value.items():
            out |= _vars_in(k) | _deep_vars(v)
    elif isinstance(value, list):
        for v in value:
            out |= _deep_vars(v)
    else:
        out |= _vars_in(value)
    return out


def validate_workflow_graph(workflow: Workflow) -> GraphValidation:
    result = GraphValidation()
    available: set[str] = set(workflow.inputs)
    names: set[str] = set()
    created_ids: dict[str, str] = {}  # resource var -> creating step name

    for step in workflow.steps:
        if step.name in names:
            result.issues.append(
                GraphIssue("WF-DUP-STEP", Severity.ERROR, f"duplicate step name '{step.name}'")
            )
        names.add(step.name)

        used = _deep_vars(step.request.model_dump())
        missing = used - available
        if missing:
            result.issues.append(
                GraphIssue(
                    "WF-MISSING-VAR",
                    Severity.ERROR,
                    f"step '{step.name}' uses undefined variables: {sorted(missing)}",
                )
            )
        # destructive steps should record what they create for cleanup checks
        if step.request.method.upper() in _DESTRUCTIVE and step.extract:
            for var in step.extract:
                created_ids[var] = step.name
        available |= set(step.extract.keys())

    # cleanup coverage: every extracted id-like variable used in a DELETE path
    delete_paths = " ".join(
        s.request.path for s in workflow.cleanup if s.request.method.upper() == "DELETE"
    )
    delete_vars = _vars_in(delete_paths)
    for var, creator in sorted(created_ids.items()):
        if var not in delete_vars:
            result.issues.append(
                GraphIssue(
                    "WF-INCOMPLETE-CLEANUP",
                    Severity.WARN,
                    f"resource '{var}' created by '{creator}' is never deleted in cleanup",
                )
            )
    unused_cleanup = delete_vars - set(created_ids)
    if unused_cleanup:
        result.issues.append(
            GraphIssue(
                "WF-CLEANUP-UNKNOWN-VAR",
                Severity.ERROR,
                f"cleanup deletes undefined variables: {sorted(unused_cleanup)}",
            )
        )
    return result


def has_cycle(steps: list[str], edges: dict[str, list[str]]) -> bool:
    """Detect cycles in a step-dependency graph (DFS with colors)."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color = dict.fromkeys(steps, WHITE)

    def visit(node: str) -> bool:
        if color.get(node, BLACK) == GRAY:
            return True
        if color.get(node, BLACK) == BLACK:
            return False
        color[node] = GRAY
        for nxt in edges.get(node, []):
            if visit(nxt):
                return True
        color[node] = BLACK
        return False

    return any(visit(n) for n in steps if color[n] == WHITE)
