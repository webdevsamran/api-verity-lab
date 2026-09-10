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


#: OTLP span kinds, as the protocol spells them.
KIND_INTERNAL = "SPAN_KIND_INTERNAL"
KIND_CLIENT = "SPAN_KIND_CLIENT"
KIND_SERVER = "SPAN_KIND_SERVER"


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
    kind: str = KIND_INTERNAL
    #: Wall-clock start, in nanoseconds since the epoch. Recorded when the span
    #: opens rather than derived at export time, which is the whole point --
    #: see `to_otlp`.
    start_unix_nano: int = 0

    def to_otlp(self) -> dict[str, Any]:
        """One span, in OTLP/JSON.

        `startTimeUnixNano` used to be `time.time()` read *here*, at
        serialization -- so every span in an exported batch claimed to have
        started at the same instant, the instant of the export, and none of
        them recorded when they actually ran. `endTimeUnixNano` was not emitted
        at all, which is a required field: a collector receiving this got a
        batch of zero-length spans stamped in the future, and the measured
        `duration_ms` sitting on the dataclass never left the process.

        Both are written from what the span actually recorded now.
        """
        start = self.start_unix_nano
        elapsed = self.duration_ms if self.duration_ms >= 0 else 0.0
        end = start + int(elapsed * 1_000_000)
        return {
            "traceId": self.trace_id,
            "spanId": self.span_id,
            "parentSpanId": self.parent_span_id,
            "name": self.name,
            "kind": self.kind,
            "startTimeUnixNano": str(start),
            "endTimeUnixNano": str(end),
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
        self,
        name: str,
        *,
        parent_span_id: str | None = None,
        kind: str = KIND_INTERNAL,
        **attrs: Any,
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
                kind=kind,
                # `time.time` for the wall clock the collector needs and
                # `time.monotonic` for the duration, because only one of them
                # is immune to the clock stepping mid-run.
                start_unix_nano=time.time_ns(),
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

    def traceparent(self, span_id: str) -> str:
        """W3C `traceparent` naming this recorder's trace and one span in it.

        Handed to the MCP client so a probe's request carries the context the
        server needs to make its own span a child of ours. Without it the two
        halves of one call are two unrelated traces.
        """
        from apiverity.exporters.semconv import traceparent

        return traceparent(self.trace_id, span_id)

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
