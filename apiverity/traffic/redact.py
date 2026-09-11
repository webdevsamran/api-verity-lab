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
    # Two changes to this one, both found by recording real traffic through
    # `apiverity capture`:
    #
    # `password` belongs here for the same reason it is in
    # `sensitive_body_fields` below -- the two lists were treating the same
    # word as sensitive in one place and not the other, so a password in a
    # *named field* was redacted and the identical string inside an opaque text
    # value was not.
    #
    # And the name may be quoted. A credential inside a string value arrives as
    # JSON or YAML -- `"password": "x"` -- where the quote sits between the
    # name and the separator, so a pattern requiring them adjacent matches the
    # bare form and misses every serialized one.
    r"(?i)[\"']?(?:api[_-]?key|token|secret|password)[\"']?\s*[=:]\s*\S+",
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


def _decode_body(raw: str | None, mime: str, cfg: RedactionConfig) -> tuple[Any, str | None]:
    """Decode a HAR body, returning (value, reason it was dropped).

    A HAR carries whatever the browser saw: form encodings, HTML error pages,
    base64 images, truncated payloads. `json.loads` on all of it raised, which
    took down the import of an entire corpus over one non-JSON entry. A body
    that cannot be parsed is now reported as a reason rather than an
    exception, so the corpus-quality summary can say how much was lost and
    why.
    """
    if raw is None or raw == "":
        return None, None
    if "json" not in (mime or "").lower():
        return None, f"body is {mime or 'an unknown type'}, not JSON"
    try:
        parsed = json.loads(raw)
    except ValueError:
        return None, "body is not parseable JSON (truncated or encoded?)"
    return redact_json(parsed, cfg), None


def import_har(
    path: str,
    cfg: RedactionConfig | None = None,
    *,
    include_response_bodies: bool = False,
) -> list[dict[str, Any]]:
    """Import a HAR file into sanitized request/response entries.

    Response bodies stay out by default: a HAR recorded against a real service
    contains real user data, and a corpus is something people commit. Drift
    detection against a corpus needs them, so `include_response_bodies=True`
    opts in -- redaction still applies, and every entry records why a body is
    absent so a later report can distinguish "nothing was returned" from "we
    chose not to keep it".

    Timestamps are carried through. They were dropped here, which meant every
    analyser downstream saw an unordered bag of requests: a drift report could
    say a header was missing from four hundred responses and not whether that
    started last Tuesday, and a call budget could not express a window at all.
    `startedDateTime` is copied verbatim rather than parsed, because a HAR
    writes an ISO-8601 instant and re-deriving one loses the offset the
    recorder chose.

    A timestamp is metadata about a real request and the redaction config has
    no rule for it, deliberately: the corpus already came from a HAR the caller
    holds, and an entry with no time is not anonymous, only useless.
    """
    cfg = cfg or RedactionConfig()
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    entries = []
    for entry in data.get("log", {}).get("entries", []):
        req = entry.get("request", {})
        resp = entry.get("response", {})
        qdict = {q["name"]: q.get("value") for q in req.get("queryString", [])}

        post = req.get("postData", {}) or {}
        request_body, request_body_dropped = _decode_body(
            post.get("text"), str(post.get("mimeType") or ""), cfg
        )

        content = resp.get("content", {}) or {}
        if include_response_bodies:
            response_body, response_body_dropped = _decode_body(
                content.get("text"), str(content.get("mimeType") or ""), cfg
            )
        else:
            response_body, response_body_dropped = None, "response bodies not imported"

        entries.append(
            {
                "method": req.get("method"),
                "url": req.get("url"),
                "request_headers": redact_headers(
                    {h["name"]: h.get("value") for h in req.get("headers", [])}, cfg
                ),
                "query": redact_query(qdict, cfg),
                "request_body": request_body,
                "request_body_dropped": request_body_dropped,
                "status": resp.get("status"),
                "response_headers": redact_headers(
                    {h["name"]: h.get("value") for h in resp.get("headers", [])}, cfg
                ),
                "response_body": response_body,
                "response_body_dropped": response_body_dropped,
                "response_mime": str(content.get("mimeType") or ""),
                "started_at": entry.get("startedDateTime"),
                "elapsed_ms": entry.get("time"),
            }
        )
    return entries
