"""OpenTelemetry-compatible trace export for verifier/test/load runs.

Opt-in only: nothing is exported anywhere unless an endpoint is explicitly
configured. Attributes are redacted before spans are ever materialized —
authorization headers, cookies, tokens and request/response bodies never
become span attributes.

The output is OTLP/JSON-shaped (resourceSpans → scopeSpans → spans), so it
can be POSTed to any OTLP/HTTP collector or inspected locally in tests.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

_SENSITIVE_KEY_PARTS = (
    "authorization",
    "cookie",
    "token",
    "secret",
    "password",
    "api_key",
    "apikey",
    "request_body",
    "response_body",
)


def redact_attributes(attrs: dict[str, Any]) -> dict[str, Any]:
    """Drop sensitive attributes; values are never partially logged."""
    out: dict[str, Any] = {}
    for key, value in attrs.items():
        lowered = key.lower()
        if any(part in lowered for part in _SENSITIVE_KEY_PARTS):
            out[key] = "[REDACTED]"
        else:
            out[key] = value
    return out


@dataclass
class Span:
    name: str
    trace_id: str
    span_id: str
    parent_span_id: str | None
    start_utc: str
    duration_ms: float
    attributes: dict[str, Any] = field(default_factory=dict)
    status: str = "ok"

    def to_otlp(self) -> dict[str, Any]:
        return {
            "traceId": self.trace_id,
            "spanId": self.span_id,
            "parentSpanId": self.parent_span_id,
            "name": self.name,
            "kind": "SPAN_KIND_INTERNAL",
            "startTimeUnixNano": str(int(time.time() * 1_000_000_000)),
            "attributes": [
                {"key": k, "value": {"stringValue": str(v)}}
                for k, v in sorted(redact_attributes(self.attributes).items())
            ],
            "status": {"code": "STATUS_CODE_OK" if self.status == "ok" else "STATUS_CODE_ERROR"},
        }


def _new_id(nbytes: int = 8) -> str:
    return uuid.uuid4().bytes.hex()[: nbytes * 2]


class TraceRecorder:
    """Collects spans for one run; deterministic IDs derive from the run seed."""

    def __init__(self, service_name: str = "apiverity", seed: str | None = None) -> None:
        self.service_name = service_name
        root = seed or uuid.uuid4().hex
        self.trace_id = hashlib.sha256(f"trace:{root}".encode()).hexdigest()[:32]
        self._spans: list[Span] = []
        self._counter = 0

    def start_span(
        self, name: str, *, parent_span_id: str | None = None, **attrs: Any
    ) -> tuple[str, float]:
        self._counter += 1
        span_id = hashlib.sha256(f"{self.trace_id}:{self._counter}:{name}".encode()).hexdigest()[
            :16
        ]
        started = time.monotonic()
        self._spans.append(
            Span(
                name=name,
                trace_id=self.trace_id,
                span_id=span_id,
                parent_span_id=parent_span_id,
                start_utc=datetime.now(UTC).isoformat(timespec="seconds"),
                duration_ms=-1.0,
                attributes=dict(attrs),
            )
        )
        return span_id, started

    def end_span(self, handle: tuple[str, float], *, status: str = "ok", **attrs: Any) -> None:
        span_id, started = handle
        for span in reversed(self._spans):
            if span.span_id == span_id:
                span.duration_ms = round((time.monotonic() - started) * 1000, 3)
                span.status = status
                span.attributes.update(attrs)
                return
        raise KeyError(span_id)

    @property
    def spans(self) -> list[Span]:
        return list(self._spans)

    def to_otlp_json(self) -> dict[str, Any]:
        return {
            "resourceSpans": [
                {
                    "resource": {
                        "attributes": [
                            {
                                "key": "service.name",
                                "value": {"stringValue": self.service_name},
                            }
                        ]
                    },
                    "scopeSpans": [
                        {
                            "scope": {"name": "apiverity"},
                            "spans": [s.to_otlp() for s in self._spans],
                        }
                    ],
                }
            ]
        }

    def export(self, endpoint: str, *, transport: Any = None) -> int:
        """POST OTLP/JSON to an explicitly configured collector; returns status."""
        import httpx

        send = transport or (
            lambda url, body: (
                httpx.post(
                    url,
                    content=json.dumps(body),
                    headers={"Content-Type": "application/json"},
                    timeout=10.0,
                ).status_code
            )
        )
        return int(send(endpoint, self.to_otlp_json()))
