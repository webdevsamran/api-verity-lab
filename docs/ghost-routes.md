---
description: >-
  Ghost routes: endpoints that were deleted from the contract and still answer in production. Found by probing what the old contract declared and the new one does not.
---

# Ghost routes: still answering, no longer declared

```bash
apiverity ghosts openapi.yaml --was v1.yaml --base-url https://api.internal
apiverity ghosts openapi.yaml --corpus traffic.har --base-url https://api.internal
```

## The question nothing else asks

Every other check here asks whether the server does what the contract says.
This asks the opposite: **does the server still do something the contract
stopped saying?**

An endpoint is removed from the document in one pull request and from the
deployment in another, and the second one is the one that gets forgotten.
Nothing fails in between. The docs are correct, the tests pass, the contract
gate is green — and the route keeps answering anyone who remembers the URL. It
is the shape behind a long tail of real incidents: an old admin path, a v1 that
was "retired", a debug handler nobody grepped for.

Almost nothing looks for this, because looking means comparing against
something that is deliberately absent.

## Where candidates come from

Two sources, both evidence:

| Flag | Candidates |
|---|---|
| `--was previous.yaml` | operations that contract declared and the current one does not |
| `--corpus traffic.har` | paths real requests used that the current contract does not match |

Both can be given; a route named by both is probed once, keeping the first
reason it came up.

**Nothing is guessed.** This never enumerates likely paths against a host,
because a tool that does that is a scanner, and
[`SAFETY_MODEL.md`](safety-model.md) §1 is explicit targets only. With no
candidates the command exits `2` rather than `0`: nothing was asked, so nothing
was established, and a green run there would be the most misleading output in
the tool.

## Safe methods only

A removed `DELETE /users/{id}` cannot be probed by sending a DELETE. Only
`GET`, `HEAD` and `OPTIONS` go out. Anything else is reported as
`GHOST-NOT-PROBED` with the method that would have been needed — an audit that
quietly skips the destructive half of its input is worse than one that says so.

A templated path is filled from the contract that declared it, using the same
seeded generator the fuzzer uses, so `/users/{id}` reaches the wire as a
concrete path rather than a literal brace.

## Findings

| Rule | Severity | Meaning |
|---|---|---|
| `GHOST-ROUTE` | ERROR | the route answered, and no contract declares it |
| `GHOST-PATH-ALIVE` | WARN | `405`: the method is gone, the path is not — something is still routed there |
| `GHOST-GONE` | INFO | `404` or `410` — the contract and the deployment agree |
| `GHOST-NOT-PROBED` | INFO | a write, not sent |
| `GHOST-UNREACHABLE` | INFO | the probe did not complete, so this run establishes nothing |

`GHOST-GONE` exists because the good news is the answer to an audit question.
"We checked twelve retired endpoints and all twelve are gone" is a record worth
keeping, and a report that only spoke when something was wrong could not
produce it. `410` is distinguished from `404` on purpose: one is absent, the
other is deliberately absent.
