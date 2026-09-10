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

The second most common answer is "we have a Postman collection", so `infer`
reads one of those too:

```bash
apiverity infer orders.postman_collection.json -o draft.yaml
```

Detected on content rather than on the extension, because both are `.json` and
a HAR named `collection.json` is a file somebody will hand this.

The output loads back through every other command in this tool, so the path
from "no contract" to "a contract gate in CI" is one file and a review.

## Reading a Postman collection

A collection goes through the *same* inference engine as a HAR — read into the
same entry shape, folded by the same path templating, held to the same
`required` and enum thresholds. Two inference paths would be two sets of
decisions about when a field is required, and they would disagree.

### A collection is not traffic

A HAR is a recording: those requests happened, in that order, at those times. A
collection is a **set of requests somebody saved**, and a saved response is an
example somebody pasted — possibly years ago, possibly by hand, possibly from
staging.

Every threshold above means something weaker about examples than about
observations, so the draft says which it read. Its first sentence says *saved*
request(s) rather than *recorded* ones, it carries
`x-apiverity-source: postman-collection`, and its description spells out that
these are requests somebody saved and not traffic anybody observed. No
timestamps are invented: a collection records none, and a fabricated one would
put a window in the draft's own description that nobody observed.

### What is read

Nested folders to any depth, `request.method`, `request.url` in both the string
and object forms the schema allows, headers, `body.raw` and `body.urlencoded`,
and saved responses with their status code and body. A query parameter or
header marked `disabled` is **not** carried — it is one somebody deliberately
turned off, and declaring it would put a parameter in the draft that the
collection says not to send.

### What is not, and where it goes

| Construct | Why | Where it is reported |
|---|---|---|
| `body.formdata`, `body.file` | A multipart upload's shape is not a JSON schema, and the file it names is not in the collection | `provenance.skipped`, naming the request |
| `body.graphql` | One POST to one endpoint; drafting REST operations from it would describe an API that does not exist. GraphQL SDL is read directly instead | the same |
| `auth`, pre-request and test scripts | Scripts compute values at send time; what one would have produced is not in the file | the same |
| A `{{variable}}` with no value | Guessing would draft an operation at a path nobody serves | `provenance.unresolved_variables`, with the URL as written |
| A request with no saved response | The endpoint is real; only its response shape is missing | `provenance.requests_without_a_saved_response` |

The request itself always survives a body mode that cannot be read. The
endpoint exists even when its payload cannot be modelled, and dropping it would
remove an operation from the draft — a draft missing a third of an API because
those requests used form bodies looks like an API with a third fewer endpoints.

Verified against the Postman Collection Format v2.1.0 schema, read 2026-09-10
at [schema.postman.com](https://schema.postman.com/json/collection/v2.1.0/collection.json).

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
