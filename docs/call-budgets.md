# Call budgets: how much an agent may use an interface

```bash
apiverity budget calls.json --budget budgets.yaml
apiverity budget traffic.har --budget budgets.yaml --spec openapi.yaml
```

## The gap this fills

The most-cited worry about agent traffic is not that an agent calls the wrong
endpoint — it is that it calls the right one ten thousand times.

No contract in any of the seven formats this engine reads has a field for how
often anything may be called. A rate limit lives in a gateway config, if it
exists at all, and the contract an agent was generated from is silent about it.
A budget file is that missing declaration, and this command checks observed
traffic against it.

```yaml
version: 1
window: 1h                # default for every limit below
deny_by_default: false    # traffic with no limit is a note, not a failure

limits:
  - tool: delete_order      # sugar for the operation key `tool delete_order`
    max_calls: 0            # never, under any circumstances
  - tool: search_orders
    max_calls: 100
    window: 1m
  - operation: "GET /users/{id}"
    max_calls: 5000
```

## Windows slide

"No more than 100 calls an hour" means no hour contains 101 calls — not that no
*clock* hour does. Tumbling buckets miss a burst that straddles a boundary, and
that is exactly the shape a runaway agent makes: five calls between 12:00:50
and 12:01:30 land as two and three in clock minutes and never trip a
per-minute limit.

So the check scans sorted timestamps for the busiest window of the declared
length, and reports where it started:

```
[ERROR] BUDGET-EXCEEDED  'tool search_orders' allows 3 call(s) per 1m and
        reached 5 in the window beginning 2026-03-01T12:00:50+00:00
```

This works because `import_har` carries `startedDateTime` through — it used to
drop it. A call with no timestamp cannot be placed in any window, so it is
counted and reported (`BUDGET-UNDATED-CALLS`) and the peak is stated as a lower
bound rather than quietly including or excluding it.

## Where the calls come from

| Input | Needs `--spec` | Why |
|---|---|---|
| A HAR | yes | a HAR records `/orders/42`; without the contract, `/orders/41` and `/orders/42` would be budgeted separately and no limit would ever trip |
| A call log | no | it already names the operation or tool |

A call log is a list an agent (or its host) writes:

```json
[
  {"tool": "search_orders", "at": "2026-03-01T12:00:50Z"},
  {"operation": "GET /users/{id}", "at": "2026-03-01T12:00:51Z"}
]
```

## Findings

| Rule | Severity | Fires on |
|---|---|---|
| `BUDGET-OPERATION-UNKNOWN` | ERROR | a limit naming an operation the contract does not declare |
| `BUDGET-FORBIDDEN` | ERROR | an operation budgeted at zero calls that was called |
| `BUDGET-EXCEEDED` | ERROR | the busiest window exceeded the allowance |
| `BUDGET-UNBUDGETED` | ERROR with `deny_by_default`, otherwise INFO | traffic no limit covers |
| `BUDGET-UNDATED-CALLS` | WARN | calls that could not be placed in a window |
| `BUDGET-UNUSED` | INFO | a limit nothing in this traffic exercised |

`BUDGET-OPERATION-UNKNOWN` is the one worth having most. A limit whose
operation key is a typo can never match anything, so the file looks like
protection, and every run it is supposed to constrain passes cleanly. Same
reasoning as `CONFIG-RULE-UNKNOWN`: a setting nobody reads is worse than a
setting nobody wrote. It needs `--spec`; without a contract to check against,
no such claim is made.

`BUDGET-UNUSED` exists for the opposite reason. A limit that was never
exercised has not been shown to hold, and a report that stayed silent about it
would read as if it had.

`deny_by_default` is off out of the box. A first budget covers the dangerous
operations and nothing else, and failing on everything not yet listed is how a
budget file gets deleted in week two.
