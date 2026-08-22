"""Typed SDK surface for api-verity-lab.

Stable public exports; the plugin API contract version is
``apiverity.plugins.registry.PLUGIN_API_VERSION``.
"""
from __future__ import annotations

from apiverity.core.artifact import ArtifactMeta  # noqa: F401
from apiverity.core.model import (  # noqa: F401
    Contract,
    Finding,
    Operation,
    SchemaNode,
    Service,
    Severity,
    SourceLocation,
)
from apiverity.diff.engine import Change, diff_services  # noqa: F401
from apiverity.fuzz.models import TestCase, TestResult  # noqa: F401
from apiverity.performance.engine import (  # noqa: F401
    OperationStats,
    PerformanceReport,
    Policy,
)

# Spec-canonical names (§24): a PerformanceBudget is a parsed policy;
# RunReport is the versioned artifact envelope.
PerformanceBudget = Policy  # noqa: F401
RunReport = ArtifactMeta  # noqa: F401
from apiverity.plugins.registry import PLUGIN_API_VERSION  # noqa: F401
from apiverity.rules.breaking import CATALOG, RuleSpec, evaluate_breaking  # noqa: F401
from apiverity.rules.semver import SemverPolicy  # noqa: F401
from apiverity.runtime.drift import DriftFinding, DriftReport  # noqa: F401
from apiverity.stateful.models import (  # noqa: F401
    StepResult,
    Workflow,
    WorkflowResult,
    WorkflowStep,
)

__all__ = [
    "Contract", "Service", "Operation", "SchemaNode", "SourceLocation",
    "Severity", "Finding", "Change", "RuleSpec", "CATALOG",
    "evaluate_breaking", "SemverPolicy", "diff_services",
    "TestCase", "TestResult", "Workflow", "WorkflowStep", "WorkflowResult",
    "StepResult", "DriftFinding", "DriftReport", "Policy", "OperationStats",
    "PerformanceReport", "PerformanceBudget", "RunReport",
    "PLUGIN_API_VERSION",
]
