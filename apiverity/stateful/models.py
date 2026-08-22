"""Workflow manifest and result models."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class WorkflowRequest(BaseModel):
    method: str = "GET"
    path: str
    body: Optional[Any] = None
    headers: dict[str, str] = Field(default_factory=dict)
    query: dict[str, Any] = Field(default_factory=dict)


class WorkflowStep(BaseModel):
    name: str
    request: WorkflowRequest
    extract: dict[str, str] = Field(default_factory=dict)  # var -> jsonpath-ish
    assert_status: Optional[list[int]] = None
    assert_jsonpath: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: float = 30.0


class Workflow(BaseModel):
    name: str
    description: Optional[str] = None
    base_url: Optional[str] = None
    allowed_hosts: list[str] = Field(default_factory=list)
    allowed_methods: list[str] = Field(
        default_factory=lambda: ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"]
    )
    steps: list[WorkflowStep] = Field(default_factory=list)
    cleanup: list[WorkflowStep] = Field(default_factory=list)


class StepResult(BaseModel):
    step: str
    status: str  # pass | fail | error | skipped
    actual_status: Optional[int] = None
    violations: list[str] = Field(default_factory=list)
    extracted: dict[str, Any] = Field(default_factory=dict)
    duration_ms: int = 0


class WorkflowResult(BaseModel):
    workflow: str
    status: str  # pass | fail | error
    steps: list[StepResult] = Field(default_factory=list)
    cleanup_steps: list[StepResult] = Field(default_factory=list)
    variables: dict[str, Any] = Field(default_factory=dict)