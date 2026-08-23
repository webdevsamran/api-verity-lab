"""Typed SDK surface for api-verity-lab.

Stable public exports; the plugin API contract version is
``apiverity.plugins.registry.PLUGIN_API_VERSION``.
"""

from __future__ import annotations

from apiverity.core.artifact import ArtifactMeta
from apiverity.core.model import (
    Contract,
    Finding,
    Operation,
    SchemaNode,
    Service,
    Severity,
    SourceLocation,
)
from apiverity.diff.engine import Change, diff_services
from apiverity.fuzz.models import TestCase, TestResult
from apiverity.performance.engine import (
    OperationStats,
    PerformanceReport,
    Policy,
)
from apiverity.plugins.registry import PLUGIN_API_VERSION
from apiverity.rules.breaking import CATALOG, RuleSpec, evaluate_breaking
from apiverity.rules.semver import SemverPolicy
from apiverity.runtime.drift import DriftFinding, DriftReport
from apiverity.stateful.models import (
    StepResult,
    Workflow,
    WorkflowResult,
    WorkflowStep,
)

# Spec-canonical names (§24): a PerformanceBudget is a parsed policy;
# RunReport is the versioned artifact envelope.
PerformanceBudget = Policy
RunReport = ArtifactMeta

__all__ = [
    "CATALOG",
    "PLUGIN_API_VERSION",
    "Change",
    "Contract",
    "DriftFinding",
    "DriftReport",
    "Finding",
    "Operation",
    "OperationStats",
    "PerformanceBudget",
    "PerformanceReport",
    "Policy",
    "RuleSpec",
    "RunReport",
    "SchemaNode",
    "SemverPolicy",
    "Service",
    "Severity",
    "SourceLocation",
    "StepResult",
    "TestCase",
    "TestResult",
    "Workflow",
    "WorkflowResult",
    "WorkflowStep",
    "diff_services",
    "evaluate_breaking",
]
