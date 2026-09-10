# Load shapes

`apiverity regression` measures every operation a fixed number of times.
`apiverity regression --shape` drives **one** operation at a **declared arrival
rate** for a declared duration.

```bash
apiverity regression openapi.yaml --base-url https://staging.example.com \
  --shape 'ramp:60s@1..20' --operation 'GET /users'
```

```text
GET /users  ramp 60s at 1/s -> 20/s (even arrivals, seed 0)
  target: https://staging.example.com/users
  scheduled 631, sent 631, errors 0
  requested 1/s, offered 10.5/s over 60.0s (60.2s including the drain)
  p50 41.2ms   p95 118.7ms   p99 402.1ms
  statuses: {'2xx': 629, '5xx': 2}
```

## Open loop, which is the point

`regression` and `regression --curve` are **closed loop**: N workers each send
a request, wait for the answer, and send the next. Offered load falls as the
service slows. That is the right instrument for "how does it behave at
concurrency 16".

`--shape` is **open loop**: a request goes out when it is due, whether or not
earlier ones have come back. That is the only way to ask "what happens at 200
requests a second" — under a closed loop a service that stalls simply receives
less traffic, and the queue never builds.

Neither replaces the other, and a report that confused them would be describing
a different experiment from the one it ran.

## The shapes

| Spec | What it does |
|---|---|
| `constant:30s@10` | Ten requests a second for thirty seconds |
| `ramp:60s@1..20` | One a second climbing to twenty over a minute |
| `spike:60s@10x6@50%` | Ten a second, with a burst of sixty halfway through |
| `soak:600s@5` | Five a second for ten minutes |

Add `+poisson` for exponentially distributed inter-arrival times rather than
even spacing — real traffic clusters, and a service that copes with a metronome
does not always cope with the same mean arriving in bursts. Add `+seed=7` to
pin the arrival process, so a Poisson run is reproducible.

A spec that cannot be read is refused rather than defaulted. A generator that
quietly ran `constant` when the operator typed `ramp` would produce a report
describing a shape that never happened.

## What the run says about itself

**`achieved_rps` against the rate you asked for**, and **`max_late_ms`**: how
far behind its own schedule the generator fell at worst. When it falls further
behind than one scheduling step, the run says so in as many words:

```text
  WARNING: this generator fell up to 3140ms behind its own schedule. The
  offered load was not the profile above -- lower the rate, or drive it from
  somewhere closer to the target.
```

That is not a verdict on the service. It is a statement about the run: with
requests going out three seconds after they were due, the latencies above
describe a load nobody asked for. k6 draws the same distinction with
`dropped_iterations`, and a load report that hid it would be quotable and
wrong.

The offered rate is measured over the **dispatch window**, not the total. An
open-loop profile controls when requests *go out*; how long the last responses
take to drain is the service's business, and dividing by the total would report
two thirds of the rate a two-second profile actually offered when its tail took
another second — which reads as a generator that fell behind and is nothing of
the kind. The run reports both windows.

"Far enough behind" is one scheduling step, 50 ms, rather than a round
wall-clock figure: 250 ms is five slots at twenty requests a second and a
fiftieth of one at four, so a fixed number would mean something different at
every rate.

Nothing is dropped here — `scheduled == sent + errors` always holds. A
generator that silently discarded a backlog would report a clean run of a
profile it did not execute.

## What it will not do without being told

**One operation, named.** `--shape` requires `--operation`. A rate is stated
for one endpoint; applying `constant:60s@50` to a forty-operation contract
means two thousand requests a second at a target somebody asked fifty of.

**A concrete path.** An operation declared at `/users/{id}` is refused with a
pointer to `--path /users/42`. There is nothing here that knows a real id, and
filling one in would send thousands of requests at a guess.

**Reads, unless you say otherwise.** A non-`GET`/`HEAD`/`OPTIONS` operation
needs `--include-mutations`, because `POST /orders` at fifty a second writes to
the target fifty times a second. See the [safety model](safety-model.md).

## History

This module existed, with tests, before any of the above. Two things were wrong
with it.

No command reached it — `--profile` on the command line is the *severity*
profile, and no flag anywhere took a load shape. And `execute` computed the
schedule and threw every offset away, firing requests back to back as fast as
the transport returned: a ramp, a spike, a soak and a Poisson arrival process
all produced the same run, differing only in how many requests it contained.
The shape, which is the entire content of a load profile, did nothing.

`capacity_search` was deleted at the same time. It swept concurrency levels
against a transport the *caller* supplied, so it never sent a request and its
numbers were whatever the caller's model said. `regression --curve` does that
job against a real target.
