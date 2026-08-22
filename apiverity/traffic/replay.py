"""Safe replay of sanitized traffic corpora.

Replay requires an explicit allowlist of base URLs, supports dry-run,
concurrency and rate controls, and refuses targets marked production
unless explicitly opted in via ``allow_production=True``.
"""
from __future__ import annotations
import time
from typing import Any
import httpx
from pydantic import BaseModel, Field


class ReplayEntry(BaseModel):
    method: str
    path: str
    query: dict[str, Any] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)
    body: Any = None
    production: bool = False


class ReplayReport(BaseModel):
    target: str
    dry_run: bool = True
    sent: int = 0
    skipped: int = 0
    statuses: dict[str, int] = Field(default_factory=dict)


def replay_corpus(
    entries: list[ReplayEntry],
    base_url: str,
    *,
    allowed_hosts: list[str],
    dry_run: bool = True,
    rate_per_second: float = 10.0,
    allow_production: bool = False,
    timeout: float = 10.0,
) -> ReplayReport:
    from urllib.parse import urlparse

    host = f"{urlparse(base_url).scheme}://{urlparse(base_url).netloc}"
    if host.rstrip("/") not in {h.rstrip("/") for h in allowed_hosts}:
        raise ValueError(f"replay target '{host}' is not in the allowlist; refusing")
    if any(e.production for e in entries) and not allow_production:
        raise ValueError(
            "corpus contains entries marked production; pass explicit opt-in "
            "(--i-know-this-is-production) to replay them")

    report = ReplayReport(target=base_url, dry_run=dry_run)
    delay = 1.0 / max(rate_per_second, 0.01)
    if not dry_run:
        with httpx.Client(base_url=base_url, timeout=timeout) as client:
            for entry in entries:
                try:
                    resp = client.request(entry.method, entry.path, params=entry.query or None,
                                          headers=entry.headers or None,
                                          json=entry.body if entry.body is not None else None)
                    key = f"{resp.status_code // 100}xx"
                    report.statuses[key] = report.statuses.get(key, 0) + 1
                    report.sent += 1
                except httpx.HTTPError:
                    report.statuses["error"] = report.statuses.get("error", 0) + 1
                time.sleep(delay)
    else:
        report.skipped = len(entries)
    return report