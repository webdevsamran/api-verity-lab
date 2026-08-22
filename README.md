# api-verity-lab

**Unified API contract governance, breaking-change analysis, schema-driven
testing, runtime drift detection, traffic replay and performance regression
for OpenAPI, GraphQL and gRPC.**

One modular, local-first platform that connects spec diffing, fuzzing,
drift detection, mocking and performance gates through **one data model,
one CLI, one result format, one plugin system and one frontend**.

> Original creator / founder / lead maintainer: **[@webdevsamran](https://github.com/webdevsamran)**
>
> ⚠️ Example/demo runs in this repository are clearly labeled synthetic data.
> The tool only ever sends traffic to base URLs you explicitly provide.

---

## The problem

Teams stitch together separate tools for spec diffing, contract testing,
fuzzing, drift detection, mocking and performance budgets. Each has its own
result format, its own CI wiring and its own mental model — so findings never
compose: you can't ask "which endpoints are both under-tested *and* drifting?"

api-verity-lab answers ten questions from one place:

| Question | Command |
|---|---|
| What changed between API versions? | `apiverity diff old.yaml new.yaml` |
| Is it breaking, risky or safe? | `apiverity breaking` |
| Was semantic versioning respected? | `apiverity breaking --check-semver` |
| Does the running API match its contract? | `apiverity drift` |
| Can schema-derived edge cases break it? | `apiverity test` |
| Do multi-step workflows fail? | `apiverity workflow run` |
| Can sanitized traffic be replayed safely? | `apiverity replay` |
| Did latency/error rate regress? | `apiverity regression` |
| Which endpoints lack coverage? | `apiverity coverage` |
| Can CI block breaking changes before release? | GitHub Action (included) |

## 60-second quickstart

```bash
pip install api-verity-lab          # or: pip install -e ".[dev]" from a clone

# 1. Validate a contract
apiverity validate fixtures/apis/crud/openapi.yaml

# 2. Diff two versions and detect breaking changes
apiverity diff fixtures/apis/versioned/v1.yaml fixtures/apis/versioned/v2.yaml --json
apiverity breaking fixtures/apis/versioned/v1.yaml fixtures/apis/versioned/v2.yaml

# 3. Enforce semver policy
apiverity breaking fixtures/apis/versioned/v1.yaml fixtures/apis/versioned/v2.yaml \
    --old-version 1.2.0 --new-version 1.3.0 --check-semver

# 4. Spin up the deterministic mock and test against it
apiverity mock fixtures/apis/crud/openapi.yaml --port 8090 &
apiverity test fixtures/apis/crud/openapi.yaml --base-url http://127.0.0.1:8090

# 5. Run an authored workflow (create → get → update → delete)
apiverity workflow run fixtures/workflows/crud-lifecycle.yaml

# 6. Detect runtime drift
apiverity drift fixtures/apis/drift/openapi.yaml --base-url http://127.0.0.1:8090

# 7. Gate performance
apiverity baseline fixtures/apis/crud/openapi.yaml --base-url http://127.0.0.1:8090 -o baseline.json
apiverity regression fixtures/apis/crud/openapi.yaml --base-url http://127.0.0.1:8090 \
    --baseline baseline.json --policy "GET /users p95 <= 250ms"
```

Every command supports `--json`, stable exit codes (`0` ok, `1` findings at/above
threshold, `2` usage error, `3` target unreachable, `4` internal error).

## A diff example

```console
$ apiverity diff v1.yaml v2.yaml
CHG-OPERATION-REMOVED-1   DELETE /users/{id}        removed operation
CHG-PARAM-REQUIREDNESS-2  GET /users                query param 'limit' became required
CHG-RESPONSE-SCHEMA-3     GET /users/{id}           response 200 field 'email' removed
CHG-ENUM-4                POST /users               request body field 'role' enum narrowed
```

## A breaking rule (direction-aware)

Removing a field from a **response** breaks consumers; adding an optional
field to a **request** does not:

```yaml
# BRK-RESP-FIELD-REMOVED (ERROR)
GET /users/{id}:
  responses:
    "200":
      # v1 had: id, name, email   →   v2 has: id, name
      email: removed   # ← ERROR: clients reading .email will break
```

The catalog ships ~30 rules across ERROR/WARN/INFO with per-rule severity
overrides — see `docs/rules.md` or run `apiverity rules`.

## A generated failure

Schema-driven tests derive edge cases from your constraints and minimize
failures to small reproductions:

```jsonc
// apiverity test --json (excerpt)
{
  "case": "POST /users negative: age violates exclusiveMinimum(0)",
  "request": { "method": "POST", "path": "/users", "body": {"name": "a", "age": -1} },
  "expected": "4XX",
  "actual": { "status": 500 },
  "finding": "server returned 5xx for invalid input",
  "reproduction": "curl -X POST http://127.0.0.1:8090/users -d '{\"name\":\"a\",\"age\":-1}'"
}
```

## Workflows

Stateful sequences are authored explicitly (never auto-generated destructively):

```yaml
# fixtures/workflows/crud-lifecycle.yaml
name: crud-lifecycle
allowed_hosts: ["http://127.0.0.1"]
steps:
  - name: create
    request: { method: POST, path: /users, body: {"name": "alice"} }
    extract: { user_id: "$.id" }
    assert: { status: 201 }
  - name: get
    request: { method: GET, path: "/users/{user_id}" }
    assert: { status: 200, jsonpath: { "$.name": "alice" } }
  - name: delete
    request: { method: DELETE, path: "/users/{user_id}" }
    assert: { status: [200, 204] }
cleanup:
  - request: { method: DELETE, path: "/users/{user_id}" }
```

## Drift

Compare what the API actually returns against what it declared:

```console
$ apiverity drift openapi.yaml --base-url http://localhost:8080
DRIFT-STATUS      GET /reports     returned 503, not declared in contract
DRIFT-FIELD       GET /users/{id}  response field 'email' missing (required)
DRIFT-UNDECLARED  GET /users/{id}  undocumented response field 'internal_score'
```

## Performance budgets

```bash
apiverity baseline ... -o perf-baseline.json
apiverity regression ... --baseline perf-baseline.json \
    --policy "GET /users p95 <= 250ms" --policy "POST /users error_rate <= 1%"
```

Stable exit codes make this a CI gate; bundles record p50/p90/p95/p99,
throughput, timeouts and error rates.

## Architecture & plugins

See [ARCHITECTURE.md](ARCHITECTURE.md). Six versioned plugin entry points:

```
apiverity.specs · apiverity.rules · apiverity.checks
apiverity.generators · apiverity.exporters · apiverity.transports
```

Spec support matrix: OpenAPI 3.0/3.1 ✅ full · GraphQL SDL ✅ foundation ·
gRPC proto ✅ foundation · AsyncAPI 📋 planned.

## Frontend

A React + TypeScript app under [`web/`](web/) renders real generated fixture
data: side-by-side diff review, breaking-change cards, endpoint tree, drift
tables, latency charts, coverage charts, shareable filters and downloadable
reports. Serve results locally with `apiverity serve <bundle>`.

## Development

```bash
pip install -e ".[dev]"
pre-commit install
pytest && cd web && npm install && npm run build
```

See [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md),
[ROADMAP.md](ROADMAP.md) and [docs/](docs/).

## License & citation

Apache-2.0 — see [LICENSE](LICENSE). Cite via [CITATION.cff](CITATION.cff).
Prior art that inspired the design is credited in ARCHITECTURE.md; no code
is copied from other projects.