---
description: >-
  Turn a sweep into one contract-health document per team, on a schedule -- routing is the difference between an alert and a muted channel.
---

# Scheduled governance reports

`apiverity digest` turns a [sweep](monorepo-sweep.md) into one contract-health
document per team.

```bash
apiverity sweep . --json > this-week.json
apiverity digest this-week.json --since last-week.json --out digests/
```

`sweep` answers the platform team's question — which contracts are failing and
whose they are — as a single document covering everything. A digest cuts the
same data the other way, so each team receives only what it owns and can be
sent it on a schedule.

Teams come from the sweep's own ownership resolution (`CODEOWNERS`), so a
digest cannot disagree with the sweep it was built from about who owns what.

## What each document holds

| Section | What it means |
|---|---|
| Newly failing | failing now, not failing in the previous sweep |
| Still failing | failing in both — the standing debt |
| Fixed | failing before; this sweep looked again and found it clean |
| No longer swept | in the previous sweep and absent from this one |
| Would not load | a contract that will not parse |
| New findings | findings present now and not in the previous sweep |

## The comparison that produces a false all-clear

Two sweeps are two walks of a tree, and the tree moves underneath them. Last
week found forty contracts; this week's `--limit` was lower, or a service moved
to another repository, or the discovery glob changed. Twelve contracts are
simply absent from the second walk.

Differenced naively, that is **twelve contracts fixed** — the report a platform
team most wants to read and least should believe.

So a contract is *fixed* only when this sweep looked at it and found no errors.
A contract absent from this sweep goes in **No longer swept**, which says what
actually happened: nobody looked.

The same applies to a team that lost every contract. Its digest is still
produced, because the week a whole service vanished from the sweep should not
be the quietest week of the year.

## The first digest compares nothing

Without `--since` there is no previous sweep, so the document reports the
current state and says so:

```
16 contract(s), 2 failing, 3 error(s) -- first digest, nothing compared
```

Nothing is labelled *newly* failing or *still* failing, because both are claims
about a week nobody looked at. Pass this run's artifact as `--since` next time
to get a comparison.

## Why this repeats itself and `monitor` does not

[`apiverity monitor`](monitoring.md) reports only transitions: a five-minute
check that re-prints the standing state is muted inside a week.

A weekly digest is the opposite. Surfacing standing debt *is* its job — a
contract that has been failing for three weeks belongs in all three digests. So
a standing failure is never "quiet" here, however old it is.

What *is* dropped is a team with nothing at all to report: no failures, no
movement, nothing unreadable. Those teams are **named** in the run's `quiet`
list rather than silently omitted, because "four teams had nothing to report"
and "four teams were missing from the sweep" are different claims.

## Unowned contracts

Contracts no `CODEOWNERS` rule matches are gathered under `(unowned)` and
reported as a team. A per-team digest that quietly dropped them would hide
exactly the contracts nobody will be asked about — the ones most likely to rot.

## Sending it

`--out DIR` writes one markdown file per speaking team, named after the team
with the characters a filename cannot hold replaced (`@org/orders` →
`org-orders.md`).

The JSON artifact's per-team `findings` key holds what *appeared*, which is the
key [`apiverity notify`](ci.md) reads — so routing a digest sends a team the
new thing rather than the standing state. On a first digest that key is empty:
the baseline document is for reading, not for paging.

```yaml
# .github/workflows/weekly-digest.yml
on:
  schedule:
    - cron: "0 9 * * MON"
jobs:
  digest:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: apiverity sweep . --json > this-week.json
      - run: apiverity digest this-week.json --since last-week.json --out digests/ --json
      - uses: actions/upload-artifact@v4
        with:
          name: contract-health
          path: digests/
```

Keep `this-week.json` somewhere the next run can read it — an artifact, a
branch, a bucket. Without it every digest is a first digest.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | nothing newly failing |
| `1` | at least one contract started failing since the previous sweep |
| `2` | the artifact could not be read, or is not a sweep |

Standing failures do **not** fail the run. A weekly report that exits non-zero
every week is a weekly report nobody runs.
