"""Stateful workflow engine.

Workflows are **authored explicitly** in YAML manifests (steps, variable
extraction, assertions, cleanup, timeouts, allowed hosts/methods). The
engine never generates destructive sequences automatically and refuses
hosts that are not in the manifest's allowlist.

A manifest can also be read from and written as an `Arazzo
<https://spec.openapis.org/arazzo/latest.html>`_ 1.1.0 description. Arazzo
describes a graph and this engine runs a straight line, so the conversion is
lossy in one direction and everything it cannot carry is reported rather than
dropped -- see `apiverity.stateful.arazzo`.
"""

from apiverity.stateful.arazzo import (
    ArazzoExport,
    ArazzoImport,
    Untranslated,
    from_arazzo,
    is_arazzo,
    read_arazzo,
    to_arazzo,
)
from apiverity.stateful.engine import WorkflowEngine, load_workflow_manifest
from apiverity.stateful.models import (
    StepResult,
    Workflow,
    WorkflowResult,
    WorkflowStep,
)

__all__ = [
    "ArazzoExport",
    "ArazzoImport",
    "StepResult",
    "Untranslated",
    "Workflow",
    "WorkflowEngine",
    "WorkflowResult",
    "WorkflowStep",
    "from_arazzo",
    "is_arazzo",
    "load_workflow_manifest",
    "read_arazzo",
    "to_arazzo",
]
