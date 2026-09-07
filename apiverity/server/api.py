"""Self-hosted REST API for API Verity Lab.

A modular Flask application exposing contracts, findings, runs, environments,
policies, approvals, audit events, webhooks and can-i-deploy decisions with
RBAC enforcement, health/readiness endpoints and Prometheus-style metrics.
"""

from __future__ import annotations

import json
import time
from typing import Any

from flask import Flask, Response, g, jsonify, request

from apiverity.server.auth import Identity, IdentityProvider, LocalTokenProvider, authorize
from apiverity.server.decision import authenticate_safe, compute_can_i_deploy
from apiverity.server.store import Store

__all__ = ["authenticate_safe", "compute_can_i_deploy", "create_app"]

_METRICS = {
    "requests_total": 0,
    "errors_total": 0,
    "auth_failures_total": 0,
    "latency_sum_ms": 0.0,
    "jobs_enqueued_total": 0,
    "jobs_rejected_total": 0,
    "rate_limited_total": 0,
}

_RATE_BUCKETS: dict[tuple[str, int], tuple[int, int]] = {}


def create_app(
    store: Store,
    *,
    providers: list[IdentityProvider] | None = None,
    webhook_transport: Any = None,
    secret_resolver: Any = None,
    rate_limit_per_minute: int | None = None,
    max_active_jobs: int = 4,
) -> Flask:
    app = Flask("apiverity-server")
    if providers is None:
        providers = [LocalTokenProvider(store)]

    def _rate_bucket_key() -> str:
        auth = request.headers.get("Authorization", "")
        import hashlib as _hashlib

        return _hashlib.sha256(auth.encode()).hexdigest()[:16] if auth.strip() else "anon"

    @app.before_request
    def _start_timer() -> Any:
        g.started = time.monotonic()
        if rate_limit_per_minute is not None and request.path != "/healthz":
            window = int(time.monotonic() // 60)
            key = (_rate_bucket_key(), window)
            count, seen_window = _RATE_BUCKETS.get(key, (0, window))
            if seen_window != window:
                count = 0
            if count >= rate_limit_per_minute:
                _METRICS["rate_limited_total"] += 1
                return jsonify({"error": "rate limit exceeded"}), 429
            _RATE_BUCKETS[key] = (count + 1, window)
            # opportunistic cleanup of stale windows
            if len(_RATE_BUCKETS) > 10_000:
                for stale in [k for k in _RATE_BUCKETS if k[1] != window]:
                    del _RATE_BUCKETS[stale]
        return None

    @app.after_request
    def _record(resp: Response) -> Response:
        _METRICS["requests_total"] += 1
        if resp.status_code >= 400:
            _METRICS["errors_total"] += 1
        _METRICS["latency_sum_ms"] += (time.monotonic() - g.get("started", time.monotonic())) * 1000
        return resp

    def current_identity(action: str) -> tuple[Identity | None, tuple[Any, ...] | None]:
        auth = request.headers.get("Authorization", "")
        token = auth.removeprefix("Bearer ").strip()
        identity = authenticate_safe(providers, token)
        if identity is None:
            _METRICS["auth_failures_total"] += 1
            return None, (jsonify({"error": "unauthenticated"}), 401)
        if not authorize(identity, action):
            return None, (
                jsonify({"error": f"forbidden: role '{identity.role.value}' cannot '{action}'"}),
                403,
            )
        return identity, None

    def notify(event: str, payload: dict[str, Any]) -> None:
        from apiverity.server.webhooks import dispatch

        hooks = store.list_webhooks(g.identity.org_id, event=event)
        dispatch(
            hooks,
            event=event,
            payload=payload,
            transport=webhook_transport,
            secret_resolver=secret_resolver,
        )

    # --- health -----------------------------------------------------------

    @app.get("/healthz")
    def healthz() -> Any:
        return jsonify({"status": "ok"})

    @app.get("/readyz")
    def readyz() -> Any:
        try:
            store.conn.execute("SELECT 1").fetchone()
            return jsonify({"status": "ready"})
        except Exception as exc:
            return jsonify({"status": "not-ready", "error": str(exc)}), 503

    @app.get("/metrics")
    def metrics() -> Any:
        lines = [
            "# TYPE apiverity_requests_total counter",
            f"apiverity_requests_total {_METRICS['requests_total']}",
            "# TYPE apiverity_errors_total counter",
            f"apiverity_errors_total {_METRICS['errors_total']}",
            "# TYPE apiverity_auth_failures_total counter",
            f"apiverity_auth_failures_total {_METRICS['auth_failures_total']}",
            "# TYPE apiverity_latency_ms summary",
            f"apiverity_latency_ms_sum {_METRICS['latency_sum_ms']:.1f}",
            "# TYPE apiverity_jobs_enqueued_total counter",
            f"apiverity_jobs_enqueued_total {_METRICS['jobs_enqueued_total']}",
            "# TYPE apiverity_jobs_rejected_total counter",
            f"apiverity_jobs_rejected_total {_METRICS['jobs_rejected_total']}",
            "# TYPE apiverity_rate_limited_total counter",
            f"apiverity_rate_limited_total {_METRICS['rate_limited_total']}",
        ]
        return Response(chr(10).join(lines) + chr(10), mimetype="text/plain")

    # --- orgs & users ---------------------------------------------------------

    @app.post("/v1/orgs")
    def create_org() -> Any:
        body = request.get_json(force=True)
        org_id = store.create_org(body["name"])
        owner_token = body.get("owner_token") or f"vlk-{org_id}-bootstrap"
        store.add_user(org_id, body.get("owner_subject", "bootstrap"), "owner", token=owner_token)
        store.audit_append(org_id, "system", "org.created", body["name"])
        return jsonify({"org_id": org_id, "owner_token": owner_token}), 201

    @app.post("/v1/orgs/<int:org_id>/users")
    def add_user(org_id: int) -> Any:
        g.identity, err = current_identity("manage_users")
        if err:
            return err
        body = request.get_json(force=True)
        user_id = store.add_user(
            org_id,
            body["subject"],
            body.get("role", "viewer"),
            display_name=body.get("display_name", ""),
            kind=body.get("kind", "user"),
            token=body.get("token"),
        )
        store.audit_append(
            org_id,
            g.identity.subject,
            "user.added",
            body["subject"],
            {"role": body.get("role", "viewer")},
        )
        return jsonify({"user_id": user_id}), 201

    @app.get("/v1/orgs/<int:org_id>/users")
    def list_users(org_id: int) -> Any:
        g.identity, err = current_identity("read")
        if err:
            return err
        return jsonify(store.list_users(org_id))

    # --- contracts -----------------------------------------------------------------

    @app.post("/v1/contracts")
    def publish_contract() -> Any:
        g.identity, err = current_identity("publish_contract")
        if err:
            return err
        body = request.get_json(force=True)
        contract_id = store.publish_contract(
            g.identity.org_id,
            body["title"],
            body["version"],
            body.get("protocol", "openapi"),
            body["spec"],
            g.identity.subject,
        )
        if isinstance(body.get("findings"), list):
            store.add_findings(contract_id, body["findings"])
        store.audit_append(
            g.identity.org_id,
            g.identity.subject,
            "contract.published",
            f"{body['title']}@{body['version']}",
            {"checksum": True},
        )
        notify("contract.published", {"title": body["title"], "version": body["version"]})
        return jsonify({"contract_id": contract_id}), 201

    @app.get("/v1/contracts")
    def list_contracts() -> Any:
        g.identity, err = current_identity("read")
        if err:
            return err
        return jsonify(store.list_contracts(g.identity.org_id, title=request.args.get("title")))

    @app.get("/v1/contracts/<int:contract_id>")
    def get_contract(contract_id: int) -> Any:
        g.identity, err = current_identity("read")
        if err:
            return err
        contract = store.get_contract(contract_id)
        if contract is None or contract["org_id"] != g.identity.org_id:
            return jsonify({"error": "not found"}), 404
        return jsonify(contract)

    @app.post("/v1/contracts/<int:contract_id>/findings")
    def add_findings(contract_id: int) -> Any:
        g.identity, err = current_identity("publish_contract")
        if err:
            return err
        contract = store.get_contract(contract_id)
        if contract is None or contract["org_id"] != g.identity.org_id:
            return jsonify({"error": "not found"}), 404
        count = store.add_findings(contract_id, request.get_json(force=True).get("findings", []))
        return jsonify({"added": count}), 201

    @app.get("/v1/contracts/<int:contract_id>/findings")
    def list_findings(contract_id: int) -> Any:
        g.identity, err = current_identity("read")
        if err:
            return err
        return jsonify(store.list_findings(contract_id))

    # --- runs ----------------------------------------------------------------------

    @app.post("/v1/runs")
    def record_run() -> Any:
        g.identity, err = current_identity("record_run")
        if err:
            return err
        body = request.get_json(force=True)
        run_id = store.record_run(
            g.identity.org_id,
            body["kind"],
            g.identity.subject,
            result=body.get("result"),
            status=body.get("status", "queued"),
            verification_for=body.get("verification_for"),
            environment=body.get("environment"),
        )
        return jsonify({"run_id": run_id}), 201

    @app.get("/v1/runs/<int:run_id>")
    def get_run(run_id: int) -> Any:
        g.identity, err = current_identity("read")
        if err:
            return err
        run = store.get_run(run_id)
        if run is None or run["org_id"] != g.identity.org_id:
            return jsonify({"error": "not found"}), 404
        return jsonify(run)

    @app.post("/v1/runs/<int:run_id>/cancel")
    def cancel_run(run_id: int) -> Any:
        g.identity, err = current_identity("record_run")
        if err:
            return err
        ok = store.cancel_run(run_id)
        return (jsonify({"cancelled": True}), 200) if ok else (jsonify({"cancelled": False}), 409)

    # --- workers & distributed jobs ---------------------------------------------------

    from apiverity.server.jobs import JobQueue, QueueFull

    queue = JobQueue(store, max_active_per_org=max_active_jobs)

    @app.post("/v1/workers")
    def enroll_worker() -> Any:
        g.identity, err = current_identity("record_run")
        if err:
            return err
        body = request.get_json(force=True)
        worker_id = store.register_worker(
            g.identity.org_id,
            body["name"],
            labels=body.get("labels", []),
            capacity=int(body.get("capacity", 1)),
        )
        store.audit_append(g.identity.org_id, g.identity.subject, "worker.enrolled", body["name"])
        return jsonify({"worker_id": worker_id}), 201

    @app.get("/v1/workers")
    def list_workers() -> Any:
        g.identity, err = current_identity("read")
        if err:
            return err
        return jsonify(store.list_workers(g.identity.org_id))

    @app.post("/v1/jobs")
    def enqueue_job() -> Any:
        """Enqueue a distributed run; idempotent by ``idempotency_key``."""
        g.identity, err = current_identity("record_run")
        if err:
            return err
        body = request.get_json(force=True)
        try:
            run_id, created = queue.enqueue(
                g.identity.org_id,
                body["kind"],
                g.identity.subject,
                verification_for=body.get("verification_for"),
                environment=body.get("environment"),
                idempotency_key=body.get("idempotency_key"),
            )
        except QueueFull as exc:
            _METRICS["jobs_rejected_total"] += 1
            return jsonify({"error": str(exc)}), 409
        _METRICS["jobs_enqueued_total"] += 1
        return (
            jsonify({"run_id": run_id, "deduplicated": not created}),
            201 if created else 200,
        )

    @app.post("/v1/jobs/claim")
    def claim_job() -> Any:
        """Worker pull endpoint: claim the next queued job for this org."""
        g.identity, err = current_identity("record_run")
        if err:
            return err
        body = request.get_json(force=True) or {}
        worker_name = body.get("worker") or f"anon-{g.identity.subject}"
        job = queue.claim(g.identity.org_id, worker_name)
        if job is None:
            return jsonify({"job": None}), 204
        return jsonify(job)

    @app.get("/v1/runs/<int:run_id>/events")
    def run_events(run_id: int) -> Any:
        """SSE stream of run progress events (deterministic: current history + final)."""
        g.identity, err = current_identity("read")
        if err:
            return err
        run = store.get_run(run_id)
        if run is None or run["org_id"] != g.identity.org_id:
            return jsonify({"error": "not found"}), 404

        def generate() -> Any:
            for ev in store.list_run_events(run_id):
                data = json.dumps(ev)
                yield f"id: {ev['id']}\nevent: progress\ndata: {data}\n\n"
            final = store.get_run(run_id)
            status = final["status"] if final else "unknown"
            yield f"event: status\ndata: {json.dumps({'run_id': run_id, 'status': status})}\n\n"

        return Response(generate(), mimetype="text/event-stream")

    # --- environments -----------------------------------------------------------------

    @app.post("/v1/environments")
    def register_environment() -> Any:
        g.identity, err = current_identity("register_environment")
        if err:
            return err
        body = request.get_json(force=True)
        env_id = store.register_environment(
            g.identity.org_id,
            body["name"],
            body["base_url"],
            body.get("safety_class", "dev"),
            body.get("owner"),
            body.get("allowed_modes", "read-only"),
        )
        store.audit_append(
            g.identity.org_id,
            g.identity.subject,
            "environment.registered",
            body["name"],
            {"safety_class": body.get("safety_class", "dev")},
        )
        return jsonify({"environment_id": env_id}), 201

    @app.get("/v1/environments")
    def list_environments() -> Any:
        g.identity, err = current_identity("read")
        if err:
            return err
        return jsonify(store.list_environments(g.identity.org_id))

    # --- policies / approvals ------------------------------------------------------------

    @app.put("/v1/policies/<name>")
    def set_policy(name: str) -> Any:
        g.identity, err = current_identity("set_policy")
        if err:
            return err
        content = request.get_json(force=True)
        store.set_policy(g.identity.org_id, name, content.get("content", ""))
        store.audit_append(g.identity.org_id, g.identity.subject, "policy.updated", name)
        return jsonify({"ok": True})

    @app.get("/v1/policies/<name>")
    def get_policy(name: str) -> Any:
        g.identity, err = current_identity("read")
        if err:
            return err
        policy = store.get_policy(g.identity.org_id, name)
        return (jsonify(policy), 200) if policy else (jsonify({"error": "not found"}), 404)

    @app.post("/v1/approvals")
    def request_approval() -> Any:
        g.identity, err = current_identity("request_approval")
        if err:
            return err
        body = request.get_json(force=True)
        approval_id = store.request_approval(
            g.identity.org_id,
            body["contract_title"],
            body["from_version"],
            body["to_version"],
            body["justification"],
            g.identity.subject,
            body.get("migration_guide"),
        )
        notify("approval.requested", {"approval_id": approval_id})
        return jsonify({"approval_id": approval_id}), 201

    @app.post("/v1/approvals/<int:approval_id>/decision")
    def decide_approval(approval_id: int) -> Any:
        g.identity, err = current_identity("decide_approval")
        if err:
            return err
        decision = request.get_json(force=True)["decision"]
        try:
            ok = store.decide_approval(approval_id, decision, g.identity.subject)
        except ValueError:
            return jsonify({"error": "invalid decision"}), 400
        if not ok:
            return jsonify({"error": "already decided or missing"}), 409
        store.audit_append(
            g.identity.org_id, g.identity.subject, f"approval.{decision}", str(approval_id)
        )
        notify(f"approval.{decision}", {"approval_id": approval_id})
        return jsonify({"ok": True})

    # --- can-i-deploy -----------------------------------------------------------------------

    @app.post("/v1/can-i-deploy")
    def can_i_deploy() -> Any:
        g.identity, err = current_identity("read")
        if err:
            return err
        body = request.get_json(force=True)
        decision = compute_can_i_deploy(store, g.identity.org_id, body)
        return jsonify(decision)

    # --- audit & webhooks ---------------------------------------------------------------------

    @app.get("/v1/audit")
    def audit_list() -> Any:
        g.identity, err = current_identity("view_audit")
        if err:
            return err
        events = store.audit_list(g.identity.org_id)
        return jsonify(
            {"events": events, "chain_valid": store.audit_verify_chain(g.identity.org_id)}
        )

    @app.post("/v1/webhooks")
    def register_webhook() -> Any:
        g.identity, err = current_identity("register_webhook")
        if err:
            return err
        body = request.get_json(force=True)
        hook_id = store.register_webhook(
            g.identity.org_id, body["url"], body["secret_ref"], body.get("events", [])
        )
        return jsonify({"webhook_id": hook_id}), 201

    @app.get("/v1/webhooks")
    def list_webhooks() -> Any:
        g.identity, err = current_identity("read")
        if err:
            return err
        return jsonify(store.list_webhooks(g.identity.org_id))

    return app
