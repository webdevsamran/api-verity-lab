"""Signed webhook notifications.

Deliveries are HMAC-SHA256 signed with the webhook secret so receivers can
verify authenticity. The HTTP transport is injectable; tests use a fake.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

Transport = Callable[[str, str, dict[str, str]], int]  # url, body, headers -> status


@dataclass(frozen=True)
class Delivery:
    webhook_url: str
    event: str
    status: int | None
    error: str | None = None


def sign_payload(secret: str, body: str) -> str:
    return hmac.new(secret.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).hexdigest()


def dispatch(
    webhooks: list[dict[str, Any]],
    *,
    event: str,
    payload: dict[str, Any],
    transport: Transport | None = None,
    secret_resolver: Callable[[str], str] | None = None,
) -> list[Delivery]:
    """Send ``event`` to every subscribed webhook. Never raises."""
    if transport is None:

        def transport(url: str, body: str, headers: dict[str, str]) -> int:
            raise RuntimeError("no webhook transport configured")

    deliveries: list[Delivery] = []
    body = json.dumps({"event": event, "id": uuid.uuid4().hex, "ts": time.time(), "data": payload})
    for wh in webhooks:
        events = wh.get("events") or []
        if events and event not in events:
            continue
        headers = {"Content-Type": "application/json"}
        secret_ref = wh.get("secret_ref", "")
        if secret_resolver is not None:
            with contextlib.suppress(KeyError):
                headers["X-Verity-Signature"] = sign_payload(secret_resolver(secret_ref), body)
        try:
            status = transport(wh["url"], body, headers)
            deliveries.append(Delivery(wh["url"], event, status))
        except Exception as exc:
            deliveries.append(Delivery(wh["url"], event, None, error=str(exc)))
    return deliveries
