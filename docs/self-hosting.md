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

### Docker

```bash
docker build -t apiverity-server .
docker run -p 8090:8090 -v verity-data:/data apiverity-server
```

Configuration via environment variables: `VERITY_DB` (SQLite path inside the
container, default `/data/verity.db`) and `VERITY_PORT` (default `8090`).
Prebuilt images are published to `ghcr.io/webdevsamran/api-verity-lab-server`
on every tagged release (`docker pull ghcr.io/webdevsamran/api-verity-lab-server:latest`).

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
latency summaries; OTLP trace export is opt-in per run, either from the CLI —
`apiverity drift manifest.json --base-url URL --otlp-endpoint URL` — or from
`apiverity.exporters.otel.TraceRecorder.export(endpoint)`. Sensitive
attributes are redacted before export (see SAFETY_MODEL.md).

MCP spans follow the [OpenTelemetry GenAI semantic
conventions](https://github.com/open-telemetry/semantic-conventions-genai)
(`docs/gen-ai/mcp.md`, read 2026-09-10): `mcp.method.name`,
`mcp.protocol.version`, `gen_ai.tool.name`, `gen_ai.operation.name`,
`jsonrpc.request.id`, `rpc.response.status_code`, `error.type` and the
`network.*` / `server.*` attributes, on `SPAN_KIND_CLIENT` spans named
`{method} {target}`. Those conventions are **Development** status in a
repository with no tagged release, so the names live in one module
(`apiverity/exporters/semconv.py`) and a rename upstream is a one-file diff.

Trace context is propagated in `params._meta` as an unprefixed `traceparent`,
which the conventions specify for MCP: one MCP request can be retried across
several HTTP requests and one HTTP request can carry several MCP messages, so
HTTP-level propagation does not describe the MCP call.

`gen_ai.tool.call.arguments` and `gen_ai.tool.call.result` are defined by the
conventions as opt-in and are **never emitted here**. They carry a tool's
inputs and outputs verbatim, and a span leaves the machine.

## Air-gapped operation

No telemetry, no phone-home, no auto-update. All artifacts (results,
bundles, exports) are plain files; docs ship in-repo.
