"""Test case and result models."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class TestCase(BaseModel):
    id: str
    operation_key: str
    kind: str  # positive | negative
    description: str
    method: str
    url_path: str
    query: dict[str, Any] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)
    body: Optional[Any] = None
    media: Optional[str] = None
    expected: str  # "2xx" for positive, "4xx" for negative


class TestResult(BaseModel):
    case_id: str
    operation_key: str
    kind: str
    description: str
    status: str  # pass | fail | error
    actual_status: Optional[int] = None
    violations: list[str] = Field(default_factory=list)
    reproduction: Optional[str] = None
    minimized: bool = False
    duration_ms: int = 0