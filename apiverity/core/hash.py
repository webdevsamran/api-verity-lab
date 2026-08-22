"""Deterministic hashing helpers for contracts and artifacts."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel


def canonical_json(value: Any) -> str:
    """Stable JSON serialization used for hashing."""
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json", exclude_none=True)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def sha256_hex(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def contract_hash(service: Any) -> str:
    """Hash of a normalized contract, excluding volatile metadata."""
    return f"sha256:{sha256_hex(service)}"