"""OpenAPI spec plugin."""

from __future__ import annotations

from apiverity.core.model import Protocol, Service, Finding
from apiverity.specs import SpecPlugin
from apiverity.specs.openapi.parser import load_openapi


class OpenApiSpecPlugin(SpecPlugin):
    """Normalizes OpenAPI 3.0/3.1 documents into the core model."""

    def protocol(self) -> Protocol:
        return Protocol.OPENAPI

    def detect(self, source: str, raw: bytes | None = None) -> bool:
        if raw is None:
            try:
                from apiverity.specs import read_source

                _, raw = read_source(source)
            except Exception:
                return False
        text = raw.decode("utf-8-sig", errors="replace")
        return '"openapi"' in text or "openapi:" in text

    def load(self, source: str) -> tuple[Service, list[Finding]]:
        return load_openapi(source)