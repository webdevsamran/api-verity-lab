"""Model-based stateful testing for CRUD resources.

Defines a small transition model over a resource (create/read/update/delete)
and executes legal transitions against an authorized target, checking each
response against expectations. Deterministic; no random exploration.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from apiverity.stateful.models import StepResult, WorkflowResult


class ResourceState(StrEnum):
    ABSENT = "absent"
    EXISTS = "exists"
    UPDATED = "updated"


@dataclass(frozen=True)
class Transition:
    name: str
    method: str
    from_state: ResourceState
    to_state: ResourceState
    expect_status: tuple[int, ...]


#: The canonical CRUD transition table.
CRUD_TRANSITIONS: tuple[Transition, ...] = (
    Transition("create", "POST", ResourceState.ABSENT, ResourceState.EXISTS, (200, 201)),
    Transition("read", "GET", ResourceState.EXISTS, ResourceState.EXISTS, (200,)),
    Transition("update", "PATCH", ResourceState.EXISTS, ResourceState.UPDATED, (200,)),
    Transition("read-after-update", "GET", ResourceState.UPDATED, ResourceState.UPDATED, (200,)),
    Transition("delete", "DELETE", ResourceState.UPDATED, ResourceState.ABSENT, (200, 202, 204)),
    Transition("read-deleted", "GET", ResourceState.ABSENT, ResourceState.ABSENT, (404, 410)),
)


class ModelBasedRunner:
    """Executes the CRUD transition model against a target.

    ``transport`` is a callable ``(method, path, body) -> (status, json_body)``
    so tests can run against httpx or an in-process mock deterministically.
    """

    def __init__(
        self,
        transport: Callable[[str, str, Any], tuple[int, Any]],
        *,
        collection_path: str = "/widgets",
        payload: dict[str, Any] | None = None,
        update_payload: dict[str, Any] | None = None,
    ) -> None:
        self.transport = transport
        self.collection_path = collection_path
        self.payload = payload or {"name": "model-based"}
        self.update_payload = update_payload or {"name": "model-based-v2"}
        self.resource_id: str | None = None

    def _path(self) -> str:
        return (
            f"{self.collection_path}/{self.resource_id}"
            if self.resource_id
            else self.collection_path
        )

    def run(self) -> WorkflowResult:
        results: list[StepResult] = []
        state = ResourceState.ABSENT
        status_overall = "pass"

        for t in CRUD_TRANSITIONS:
            if t.from_state != state:
                continue  # deterministic path only follows reachable transitions
            body = None
            if t.method == "POST":
                body = self.payload
            elif t.method == "PATCH":
                body = self.update_payload
            try:
                resp_status, resp_body = self.transport(t.method, self._path(), body)
            except Exception as exc:
                results.append(StepResult(step=t.name, status="error", violations=[str(exc)]))
                status_overall = "error"
                break
            violations: list[str] = []
            if resp_status not in t.expect_status:
                violations.append(
                    f"expected status in {list(t.expect_status)} but got {resp_status}"
                )
            if t.name == "create" and isinstance(resp_body, dict):
                rid = resp_body.get("id")
                if rid is None:
                    violations.append("created resource has no 'id' field to address it by")
                else:
                    self.resource_id = str(rid)
            if t.name == "read-after-update" and isinstance(resp_body, dict):
                for k, v in self.update_payload.items():
                    if resp_body.get(k) != v:
                        violations.append(f"update not persisted: '{k}' is {resp_body.get(k)!r}")
            results.append(
                StepResult(
                    step=t.name,
                    status="fail" if violations else "pass",
                    actual_status=resp_status,
                    violations=violations,
                    extracted=dict(resp_body) if isinstance(resp_body, dict) else {},
                )
            )
            if violations:
                status_overall = "fail"
                break
            state = t.to_state

        return WorkflowResult(workflow="model-based-crud", status=status_overall, steps=results)
