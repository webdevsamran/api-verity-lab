---
description: >-
  Turn `severity: ERROR` into the names of the services that break, by evaluating a breaking change against a registry of declared consumers.
---

# Blast radius: who breaks, not just what

```bash
apiverity breaking v1.yaml v2.yaml --consumers consumers.yaml
```

## The problem with a correct finding

```
[ERROR] BRK-OP-REMOVED  operation 'DELETE /users/{id}' was removed
```

That is accurate, and the person reading it still has to go and find out whose
build fails on Monday. The answer lives in a file most teams do not have: which
services call which operations.

A consumer registry is that file.

```yaml
version: 1
complete: false          # see below — this word does real work
consumers:
  - name: checkout-service
    team: payments
    contact: "#payments"
    uses:
      - operation: "GET /users"
  - name: mobile-v3
    team: mobile
    uses:
      - operation: "GET /users"
      - operation: "DELETE /users/{id}"
  - name: support-agent
    uses:
      - tool: search_orders     # sugar for the key an MCP manifest produces
```

With it, the same finding reads:

```
[ERROR] BRK-OP-REMOVED  operation 'DELETE /users/{id}' was removed — affects mobile-v3
```

and the artifact carries a `blast_radius` object: findings per consumer, teams,
contacts, and the operations each one is exposed to. `--summary` names them in
the pull-request text.

## The downgrade this will not do by default

The obvious next feature is to soften a finding nobody consumes. A removal with
no registered caller genuinely is not the same event as one three services
depend on.

But a registry is incomplete the moment somebody writes a client without
telling anyone, which is most of the time. "No consumer listed" then reads as
"no consumer exists", and downgrading on that is exactly how a breaking change
ships.

So softening needs two separate acts:

1. the registry declares `complete: true`, taking responsibility for the claim;
2. the caller passes `--severity-by-consumers`.

A finding softened this way says so, and names the file that made the claim:

```
[WARN] BRK-OP-REMOVED  operation 'POST /reports' was removed — no registered
       consumer calls this, and consumers.yaml declares itself complete, so it
       is reported at WARN
```

Without both, the registry only ever adds information. It never removes
severity.

## Two findings about the registry itself

`CONSUMER-UNKNOWN-OPERATION` (ERROR) fires when an entry names an operation
neither side of the comparison declares — a typo, or a path that was renamed
long ago. Such an entry can never match a finding, so the registry looks like
coverage and provides none, and with `complete: true` it would soften findings
for the very operation the author meant to protect.

The check runs against **both** contracts, old and new. A consumer using an
operation the new version removed is the case this whole feature exists to
report; checking against the new contract alone would flag every one of them as
a mistake in the registry, which is backwards.

`unclaimed_operations` in the blast radius lists operations with a breaking
finding and no registered consumer. That is where an incomplete registry hurts,
and a reader should see the gap rather than have to infer it from an absence.

## In the dashboard

The **Blast Radius** page under Team draws the same result as a bipartite
graph: the operations with a breaking finding on the left, the consumers that
call them on the right, an edge for each dependency. Selecting either side dims
the rest rather than hiding it, because the shape of the whole graph is the
context that makes one highlighted path mean anything.

The drawing is `aria-hidden`, and every number in it is repeated in two real
tables underneath — one keyed by operation, one by consumer, with the team and
the contact to reach. A graph that can only be read by looking at it is a graph
half the audience cannot read.

The page states whether the registry it read declared itself complete, in those
words. Without that sentence, an operation with no consumer beside it reads as
"nobody calls this" when it may only mean "nobody wrote it down" — and those
two lead to opposite decisions.

## What it does not do

**Field granularity.** A consumer can declare the operations it calls, not the
response fields it reads, so `BRK-RESP-FIELD-REMOVED` is attributed to everyone
who calls the operation rather than to whoever reads that field. The reason is
mechanical: `Change` carries the field name only inside a human-readable
description, and matching on that would mean parsing a message. When the differ
carries a pointer, this can.

**Discovery.** Nothing here finds consumers for you. The registry is written by
people, which is why `complete` is a claim someone has to make rather than
something the tool infers.
