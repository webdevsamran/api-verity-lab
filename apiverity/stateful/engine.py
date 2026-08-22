"""Workflow execution engine.

Safety model:
- requests are only sent to hosts listed in ``allowed_hosts`` (or the
  manifest's ``base_url`` host, which must itself be allowlisted);
- methods are restricted to ``allowed_methods``;
- destructive sequences exist only because a human authored them.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import yaml

from apiverity.stateful.models import (
    StepResult,
    Workflow,
    WorkflowResult,
    WorkflowStep,
)

_JSONPATH_RE = re.compile(r"^\$\.([A-Za-z_][\w.]*)(?:\[(\d+)\])?$")


def load_workflow_manifest(path: str) -> Workflow:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("workflow manifest must be a mapping")
    steps = []
    for s in raw.get("steps") or []:
        req = s.get("request") or {}
        assert_status = req.get("assert", {}).get("status") if isinstance(req.get("assert"), dict) else None
        # assertions may live on the step or inside request.assert
        step_assert = s.get("assert") or (req.get("assert") or {})
        status_list = step_assert.get("status") if isinstance(step_assert, dict) else None
        if isinstance(status_list, int):
            status_list = [status_list]
        jsonpath_asserts = {}
        if isinstance(step_assert, dict):
            jp = step_assert.get("jsonpath") or {}
            if isinstance(jp, dict):
                jsonpath_asserts = jp
        steps.append(
            WorkflowStep(
                name=str(s.get("name", f"step-{len(steps)}")),
                request={
                    "method": str(req.get("method", "GET")).upper(),
                    "path": str(req.get("path", "/")),
                    "body": req.get("body"),
                    "headers": req.get("headers") or {},
                    "query": req.get("query") or {},
                },
                extract=s.get("extract") or {},
                assert_status=status_list,
                assert_jsonpath=jsonpath_asserts,
                timeout_seconds=float(s.get("timeout", 30.0)),
            )
        )
    cleanup = []
    for s in raw.get("cleanup") or []:
        req = s.get("request") or {}
        cleanup.append(
            WorkflowStep(
                name=str(s.get("name", f"cleanup-{len(cleanup)}")),
                request={
                    "method": str(req.get("method", "GET")).upper(),
                    "path": str(req.get("path", "/")),
                    "body": req.get("body"),
                    "headers": req.get("headers") or {},
                    "query": req.get("query") or {},
                },
                timeout_seconds=float(s.get("timeout", 30.0)),
            )
        )
    return Workflow(
        name=str(raw.get("name", Path(path).stem)),
        description=raw.get("description"),
        base_url=raw.get("base_url"),
        allowed_hosts=[str(h) for h in raw.get("allowed_hosts") or []],
        allowed_methods=[str(m).upper() for m in raw.get("allowed_methods")
                         or ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"]],
        steps=steps,
        cleanup=cleanup,
    )


def _extract_jsonpath(data: Any, expression: str) -> tuple[bool, Any]:
    """Tiny JSONPath subset: ``$.a.b[0]``."""
    m = _JSONPATH_RE.match(expression.strip())
    if not m:
        return False, None
    current = data
    for part in m.group(1).split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return False, None
    if m.group(2) is not None:
        idx = int(m.group(2))
        if isinstance(current, list) and 0 <= idx < len(current):
            current = current[idx]
        else:
            return False, None
    return True, current


def _substitute(text: str, variables: dict[str, Any]) -> str:
    out = text
    for key, value in variables.items():
        out = out.replace("{" + key + "}", str(value))
    return out


def _deep_substitute(value: Any, variables: dict[str, Any]) -> Any:
    if isinstance(value, str):
        return _substitute(value, variables)
    if isinstance(value, dict):
        return {k: _deep_substitute(v, variables) for k, v in value.items()}
    if isinstance(value, list):
        return [_deep_substitute(v, variables) for v in value]
    return value


class WorkflowEngine:
    """Executes an authored workflow against an allowlisted base URL."""

    def __init__(self, workflow: Workflow, base_url: str) -> None:
        self.workflow = workflow
        self.base_url = base_url.rstrip("/")
        self._check_host(base_url)

    def _check_host(self, url: str) -> None:
        parsed = urlparse(url)
        host = f"{parsed.scheme}://{parsed.netloc}"
        # Allowlist entries may omit the port (e.g. "http://127.0.0.1").
        origin = f"{parsed.scheme}://{parsed.hostname}"
        allowed = {h.rstrip("/") for h in self.workflow.allowed_hosts}
        allowed_origins = {a.split("://")[0] + "://" +
                           urlparse(a if "://" in a else "http://" + a).hostname
                           for a in allowed}
        if allowed and host not in allowed and origin not in allowed_origins:
            raise ValueError(
                f"host '{host}' is not in the workflow allowlist "
                f"{sorted(allowed)}; refusing to send traffic"
            )

    def run(self) -> WorkflowResult:
        result = WorkflowResult(workflow=self.workflow.name, status="pass")
        variables: dict[str, Any] = {}

        for step in self.workflow.steps:
            step_result = self._run_step(step, variables)
            result.steps.append(step_result)
            variables.update(step_result.extracted)
            result.variables = dict(variables)
            if step_result.status != "pass":
                result.status = "fail" if step_result.status == "fail" else "error"
                break

        # cleanup always runs (best effort), even after failures
        cleanup_vars = dict(variables)
        for step in self.workflow.cleanup:
            step_result = self._run_step(step, cleanup_vars, strict=False)
            result.cleanup_steps.append(step_result)

        return result

    def _run_step(
        self, step: WorkflowStep, variables: dict[str, Any], *, strict: bool = True
    ) -> StepResult:
        request = step.request
        if request.method not in self.workflow.allowed_methods:
            return StepResult(
                step=step.name,
                status="fail",
                violations=[f"method {request.method} not in allowed_methods"],
            )

        path = _substitute(request.path, variables)
        body = _deep_substitute(request.body, variables)
        headers = {k: _substitute(str(v), variables) for k, v in request.headers.items()}
        query = _deep_substitute(request.query, variables)

        started = time.monotonic()
        try:
            with httpx.Client(timeout=step.timeout_seconds) as client:
                response = client.request(
                    request.method,
                    self.base_url + path,
                    params=query or None,
                    headers=headers or None,
                    json=body if body is not None else None,
                )
        except httpx.HTTPError as exc:
            return StepResult(
                step=step.name,
                status="error",
                violations=[f"request failed: {exc}"],
                duration_ms=int((time.monotonic() - started) * 1000),
            )
        duration_ms = int((time.monotonic() - started) * 1000)

        violations: list[str] = []
        expected_statuses = step.assert_status
        if expected_statuses is None:
            expected_statuses = [200, 201, 202, 204]
        if response.status_code not in expected_statuses:
            violations.append(
                f"status {response.status_code} not in expected {expected_statuses}"
            )

        extracted: dict[str, Any] = {}
        try:
            payload: Any = response.json() if response.content else None
        except ValueError:
            payload = None
            if step.extract:
                violations.append("response body is not JSON but extraction was requested")

        for var, expression in step.extract.items():
            ok, value = _extract_jsonpath(payload, expression)
            if ok:
                extracted[var] = value
            else:
                violations.append(f"could not extract '{var}' from {expression}")

        for expression, expected in step.assert_jsonpath.items():
            ok, actual = _extract_jsonpath(payload, expression)
            if not ok:
                violations.append(f"assertion path '{expression}' not found")
            elif actual != expected:
                violations.append(
                    f"assertion failed at '{expression}': "
                    f"expected {expected!r}, got {actual!r}"
                )

        status = "fail" if violations else "pass"
        if not strict:
            # cleanup failures never fail the workflow
            status = "pass" if status == "fail" else status
        return StepResult(
            step=step.name,
            status=status,
            actual_status=response.status_code,
            violations=violations,
            extracted=extracted,
            duration_ms=duration_ms,
        )


def run_workflow_manifest(path: str, base_url: str) -> WorkflowResult:
    wf = load_workflow_manifest(path)
    return WorkflowEngine(wf, base_url).run()