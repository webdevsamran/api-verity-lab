---
description: >-
  Behavioural drift asks whether a service still matches itself: a field that stopped being populated, an enum value that stopped appearing, a latency that moved.
---

# Behavioural drift

Every other check in this project asks whether reality matches the document.
This one asks whether reality matches **itself** — whether the service is still
doing what it was doing last month.

```bash
apiverity drift openapi.yaml \
  --corpus april.har --against-corpus march.har \
  --include-response-bodies
```

## The cases it exists for

All three are contract-valid, which is exactly why nothing else catches them.

**An optional field that stops being populated.** `email` is optional, so a
response without it validates, `drift --corpus` reports nothing, and every
consumer that read it gets nothing. The shipped fixture pair
(`fixtures/traffic/users-march.har` and `users-april.har`) is this case, and a
test asserts that corpus drift finds *zero* findings on the later one — if that
ever stops being true, the fixture has lost its point.

**A value that stops appearing.** `status` still declares
`[pending, active, archived]` and `archived` has not been returned since the
migration. A consumer with a branch for it has dead code and no way to find
out.

**A null rate that jumps.** From 2% to 80%. Nullable is nullable, no schema
check objects, and the meaning of the response changed anyway.

## Why it mostly stays quiet

None of these is a defect on its own. A field that stops being populated may be
a feature nobody uses; a missing value may just mean nobody hit that state this
week. The value of the check is that it distinguishes a change from a
coincidence, and one that reported both would be worse than none.

So:

- **A minimum sample size, on both sides.** Three responses and then two is not
  evidence that a field was abandoned — it is two requests. The default floor
  is twenty per operation (`--min-samples` to change it), and what could *not*
  be compared is counted in the report: "nothing changed" and "we could not
  tell" are different answers, and only one of them is reassuring.
- **A rate has to move a long way.** Real traffic wobbles; a check that fires
  on noise is one people learn to ignore.
- **Every finding carries its evidence** — the observation counts on both sides
  — so a reader can judge the claim instead of trusting it.
- **High-cardinality fields are not compared by value.** Every id is new every
  time, and reporting that would be reporting that ids are ids.

## What a profile is

Per operation, per response field: how many responses were seen, in how many
the field was present, in how many it was null, and which scalar values
appeared (up to a cap). Array positions collapse — `items[0].status` and
`items[4].status` are the same field — and one response counts once however
many array elements carried the field, or a list of fifty would make a single
response look like fifty observations.

That is small enough to commit next to a contract as a baseline, which is the
point: keeping a profile is the alternative to keeping the corpus, and a corpus
of real traffic is the thing you least want to keep.

## Response bodies, and the safety model

The comparison reads response *contents*, so it requires
`--include-response-bodies`. That flag is opt-in for a reason and the reason
has not changed: a HAR of a real service holds real user data. Redaction runs
before anything reaches disk — see [the safety model](safety-model.md) — and
the profile itself stores value *sets* under a cardinality cap rather than the
values of every response, which is why a profile is safe to commit where a
corpus is not.
