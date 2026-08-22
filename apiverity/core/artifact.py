"""Versioned result-artifact envelope (§21 of the product spec).

Every command payload is enriched with: tool version, result schema
version, protocol version, contract hash (sha256 of the spec file),
target metadata, seed, timing and redaction state.
"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

RESULT_SCHEMA_VERSION = 1


def contract_hash(spec_path: str | None) -> str:
    """Stable sha256 of the contract file ('0'*64 when unavailable)."""
    if not spec_path:
        return "0" * 64
    try:
        return hashlib.sha256(Path(spec_path).read_bytes()).hexdigest()
    except OSError:
        return "0" * 64


class ArtifactMeta(BaseModel):
    tool: str = "apiverity"
    tool_version: str = "0.1.0"
    result_schema_version: int = RESULT_SCHEMA_VERSION
    contract_hash: str = Field(default_factory=lambda: "0" * 64)
    protocol_version: str = "openapi-3.x"
    target: str | None = None
    seed: int | None = None
    duration_ms: int = 0
    redaction: dict[str, Any] = Field(
        default_factory=lambda: {"applied": True, "sensitive_field_count": 10}
    )


def enrich(
    payload: dict[str, Any],
    *,
    spec_path: str | None = None,
    target: str | None = None,
    seed: int | None = None,
) -> dict[str, Any]:
    """Merge artifact metadata into a command payload (in place)."""
    started = payload.pop("_started", None)
    meta = ArtifactMeta(
        contract_hash=contract_hash(spec_path),
        target=target,
        seed=seed,
        duration_ms=int((time.monotonic() - started) * 1000) if started else 0,
    )
    enriched = {"tool": payload.get("tool", "apiverity"), **payload}
    for key, value in meta.model_dump().items():
        enriched.setdefault(key, value)
    enriched["tool"] = meta.tool
    return enriched