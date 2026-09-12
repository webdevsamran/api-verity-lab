---
description: >-
  Record real traffic into a HAR corpus with `apiverity capture`, then run drift detection against it instead of against a synthetic probe.
---

# Recording real traffic

```bash
apiverity capture --target https://staging.example.com --out corpus.har
# point a client at the address it prints; ctrl-c to stop
apiverity drift openapi.yaml --corpus corpus.har
```

[`drift --corpus`](capability-status.md) and `infer` both want real traffic, and
until now the only way to get some was to already have a HAR from somewhere
else. This records one.

## Redaction happens before the write

A recorder that wrote the HAR and then sanitized it would have already put an
`Authorization` header on disk — and on a crash between the two, left it there.

So headers, query strings, request URLs and bodies are redacted **in memory**,
and the entry appended to the log is the redacted one. The unredacted response
still goes back to the client, because the client asked for it and this is a
proxy.

The URL is rebuilt from the redacted parameters rather than carried through.
Redacting `queryString` and leaving `request.url` alone writes the credential
into the file anyway, one field over — which is exactly what the first version
of this did, and what the test that reads the file back caught.

A JSON body gets two passes: the field-name rules, then the patterns over each
string **value**. The second catches a credential sitting inside an opaque
string — a request body echoed back, a log line carried in a field — which
nothing keyed on field names can see into. Over the values rather than the
serialized document, because in serialized form `{"password": "x"}` nested in a
string reads as `password\": \"x`, and the escaping is what hides it.

### What redaction cannot catch

An unlabelled secret in free text: a bare token with nothing beside it saying
what it is.

Redaction here is rule-based, not clairvoyant. A recorder claiming otherwise is
the claim that gets a credential committed. **Read what you captured before you
commit it.**

## What it refuses to be

**An open relay.** Every request goes to the one `--target` the run named.

**Reachable from the network.** It binds `127.0.0.1` and refuses any other
address without `--i-know-this-is-exposed`. An unauthenticated recording proxy
on a routable address is a credential collector somebody else can point
wherever they like — and this one writes what it sees to a file.

**A TLS interceptor.** There is no `CONNECT`. Tunnelling would either pass TLS
through opaquely, recording nothing, or require issuing certificates for hosts
this process does not own. It answers `405` and says which.

## What it admits it did not record

A corpus that silently drops what it could not handle has gaps that read as
facts about the service. Every skip is counted, named in the JSON output, and
written into the HAR's own `log.comment` so it survives the file:

| Skip | Why |
|---|---|
| `oversized_request` / `oversized_response` | over `--max-body-bytes` (default 256 kB) |
| `binary_request` / `binary_response` | a content type with no useful `text` in a HAR |
| `upstream_failed` | the target never answered; the client got a `502` |
| `after_limit` | `--max-entries` was reached and traffic kept arriving |

`--max-entries` is a hard cap, not a threshold: asking for two gives two. The
poll loop notices a limit a tenth of a second later, by which time more requests
have arrived, so the cap is enforced where the entry is appended — and what
arrived after it is counted rather than silently absent.

## An empty corpus is still written

Nobody sent anything through: that is a fact about the run. A missing file reads
as a crash.

## Options

| | |
|---|---|
| `--target URL` | the one upstream to forward to (required) |
| `--out FILE` | where to write the HAR (required) |
| `--host` / `--port` | where to listen (default `127.0.0.1`, any free port) |
| `--duration SECONDS` | stop after this long |
| `--max-entries N` | record at most this many, then stop |
| `--max-body-bytes N` | bodies above this are noted as absent, with the reason |
| `--no-response-bodies` | request bodies only — narrows what the corpus is usable for, since `drift --corpus` compares responses |
