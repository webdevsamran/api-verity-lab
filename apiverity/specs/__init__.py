"""Spec plugins: adapters that normalize wire formats into the core model."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from apiverity.core.model import Finding, Protocol, Service


class SpecPlugin(ABC):
    """Base class for spec adapters.

    Plugin contract version 1: implement :meth:`protocol`, :meth:`detect`
    and :meth:`load`. ``load`` returns ``(Service, list[Finding])`` where
    findings include validation problems (unresolved refs, duplicates, ...).
    """

    PLUGIN_API_VERSION = "1"

    @abstractmethod
    def protocol(self) -> Protocol:
        """Which protocol this plugin handles."""

    @abstractmethod
    def detect(self, source: str, raw: bytes | None = None) -> bool:
        """Return True if this plugin can handle the given source."""

    @abstractmethod
    def load(self, source: str) -> tuple[Service, list[Finding]]:
        """Load and normalize a contract from a file path or URL."""


def read_source(source: str) -> tuple[str, bytes]:
    """Read a spec from a local path or an HTTP(S) URL."""
    if source.startswith(("http://", "https://")):
        import httpx

        response = httpx.get(source, timeout=30.0, follow_redirects=True)
        response.raise_for_status()
        return source, response.content
    path = Path(source)
    return str(path), path.read_bytes()


def parse_document(raw: bytes) -> dict[str, Any]:
    """Parse JSON or YAML bytes into a dict."""
    import json

    text = raw.decode("utf-8-sig")
    try:
        doc = json.loads(text)
    except ValueError:
        import yaml

        doc = yaml.safe_load(text)
    if not isinstance(doc, dict):
        raise ValueError("spec document must be a mapping at the top level")
    return doc