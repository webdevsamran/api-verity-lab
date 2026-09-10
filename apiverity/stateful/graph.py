"""Workflow graph validation, run before anything is sent.

Checks a manifest as a graph:

- variable dependency ordering -- a step may only use variables an earlier step
  extracted, or an input the caller supplied;
- destructive steps record what they created, and cleanup deletes it;
- cleanup does not name variables nothing produces;
- duplicate step names.

## It was looking for a syntax nothing writes

This module matched `{{ name }}`. `WorkflowEngine` substitutes `{name}`. So
against any real manifest `_deep_vars` found nothing at all, and the
consequences ran in both directions: `WF-MISSING-VAR` could not fire, and
`WF-INCOMPLETE-CLEANUP` fired on every created resource -- including the
bundled `crud-lifecycle.yaml`, whose cleanup deletes exactly the resource it
was being warned about.

The tests passed because they were written in `{{ }}` too, and so were the four
built-in templates in `templates.py`. Three modules agreed with each other and
disagreed with the one that executes anything. Nothing caught it because this
validator was reachable from no command.

`VARIABLE_RE` now comes from `stateful.models`, which is also where
`engine._substitute` gets `placeholder`, so the two cannot drift again.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from apiverity.core.model import Finding, Severity
from apiverity.stateful.models import Workflow, variables_in

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


def _deep_vars(value: object) -> set[str]:
    out: set[str] = set()
    if isinstance(value, dict):
        for k, v in value.items():
            out |= variables_in(k) | _deep_vars(v)
    elif isinstance(value, list):
        for v in value:
            out |= _deep_vars(v)
    else:
        out |= variables_in(value)
    return out


def validate_workflow_graph(workflow: Workflow) -> GraphValidation:
    result = GraphValidation()
    available: set[str] = set(workflow.inputs)
    names: set[str] = set()
    extracted_by: dict[str, str] = {}  # var -> the destructive step that made it
    # Every variable any step or cleanup step puts in a *path*. That is what
    # distinguishes a resource handle from a value: `{order_id}` addresses
    # something at `/orders/{order_id}`, and an `access_token` that only ever
    # appears in a header addresses nothing and has nothing to delete. The
    # cleanup rule warned about tokens until this told the two apart.
    addressed: set[str] = set()
    for step in [*workflow.steps, *workflow.cleanup]:
        addressed |= variables_in(step.request.path)

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
                extracted_by[var] = step.name
        available |= set(step.extract.keys())

    # cleanup coverage: every extracted id-like variable used in a DELETE path
    delete_paths = " ".join(
        s.request.path for s in workflow.cleanup if s.request.method.upper() == "DELETE"
    )
    delete_vars = variables_in(delete_paths)
    created_ids = {v: step for v, step in extracted_by.items() if v in addressed}
    for var, creator in sorted(created_ids.items()):
        if var not in delete_vars:
            result.issues.append(
                GraphIssue(
                    "WF-INCOMPLETE-CLEANUP",
                    Severity.WARN,
                    f"resource '{var}' created by '{creator}' is never deleted in cleanup",
                )
            )
    # Against everything extracted, not only the addressed subset: a cleanup
    # that deletes `{access_token}` is still deleting something nothing
    # produced as a path handle, and that is the error this reports.
    unused_cleanup = delete_vars - set(extracted_by) - set(workflow.inputs)
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
