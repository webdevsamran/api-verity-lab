"""Workflow manifest and result models, and the variable syntax they use.

`VARIABLE_RE` and `placeholder` live here rather than in the engine because
three modules need to agree about them and one of them must not import httpx.

They did not agree. `engine._substitute` replaces `{name}`; `graph.py` looked
for `{{ name }}` and `templates.py` emitted `{{ name }}`. So the validator and
the four built-in templates shared a syntax the thing that executes them has
never implemented -- which nothing caught, because the validator was reachable
from no command and the templates were only ever compared against themselves.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

#: `{name}` -- what `WorkflowEngine` substitutes and therefore what a manifest
#: means by a variable. Anything else is a literal and is sent as written.
VARIABLE_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def placeholder(name: str) -> str:
    """The text a manifest writes to stand for `name`."""
    return "{" + name + "}"


def variables_in(text: object) -> set[str]:
    """Every variable a string refers to. Empty for anything that is not one."""
    return set(VARIABLE_RE.findall(text)) if isinstance(text, str) else set()


class WorkflowRequest(BaseModel):
    method: str = "GET"
    path: str
    body: Any | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    query: dict[str, Any] = Field(default_factory=dict)


class WorkflowStep(BaseModel):
    name: str
    request: WorkflowRequest
    extract: dict[str, str] = Field(default_factory=dict)  # var -> jsonpath-ish
    assert_status: list[int] | None = None
    assert_jsonpath: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: float = 30.0


class Workflow(BaseModel):
    name: str
    description: str | None = None
    base_url: str | None = None
    inputs: list[str] = Field(default_factory=list)  # variables supplied by the caller
    allowed_hosts: list[str] = Field(default_factory=list)
    allowed_methods: list[str] = Field(
        default_factory=lambda: ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"]
    )
    steps: list[WorkflowStep] = Field(default_factory=list)
    cleanup: list[WorkflowStep] = Field(default_factory=list)


class StepResult(BaseModel):
    step: str
    status: str  # pass | fail | error | skipped
    actual_status: int | None = None
    violations: list[str] = Field(default_factory=list)
    extracted: dict[str, Any] = Field(default_factory=dict)
    duration_ms: int = 0


class WorkflowResult(BaseModel):
    workflow: str
    status: str  # pass | fail | error
    steps: list[StepResult] = Field(default_factory=list)
    cleanup_steps: list[StepResult] = Field(default_factory=list)
    variables: dict[str, Any] = Field(default_factory=dict)
