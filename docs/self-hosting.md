# Self-Hosting Guide

The server is a modular Flask monolith with SQLite (`apiverity/server/`).
It is optional: the CLI/SDK work fully offline without it.

## Run

```bash
pip install -e ".[dev]"
python -c "
from apiverity.server import Store
from apiverity.server.api import create_app
app = create_app(Store('verity.db'))
app.run(port=8090)
"
```

Endpoints: `/healthz`, `/readyz`, `/metrics`, and `/v1/*` for orgs, users,
contracts, findings, runs, environments, policies, approvals, webhooks,
can-i-deploy, workers and jobs. RBAC: `owner > admin > member > viewer`;
tokens are stored hashed.

## Distributed runs (worker fleet)

```bash
# operator: enqueue a job (idempotent — safe CI retries)
curl -X POST :8090/v1/jobs -H "Authorization: Bearer $TOKEN" \
  -d '{"kind":"test","environment":"staging","idempotency_key":"ci-42"}'

# worker inside the private network: enroll once, then pull
curl -X POST :8090/v1/workers -H "Authorization: Bearer $WORKER_TOKEN" \
  -d '{"name":"runner-1","labels":["gpu"]}'
curl -X POST :8090/v1/jobs/claim -H "Authorization: Bearer $WORKER_TOKEN" \
  -d '{"worker":"runner-1"}'
```

Progress is streamable as Server-Sent Events:
`GET /v1/runs/<id>/events` emits `progress` events then a final `status`.
Concurrency is capped per org (`create_app(..., max_active_jobs=N)`);
overflow returns 409 rather than queueing unbounded.

## Rate limiting

```python
app = create_app(store, rate_limit_per_minute=120)
```

Fixed window per bearer token; `/healthz` exempt; 429s are counted in
`/metrics` (`apiverity_rate_limited_total`).

## Backup / restore / export / import

```bash
apiverity server-db backup --db verity.db -o backups/snap.db   # online snapshot
apiverity server-db restore --db backups/snap.db -o restored.db
apiverity server-db export --db restored.db --org-id 1 -o org.json  # no token hashes
apiverity server-db import --db verity.db --input org.json     # becomes a new org
```

Retention: `Store.purge_older_than(days)` prunes old findings/runs.
Audit events are hash-chained; verify with `store.audit_verify_chain(org_id)`.

## Identity providers

Local token auth works out of the box. For OIDC/SAML, implement the
`IdentityProvider` protocol (`verify(token) -> (subject, claims) | None`)
and pass instances via `create_app(store, providers=[...])`. A real IdP
integration requires an environment we do not ship; see ISSUES.md.

## Observability

Prometheus text metrics at `/metrics`; structured request counters and
latency summaries; OTLP trace export is opt-in per run via
`apiverity.exporters.otel.TraceRecorder.export(endpoint)` — sensitive
attributes are redacted before export (see SAFETY_MODEL.md).

## Air-gapped operation

No telemetry, no phone-home, no auto-update. All artifacts (results,
bundles, exports) are plain files; docs ship in-repo.
