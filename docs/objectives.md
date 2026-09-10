# Objectives the contract declares

A performance budget used to be a flag:

```bash
apiverity regression spec.yaml --base-url … --policy "GET /users p95 <= 250ms"
```

That number lives in whoever's CI file typed it, which is not where the promise
lives. The promise is in the contract — the thing consumers actually read — and
a budget that disagrees with it is a budget nobody agreed to.

```yaml
paths:
  /users:
    get:
      x-slo:
        p95_ms: 250
        error_rate_pct: 1
        bytes_p95: 262144
        availability: 99.9
        window: 30d
```

```bash
apiverity regression spec.yaml --base-url … --slo
```

`x-` because no version of OpenAPI has a field for this, and
`Operation.extensions` already carries every `x-*` key verbatim for exactly
this reason.

## The distinction this whole feature is built around

**An SLO is a promise over a window. A run is a sample of it.**

"99.9% of requests under 250 ms over 30 days" is not something any load run can
confirm or refute — not this one, not a longer one. Twenty samples against a
mock say something about twenty samples against a mock.

So the finding is called `SLO-RUN-EXCEEDS-OBJECTIVE`, its message says *this
run measured*, and its hint says how many samples that was. A tool that printed
"SLO breached" off twenty requests would be making exactly the claim its own
documentation says it cannot, and the first reader who checked would stop
believing the rest of the output.

## What is measured

| Objective | Compared against |
|---|---|
| `p50_ms`, `p90_ms`, `p95_ms`, `p99_ms` | the measured percentile |
| `error_rate_pct` | the measured error rate |
| `bytes_p50`, `bytes_p95`, `bytes_max` | the measured response size |

Every one is a ceiling.

## What is not, and why

| Objective | Why |
|---|---|
| `availability`, `uptime_pct` | A run measures the requests it made and cannot see the ones it did not. A figure computed here would be a fabrication with a decimal point on it. |
| `window` | The period the objective is promised over. Carried into the report so it can be quoted; no run is long enough to evaluate it. |

These are **reported**, at INFO, rather than ignored — silence about an
objective somebody wrote down reads as a pass.

## The checks

| Rule | When |
|---|---|
| `SLO-MALFORMED` | `p95_ms: "250ms"` — looks declared, reads as declared in a review, compared against nothing. Worse than a missing objective. |
| `SLO-UNKNOWN-OBJECTIVE` | An objective this tool does not measure. A promise nobody checks. |
| `SLO-NOT-MEASURABLE` | One of the two above, named rather than dropped. |
| `SLO-UNDECLARED` | An operation with no objective, in a contract where others have one. INFO: an operation nobody promised anything about is not a defect. |
| `SLO-NOT-MEASURED` | The objective exists and the run measured nothing for it — including when every request was refused or timed out. A p95 of a connection timeout is not a latency, and reporting it against an objective would blame the service for being unreachable. |
| `SLO-RUN-EXCEEDS-OBJECTIVE` | This run measured past the declared value. |

The first four run under `apiverity validate`, because that is where a contract
gets read and a check nobody invokes is a check nobody has. The last two need a
measurement, so they run under `regression --slo`.

`--slo` is off by default. Measuring against a promise the caller did not ask to
be measured against would fail builds over an `x-slo` block somebody added as
documentation.

## Noise

`SLO-UNDECLARED` is silent on a contract that declares no objectives anywhere —
that is a choice, not an oversight, and a finding per operation for it would be
a wall of warnings saying one thing. Same discipline as
[`SEC-RATE-LIMIT-NO-429`](check-rules.md).
