"""Traffic import (HAR/logs) and central redaction.

Redaction covers authorization headers, cookies, API keys/tokens and
configurable sensitive fields. Redaction is always applied before any
corpus is stored in a bundle; secret values never persist.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

DEFAULT_SENSITIVE_HEADERS = {
    "authorization",
    "cookie",
    "set-cookie",
    "proxy-authorization",
    "x-api-key",
    "x-auth-token",
    "x-csrf-token",
}
DEFAULT_SENSITIVE_QUERY = {"api_key", "apikey", "token", "access_token", "secret", "password"}
DEFAULT_PATTERNS = [
    r"(?i)bearer\s+[a-z0-9._\-]+",
    r"(?i)sk-[a-z0-9]{16,}",
    r"(?i)(?:api[_-]?key|token|secret)\s*[=:]\s*\S+",
]


class RedactionConfig(BaseModel):
    sensitive_headers: set[str] = Field(default_factory=lambda: set(DEFAULT_SENSITIVE_HEADERS))
    sensitive_query_fields: set[str] = Field(default_factory=lambda: set(DEFAULT_SENSITIVE_QUERY))
    sensitive_body_fields: set[str] = Field(default_factory=lambda: {"password", "secret", "token"})
    patterns: list[str] = Field(default_factory=lambda: list(DEFAULT_PATTERNS))
    replacement: str = "[REDACTED]"

    def compiled(self) -> list[re.Pattern[str]]:
        return [re.compile(p) for p in self.patterns]


def redact_headers(headers: dict[str, str], cfg: RedactionConfig) -> dict[str, str]:
    out = {}
    rx = cfg.compiled()
    for k, v in headers.items():
        if k.lower() in cfg.sensitive_headers:
            out[k] = cfg.replacement
        else:
            for pattern in rx:
                v = pattern.sub(cfg.replacement, str(v))
            out[k] = v
    return out


def redact_query(params: dict[str, Any], cfg: RedactionConfig) -> dict[str, Any]:
    return {
        k: (cfg.replacement if k.lower() in cfg.sensitive_query_fields else v)
        for k, v in params.items()
    }


def redact_json(value: Any, cfg: RedactionConfig, *, is_body: bool = True) -> Any:
    fields = cfg.sensitive_body_fields if is_body else cfg.sensitive_query_fields
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k.lower() in fields:
                out[k] = cfg.replacement
            else:
                out[k] = redact_json(v, cfg, is_body=is_body)
        return out
    if isinstance(value, list):
        return [redact_json(v, cfg, is_body=is_body) for v in value]
    if isinstance(value, str):
        result = value
        for pattern in cfg.compiled():
            result = pattern.sub(cfg.replacement, result)
        return result
    return value


def import_har(path: str, cfg: RedactionConfig | None = None) -> list[dict[str, Any]]:
    """Import a HAR file into sanitized request/response entries."""
    cfg = cfg or RedactionConfig()
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    entries = []
    for entry in data.get("log", {}).get("entries", []):
        req = entry.get("request", {})
        resp = entry.get("response", {})
        qdict = {q["name"]: q.get("value") for q in req.get("queryString", [])}
        post = req.get("postData", {}).get("text")
        entries.append(
            {
                "method": req.get("method"),
                "url": req.get("url"),
                "request_headers": redact_headers(
                    {h["name"]: h.get("value") for h in req.get("headers", [])}, cfg
                ),
                "query": redact_query(qdict, cfg),
                "request_body": redact_json(json.loads(post), cfg) if post else None,
                "status": resp.get("status"),
                "response_headers": redact_headers(
                    {h["name"]: h.get("value") for h in resp.get("headers", [])}, cfg
                ),
                "response_body": None,  # bodies are not persisted by default
            }
        )
    return entries
