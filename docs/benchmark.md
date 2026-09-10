# Benchmark against oasdiff

Both engines over the same contracts, with what each reported.

**The interesting column is the one where oasdiff found something this tool did
not.** A benchmark that only wins reads as marketing, and the reader who
notices that stops believing everything else in the repository.

## What this measures, and what it does not

Rule ids do not align across the two vocabularies -- that is what
[migrating from oasdiff](oasdiff-migration.md) is about -- so nothing here
matches finding against finding. The comparison is at **operation**
granularity: for each pair of contracts, which operations did each tool flag as
breaking?

That question has a checkable answer. It is still **not a correctness
measure**. Two tools disagreeing about an operation usually means they model
different things, and either may be right; a count is a fact about coverage,
not about being correct. Where they disagree below, the other tool's own
wording is quoted so a reader can judge rather than take a number.

Every finding from both tools is listed, at every severity, with the severity
each one assigned. An earlier version of this page compared only this tool's
`ERROR` findings against oasdiff's output and published two changes as gaps
that were not gaps -- both were reported here, one at `WARN` and one at `INFO`.
A benchmark that invents a gap is the same defect as one that hides a gap, and
more embarrassing.

Once both tools have found the same change, the interesting comparison is what
each one *called* it. `oasdiff breaking` reports only what it considers
breaking; this tool's `breaking` reports everything the diff produced, with a
severity. The two lists are deliberately *not* a two-column table: putting one
tool's n-th finding beside the other's implies they correspond, and the
vocabularies differ in granularity, so they often do not. Read them as two
accounts of the same pair of documents.

Only OpenAPI pairs are compared. oasdiff reads OpenAPI, and running it against
a `.proto` to report that it found nothing would be a rigged comparison.


## Provenance

- Run: **2026-09-10T10:10:39.379176+00:00**
- api-verity-lab: **0.2.0**
- oasdiff: module **v1.31.0**, self-reported `oasdiff version main` (`go install` builds without the version ldflag, so the binary does not know which tag it came from -- the module version is the one that was asked for)
- **Specmatic**: not run -- needs a JVM, and this machine has none. Listed rather than left out: a benchmark naming two competitors and measuring one has said something about the second by omission

## versioned

`apis/versioned/v1.yaml` against `apis/versioned/v2.yaml`

| | This tool | oasdiff |
|---|---|---|
| Breaking findings | 8 | 6 |
| Operations flagged | 4 | 3 |
| Operations both flagged | 3 | 3 |

Operations **only this tool** flagged: `GET /users/{id}`

### What each tool said

**`DELETE /users/{id}`** — 1 here, 1 from oasdiff

_This tool_

- `BRK-OP-REMOVED` (ERROR) — operation 'DELETE /users/{id}' was removed

_oasdiff_

- `api-removed-without-deprecation` (error) — api removed without deprecation

**`GET /users`** — 4 here, 3 from oasdiff

_This tool_

- `BRK-PARAM-REQUIRED` (ERROR) — parameter 'limit' (query) requiredness changed False -> True
- `BRK-CONSTRAINT-TIGHTENED` (ERROR) — request parameter 'limit': constraint 'minimum' changed 1 -> 10
- `BRK-CONSTRAINT-TIGHTENED` (ERROR) — request parameter 'limit': constraint 'maximum' changed 100 -> 50
- `BRK-ENUM-NARROWED-RESPONSE` (WARN) — response 200 body (application/json)[].role: enum changed (removed ['guest'], added [])

_oasdiff_

- `request-parameter-became-required` (error) — the `query` request parameter `limit` became required
- `request-parameter-max-decreased` (error) — for the `query` request parameter `limit`, the max was decreased from `100.00` to `50.00`
- `request-parameter-min-increased` (error) — for the `query` request parameter `limit`, the min was increased from `1.00` to `10.00`

**`GET /users/{id}`** — 1 here, 0 from oasdiff

_This tool_

- `BRK-ENUM-NARROWED-RESPONSE` (WARN) — response 200 body (application/json).role: enum changed (removed ['guest'], added [])

_oasdiff_

- nothing

**`POST /users`** — 2 here, 2 from oasdiff

_This tool_

- `BRK-ENUM-NARROWED-REQUEST` (ERROR) — request body (application/json).role: enum changed (removed ['guest'], added [])
- `BRK-REQ-BODY-REQUIRED` (ERROR) — request body requiredness changed False -> True

_oasdiff_

- `request-body-became-required` (error) — request body became required
- `request-property-enum-value-removed` (error) — removed the enum value `guest` of the request property `role`

## json-schema 2020-12

`apis/jsonschema2020/v1.yaml` against `apis/jsonschema2020/v2.yaml`

| | This tool | oasdiff |
|---|---|---|
| Breaking findings | 6 | 5 |
| Operations flagged | 1 | 1 |
| Operations both flagged | 1 | 1 |

### What each tool said

**`POST /shipments`** — 6 here, 5 from oasdiff

_This tool_

- `BRK-DEPENDENT-REQUIRED-ADDED` (ERROR) — request body (application/json): sending 'card' now also requires ['billingPostcode']
- `BRK-CONSTRAINT-TIGHTENED` (ERROR) — request body (application/json)/patternProperties/^x-: constraint 'max_length' changed None -> 64
- `BRK-CONSTRAINT-TIGHTENED` (ERROR) — request body (application/json)/if.mode: constraint 'const' changed 'road' -> 'sea'
- `BRK-RESP-CONSTRAINT-TIGHTENED` (WARN) — response 201 body (application/json).labels/propertyNames: constraint 'pattern' changed '^[a-z][a-z0-9-]*$' -> '^[a-z]+$'
- `BRK-CONTAINS-CHANGED` (WARN) — response 201 body (application/json).legs: minContains changed 1 -> 2
- `BRK-TUPLE-SHAPE-CHANGED` (ERROR) — response 201 body (application/json).route: the tuple went from 2 positional item(s) to 3

_oasdiff_

- `request-body-dependent-required-changed` (error) — the request body dependentRequired for `card` was updated: `billingPostcode added`
- `request-property-const-changed` (error) — the `mode` request property const value changed from `road` to `sea`
- `request-property-max-length-set` (error) — the `/patternProperties[^x-]/` request property's maxLength was set to `64`
- `response-property-pattern-changed` (warning) — the `labels/propertyNames/` response's property pattern was changed from `^[a-z][a-z0-9-]*$` to `^[a-z]+$` for the status `201`
- `response-property-prefix-items-added` (warning) — added `subschema #3` to the `route` response property 'prefixItems' list for the response status `201`

## crud against drift

`apis/crud/openapi.yaml` against `apis/drift/openapi.yaml`

| | This tool | oasdiff |
|---|---|---|
| Breaking findings | 12 | 5 |
| Operations flagged | 5 | 4 |
| Operations both flagged | 4 | 4 |

Operations **only this tool** flagged: `GET /reports`

### What each tool said

**`DELETE /users/{id}`** — 1 here, 1 from oasdiff

_This tool_

- `BRK-OP-REMOVED` (ERROR) — operation 'DELETE /users/{id}' was removed

_oasdiff_

- `api-removed-without-deprecation` (error) — api removed without deprecation

**`GET /reports`** — 1 here, 0 from oasdiff

_This tool_

- `BRK-OP-ADDED` (INFO) — operation 'GET /reports' was added

_oasdiff_

- nothing

**`GET /users`** — 1 here, 1 from oasdiff

_This tool_

- `BRK-OP-REMOVED` (ERROR) — operation 'GET /users' was removed

_oasdiff_

- `api-path-removed-without-deprecation` (error) — api path removed without deprecation

**`GET /users/{id}`** — 8 here, 2 from oasdiff

_This tool_

- `BRK-RESP-STATUS-REMOVED` (ERROR) — response status '404' was removed
- `BRK-HEADER-ADDED` (INFO) — response 200 header 'X-Request-Id' was added
- `BRK-RESP-FIELD-REMOVED` (ERROR) — response 200 body (application/json): field 'age' was removed
- `BRK-RESP-FIELD-REMOVED` (ERROR) — response 200 body (application/json): field 'role' was removed
- `BRK-RESP-FIELD-ADDED` (INFO) — response 200 body (application/json): field 'plan' was added
- `BRK-RESP-TYPE-CHANGED` (WARN) — response 200 body (application/json).email: format changed 'email' -> 'None'
- `BRK-RESP-CONSTRAINT-LOOSENED` (WARN) — response 200 body (application/json).name: constraint 'min_length' changed 1 -> None
- `BRK-RESP-FIELD-GUARANTEED` (INFO) — response 200 body (application/json): field 'email' became required

_oasdiff_

- `response-property-min-length-unset` (error) — the `name` response property's minLength was unset from `1` for the response status `200`
- `response-property-type-changed` (error) — the `email` response's property `format` changed from `email` to `none` for status `200`

**`POST /users`** — 1 here, 1 from oasdiff

_This tool_

- `BRK-OP-REMOVED` (ERROR) — operation 'POST /users' was removed

_oasdiff_

- `api-path-removed-without-deprecation` (error) — api path removed without deprecation

## Reading this

Across every pair, oasdiff flagged **0** operation(s) this tool did not, and this tool flagged **2** oasdiff did not.

On contracts this size that number is usually zero and it is the least informative thing on the page: both tools flag the same handful of operations, and everything interesting is *inside* them. The per-operation lists above are where the disagreement is, and an operation whose oasdiff list is longer than this tool's is where to look first.

Neither count is a score. Two tools disagreeing about a change usually means they model different things, and either may be right.
