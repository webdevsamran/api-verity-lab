# Drafting a contract from traffic

```bash
apiverity infer traffic.har -o draft.yaml --title "Orders API"
```

## Why this exists

The most common answer to "run the contract gate on this API" is "we do not
have a contract." Every capability in this project starts from a document that
does not exist, and writing one by hand for a service with ninety endpoints is
exactly why it never gets written.

Recorded traffic is the next best evidence. `apiverity infer` reads a HAR and
produces an OpenAPI 3.1 document describing **what was observed** — which is a
different thing from what the API supports, and the document says so wherever
it matters.

The output loads back through every other command in this tool, so the path
from "no contract" to "a contract gate in CI" is one file and a review.

## Three places this could lie, and does not

### Required

A field present in all four observed responses is not a field the API
guarantees. A property is marked `required` only when it appeared in **every**
sample *and* there were at least three of them. Below that it stays optional.

Every schema carries `x-apiverity-samples`, so a reader can weigh the claim and
disagree with it:

```yaml
properties:
  created_at:
    type: string
    format: date-time
    x-apiverity-samples: 3
required: [created_at, email, id, status]
x-apiverity-samples: 3
```

### Enums

Three responses with `status: "open"` do not make `open` the only value. Enum
inference is **off** unless you pass `--infer-enums`, and even then it needs
eight samples and at most twelve distinct values.

A fabricated constraint is worse than an absent one: it turns a valid request
into a reported violation, and the report will look authoritative.

### Path parameters

`/users/42` and `/users/43` are one operation. `/users/me` and
`/users/settings` are two. Collapsing too eagerly invents an operation nobody
serves; collapsing too late produces a hundred operations and no signal.

A segment becomes a parameter only on evidence — either every sibling value at
that position looks like an identifier (UUID, integer, long hex, `cus_…`), or
there are enough distinct values that a literal set is not credible. The reason
is recorded per operation:

```yaml
description: 'Inferred from 3 recorded request(s). Path templating: 4 distinct
  values at this position; a literal set that large is not credible.'
```

A single identifier with no siblings is left alone: one observation is not a
pattern. And `/users/me` survives untouched next to three UUIDs, because it
does not read as an identifier.

The parameter is named from its parent segment — `/orders/{orderId}` — which is
predictable rather than clever.

## Other honesty

- Two shapes for one field are reported as two: `type: [integer, string]`.
  That is a fact about the API, not something to smooth over by picking one.
- A format is recorded only when every sample agrees on it.
- A status observed with no body is still a declared response, described as
  "Observed, with no response body recorded" rather than as an empty schema.
- An empty corpus is a usage error, not an empty API. A document with no paths
  would read as "this service has none."

## The label

The document is marked in three places so nobody downstream mistakes it for
something a person wrote:

- `x-apiverity-inferred: true` at the top level;
- `(inferred draft)` in the title;
- a description saying how many requests it came from, over what window, and
  that it should be read by someone who knows the service before it is
  published.

Redaction runs first: `import_har` sanitises headers, query parameters and
bodies before any of this sees them, so a drafted contract does not carry
credentials out of a recorded session.
