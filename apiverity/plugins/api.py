"""Versioned plugin API contracts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from apiverity.core.model import Finding, Operation, SchemaNode, Service


class RulePlugin(ABC):
    """A breaking-change rule evaluated against a pair of operations."""

    rule_id: str = ""
    severity: str = "ERROR"
    description: str = ""

    @abstractmethod
    def check(self, old: Operation | None, new: Operation | None) -> list[Finding]:
        """Return findings for a changed operation pair."""


class CheckPlugin(ABC):
    """A static contract check run against a single normalized contract."""

    check_id: str = ""

    @abstractmethod
    def check(self, service: Service) -> list[Finding]:
        """Return findings for the contract."""


class GeneratorPlugin(ABC):
    """Produces test cases from schemas."""

    generator_id: str = ""

    @abstractmethod
    def generate(self, schema: SchemaNode, seed: int) -> list[dict[str, Any]]:
        """Generate candidate values for a schema node."""


class ExporterPlugin(ABC):
    """Serializes a result artifact to a target format."""

    exporter_id: str = ""

    @abstractmethod
    def export(self, artifact: Any) -> str:
        """Render the artifact to a string in the target format."""