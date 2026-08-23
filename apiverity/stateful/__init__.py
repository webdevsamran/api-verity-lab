"""Stateful workflow engine.

Workflows are **authored explicitly** in YAML manifests (steps, variable
extraction, assertions, cleanup, timeouts, allowed hosts/methods). The
engine never generates destructive sequences automatically and refuses
hosts that are not in the manifest's allowlist.
"""

from apiverity.stateful.engine import WorkflowEngine, load_workflow_manifest
from apiverity.stateful.models import (
    StepResult,
    Workflow,
    WorkflowResult,
    WorkflowStep,
)

__all__ = [
    "StepResult",
    "Workflow",
    "WorkflowEngine",
    "WorkflowResult",
    "WorkflowStep",
    "load_workflow_manifest",
]
