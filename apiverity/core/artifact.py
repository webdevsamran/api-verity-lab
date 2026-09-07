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


def tool_version() -> str:
    """The version actually installed, not a literal in this file.

    This used to be a hardcoded `"0.1.0"` default on the model, so every
    artifact this tool has ever written -- every result bundle, every JSON
    export, every SARIF upload -- claimed 0.1.0 no matter which version
    produced it. A provenance field that does not track the thing it names is
    worse than an absent one: a consumer diffing two bundles would conclude
    the tool had not changed.
    """
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("api-verity-lab")
    except PackageNotFoundError:  # running from a source tree, not installed
        pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
        try:
            import tomllib

            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            return str(data["project"]["version"])
        except Exception:
            return "unknown"


#: What `redaction` means when nothing has been redacted.
#:
#: The previous default asserted `{"applied": True, "sensitive_field_count":
#: 10}` on every artifact, unconditionally -- `enrich` performs no redaction
#: at all, so that was a fabricated claim about a security control, stamped
#: identically onto every output including ones with nothing sensitive in
#: them. Redaction is real, but it happens in `traffic/redact.py` on imported
#: corpora; it does not happen here.
NO_REDACTION: dict[str, Any] = {
    "applied": False,
    "reason": "no traffic corpus in this artifact; see traffic/redact.py for corpus imports",
}


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
    tool_version: str = Field(default_factory=tool_version)
    result_schema_version: int = RESULT_SCHEMA_VERSION
    contract_hash: str = Field(default_factory=lambda: "0" * 64)
    #: The protocol of the contract this artifact describes. Defaults to
    #: unknown rather than to OpenAPI: it was fixed at "openapi-3.x", so a
    #: gRPC or AsyncAPI run produced an artifact claiming to be OpenAPI.
    protocol_version: str = "unknown"
    target: str | None = None
    seed: int | None = None
    duration_ms: int = 0
    redaction: dict[str, Any] = Field(default_factory=lambda: dict(NO_REDACTION))


def enrich(
    payload: dict[str, Any],
    *,
    spec_path: str | None = None,
    target: str | None = None,
    seed: int | None = None,
    protocol: str | None = None,
    redaction: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge artifact metadata into a command payload (in place).

    `protocol` and `redaction` are passed by callers that know them. Both
    previously had fixed defaults that were simply wrong for most runs -- see
    the notes on `ArtifactMeta` and `NO_REDACTION`.
    """
    started = payload.pop("_started", None)
    meta = ArtifactMeta(
        contract_hash=contract_hash(spec_path),
        target=target,
        seed=seed,
        duration_ms=int((time.monotonic() - started) * 1000) if started else 0,
        # Named rather than **-splatted so the types stay checkable; the
        # field defaults handle the None case.
        protocol_version=protocol or ArtifactMeta.model_fields["protocol_version"].default,
        redaction=redaction if redaction is not None else dict(NO_REDACTION),
    )
    enriched = {"tool": payload.get("tool", "apiverity"), **payload}
    for key, value in meta.model_dump().items():
        enriched.setdefault(key, value)
    enriched["tool"] = meta.tool
    return enriched
