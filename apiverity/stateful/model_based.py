"""The CRUD invariants a contract implies and no schema states.

`apiverity test --model-based` is what reaches this. It answers questions a
schema check cannot ask, because they are about *sequences*:

- can a resource you just created be read back?
- does an update persist, or does the next read return the old value?
- is a deleted resource actually gone, or does it still answer 200?

Every one of those is a service that satisfies its contract on every individual
request and is broken.

## What it drives, and how it knows

`discover_collections` reads the contract: a collection is a path with a POST
and a sibling `{id}` path with a GET. Which verb updates -- `PATCH` or `PUT` --
comes from the contract too, and a collection declaring neither is exercised
without the update transitions rather than failed for not having them.

Deterministic, and one resource per collection. There is no random exploration
here: a model-based run that wandered would report a different set of findings
every time, and this is a gate.

## It writes

Create, update and delete, against whatever `--base-url` names. `test` gates it
behind `--include-mutations`, the same flag its generated mutation cases use.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from apiverity.core.model import Operation, Service
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


#: The canonical CRUD transition table. `update_verb` replaces PATCH when the
#: contract declares PUT instead.
CRUD_TRANSITIONS: tuple[Transition, ...] = (
    Transition("create", "POST", ResourceState.ABSENT, ResourceState.EXISTS, (200, 201)),
    Transition("read", "GET", ResourceState.EXISTS, ResourceState.EXISTS, (200,)),
    Transition("update", "PATCH", ResourceState.EXISTS, ResourceState.UPDATED, (200,)),
    Transition("read-after-update", "GET", ResourceState.UPDATED, ResourceState.UPDATED, (200,)),
    Transition("delete", "DELETE", ResourceState.UPDATED, ResourceState.ABSENT, (200, 202, 204)),
    Transition("read-deleted", "GET", ResourceState.ABSENT, ResourceState.ABSENT, (404, 410)),
)

#: When a collection declares no update verb, these two are dropped and
#: `delete` runs from EXISTS instead.
_UPDATE_STEPS = ("update", "read-after-update")


@dataclass
class Collection:
    """A CRUD resource the contract declares, ready to be driven."""

    #: `/widgets`
    path: str
    #: `/widgets/{id}`
    item_path: str
    #: `PATCH`, `PUT`, or None when the contract declares neither.
    update_verb: str | None = None
    #: Whether the contract declares a DELETE on the item path.
    deletable: bool = True
    #: The request schema a create takes, for a payload derived from the
    #: contract rather than guessed.
    create_operation: Operation | None = None
    update_operation: Operation | None = None
    #: Why a transition is not exercised, in the report rather than dropped.
    notes: list[str] = field(default_factory=list)

    def transitions(self) -> list[Transition]:
        steps = list(CRUD_TRANSITIONS)
        if self.update_verb is None:
            steps = [t for t in steps if t.name not in _UPDATE_STEPS]
            steps = [
                Transition(t.name, t.method, ResourceState.EXISTS, t.to_state, t.expect_status)
                if t.name == "delete"
                else t
                for t in steps
            ]
        else:
            steps = [
                Transition(t.name, self.update_verb, t.from_state, t.to_state, t.expect_status)
                if t.name == "update"
                else t
                for t in steps
            ]
        if not self.deletable:
            steps = [t for t in steps if t.name not in ("delete", "read-deleted")]
        return steps


def discover_collections(service: Service) -> list[Collection]:
    """Every CRUD resource the contract declares.

    A collection is a path with a POST and a sibling `{id}` path with a GET.
    Nothing is inferred from a name: `/widgets` is a collection because the
    contract says you can create one and read one back, not because it is
    plural.
    """
    by_key = {op.key: op for op in service.operations}
    item_paths: dict[str, str] = {}
    for op in service.operations:
        if op.method != "GET" or not op.path:
            continue
        head, _, tail = op.path.rpartition("/")
        if head and tail.startswith("{") and tail.endswith("}"):
            item_paths.setdefault(head, op.path)

    out: list[Collection] = []
    for collection_path, item_path in sorted(item_paths.items()):
        create = by_key.get(f"POST {collection_path}")
        if create is None:
            continue
        update_verb = next(
            (verb for verb in ("PATCH", "PUT") if f"{verb} {item_path}" in by_key), None
        )
        collection = Collection(
            path=collection_path,
            item_path=item_path,
            update_verb=update_verb,
            deletable=f"DELETE {item_path}" in by_key,
            create_operation=create,
            update_operation=by_key.get(f"{update_verb} {item_path}") if update_verb else None,
        )
        if update_verb is None:
            collection.notes.append(
                f"{item_path} declares neither PATCH nor PUT, so nothing checks that an "
                "update persists"
            )
        if not collection.deletable:
            collection.notes.append(
                f"{item_path} declares no DELETE, so nothing checks that a deleted resource is gone"
            )
        out.append(collection)
    return out


def payload_for(operation: Operation | None, seed: int = 0) -> dict[str, Any]:
    """A request body derived from the contract, not invented.

    A hardcoded `{"name": ...}` works against a fixture and against nothing
    else: a real create usually has required fields, and a 400 from one of them
    would be reported as a service that cannot create a resource.
    """
    import random

    from apiverity.fuzz.generate import generate_valid

    if operation is None or operation.request_body is None:
        return {}
    content = operation.request_body.content
    if not content:
        return {}
    schema = content[sorted(content)[0]]
    value = generate_valid(schema, random.Random(seed))
    return value if isinstance(value, dict) else {}


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
        transitions: tuple[Transition, ...] | list[Transition] | None = None,
        name: str = "model-based-crud",
    ) -> None:
        self.transport = transport
        self.collection_path = collection_path
        self.payload = payload or {"name": "model-based"}
        self.update_payload = update_payload or {"name": "model-based-v2"}
        self.transitions = tuple(transitions if transitions is not None else CRUD_TRANSITIONS)
        self.name = name
        self.resource_id: str | None = None

    @classmethod
    def for_collection(
        cls,
        transport: Callable[[str, str, Any], tuple[int, Any]],
        collection: Collection,
        *,
        seed: int = 0,
    ) -> ModelBasedRunner:
        """A runner for one discovered collection, with contract payloads."""
        created = payload_for(collection.create_operation, seed)
        updated = payload_for(collection.update_operation or collection.create_operation, seed + 1)
        return cls(
            transport,
            collection_path=collection.path,
            payload=created or {"name": "model-based"},
            update_payload=updated or {"name": "model-based-v2"},
            transitions=collection.transitions(),
            name=f"model-based {collection.path}",
        )

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

        for t in self.transitions:
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

        return WorkflowResult(workflow=self.name, status=status_overall, steps=results)
