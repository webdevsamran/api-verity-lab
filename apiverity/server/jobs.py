"""Distributed job queue for self-hosted worker fleets.

Deterministic, store-backed pull model: the server enqueues runs, enrolled
workers claim them inside their private network. No background threads —
progress is driven by explicit :meth:`JobQueue.claim` / ``complete`` calls,
which keeps behavior testable and audit-friendly.

- Idempotency: enqueue with the same ``idempotency_key`` returns the existing
  run instead of creating a duplicate (safe CI retries).
- Backpressure: per-org concurrency limit; exceeding it raises
  :class:`QueueFull` so callers get a clean 409 instead of silent overload.
- Progress: every state change appends a run event consumable via SSE.
"""

from __future__ import annotations

from typing import Any

from apiverity.server.store import Store


class QueueFull(Exception):
    """The organization hit its concurrent-jobs limit."""


class JobQueue:
    def __init__(self, store: Store, max_active_per_org: int = 4) -> None:
        self.store = store
        self.max_active_per_org = max_active_per_org

    def enqueue(
        self,
        org_id: int,
        kind: str,
        requested_by: str,
        *,
        verification_for: str | None = None,
        environment: str | None = None,
        idempotency_key: str | None = None,
    ) -> tuple[int, bool]:
        """Return ``(run_id, created)``; ``created=False`` on idempotent replay."""
        if idempotency_key:
            existing = self.store.find_run_by_idempotency_key(org_id, idempotency_key)
            if existing is not None and existing["status"] not in ("cancelled", "failed"):
                return int(existing["id"]), False
        if self.store.active_run_count(org_id) >= self.max_active_per_org:
            raise QueueFull(f"org {org_id} already has {self.max_active_per_org} active jobs")
        run_id = self.store.record_run(
            org_id,
            kind,
            requested_by,
            status="queued",
            verification_for=verification_for,
            environment=environment,
            idempotency_key=idempotency_key,
        )
        self.store.append_run_event(run_id, f"queued '{kind}' by {requested_by}", 0)
        return run_id, True

    def claim(self, org_id: int, worker_name: str) -> dict[str, Any] | None:
        """Worker pull: atomically claim the oldest queued job, if any."""
        return self.store.claim_next_run(org_id, worker_name)

    def progress(self, run_id: int, message: str, pct: int | None = None) -> None:
        self.store.append_run_event(run_id, message, pct)

    def complete(self, run_id: int, result: dict[str, Any], *, passed: bool = True) -> None:
        status = "passed" if passed else "failed"
        self.store.update_run(run_id, status=status, result=result)
        self.store.append_run_event(run_id, f"finished: {status}", 100)

    def cancel(self, run_id: int) -> bool:
        if self.store.cancel_run(run_id):
            self.store.append_run_event(run_id, "cancelled", None)
            return True
        return False
