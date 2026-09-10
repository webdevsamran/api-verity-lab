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

## Reading the server from the dashboard

`web/` can point at a running server instead of the bundled `demo-data.json`.
Two things had to exist first, and neither did:

**CORS.** The server sent no cross-origin headers at all, so a dashboard on
another origin got a console error and a blank page rather than a server that
said no. It is opt-in, and there is deliberately no wildcard:

```python
app = create_app(store, cors_origins=["https://verity-dash.internal"])
```

Every route here is authenticated, and `Access-Control-Allow-Origin: *` cannot
carry credentials — a server that sent one anyway would be relying on the
browser to enforce the difference. `create_app` refuses `"*"` outright, and
`Vary: Origin` is always set, because a cache that saw one allowed origin's
response would otherwise serve it to every other origin.

**List routes.** `GET /v1/runs`, `GET /v1/approvals` and `GET /v1/policies`
did not exist. An approval queue could be created and decided and never
listed; `Store.list_policies` was written and called by nothing, so a policy
could only be fetched by a name you already knew.

In the dashboard, the source picker in the top bar takes a base URL, a token
and an org id. The token is stored in that browser only and never placed in a
URL — a shareable live-dashboard link would write a bearer token into browser
history, the access log, and every outbound `Referer` on the page, which is
what `SEC-APIKEY-IN-QUERY` reports about other people's contracts.

A live server fills the org, contract, environment, policy, approval, run,
audit and webhook views. It does **not** fill the test, drift, performance,
coverage or workflow views, and those render "not gathered" rather than zero:
they are outputs of a run, not server state, and a dashboard reporting
"0 failures, 100% coverage" for a service nobody has tested is worse than a
blank one and much harder to notice.

## Concurrency

`Store` keeps one SQLite connection, opened with `check_same_thread=False`, and
every request thread uses it. Access is serialised behind a re-entrant lock —
without one, two threads executing on the same connection interleave, and the
first client to make concurrent requests found out: the dashboard fetches eight
collections at once, and got intermittent `401`s for a valid token because the
token lookup came back empty. A refusal is the *lucky* symptom; the same race
returns one query's rows to another query's caller, which no log records.

It is a lock rather than a connection per thread because a `:memory:` database
lives inside its connection: per-thread connections would hand each thread a
different empty database.

`audit_append` holds that lock across its read and its insert. Each entry
hashes the previous entry's hash, so two threads that read the same tail both
link to it and the chain forks — a tamper-evident log reporting tampering on
its own writes, which is worse than no log because the next person switches the
check off.

For serious write concurrency, put a real database behind the store interface.
This is a lock, not a scalability story, and it is honest about which.

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
