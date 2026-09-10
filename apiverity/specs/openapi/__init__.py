"""OpenAPI spec plugin."""

from __future__ import annotations

from apiverity.core.model import Finding, Protocol, Service
from apiverity.specs import SpecPlugin
from apiverity.specs.openapi.parser import load_openapi


class OpenApiSpecPlugin(SpecPlugin):
    """Normalizes OpenAPI 3.0/3.1/3.2 documents into the core model."""

    def __init__(self, *, allow_remote_refs: bool = False) -> None:
        #: Set at construction rather than passed to `load`, because `load` is
        #: the versioned plugin interface every third-party spec plugin
        #: implements. Widening it to carry one loader option would break all
        #: of them for a flag none of them uses.
        self.allow_remote_refs = allow_remote_refs

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
        return load_openapi(source, allow_remote_refs=self.allow_remote_refs)
