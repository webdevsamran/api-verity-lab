---
description: >-
  Synthetic monitoring: run any api-verity-lab command on a schedule against staging or production, and alert on what changed since the last run.
---

# Synthetic monitoring

`apiverity monitor` runs any other command on a schedule and reports what
**changed** since the last run.

```bash
apiverity monitor --state .apiverity/staging.json -- \
  drift openapi.yaml --base-url https://staging.example.com
```

The `--` works the way it does in [`watch`](#relationship-to-watch): everything
after it is the command to run.

## Why a diff and not a report

A cron entry that runs `drift` every five minutes and posts the result produces
288 identical reports a day. People mute the channel inside a week, and the run
that finally differs arrives in a muted channel.

So the output is the transitions:

| Field | What it holds |
|---|---|
| `findings` | the findings that **appeared** on this run |
| `resolved` | the findings that stopped being reported |
| `unchanged_count` | how many were already known and still are |
| `message_changed` | known findings whose text moved but whose identity did not |
| `carried_forward` | known findings whose operation could not be measured |
| `unobserved` | the operations that could not be measured |
| `flapping` | keys that have crossed more than once, with their counts |
| `inconclusive` | set when the run established nothing |
| `baseline` | true on the first run against a state file |

`findings` is deliberately the *new* ones, because that is the key
[`apiverity notify`](ci.md) reads. Piping the standing state into a team's
channel every five minutes is the muting.

```bash
apiverity monitor --state .apiverity/staging.json --out transitions.json -- \
  drift openapi.yaml --base-url https://staging.example.com
apiverity notify transitions.json --routes routes.yaml --send
```

## The first run alerts on nothing

Point this at a service that has run for three years and it will find findings
that are not today's problem. The first run against a new `--state` file
records them as a **baseline** and reports none of them as new — and says so:

```
summary: baseline recorded: 14 finding(s) known, none reported as new
```

The second run is the first that can report anything.

## The run that could not look

This is the failure the command exists to avoid.

An operation that could not be probed produces no findings about that
operation. Differenced naively against a previous run that had three, that
reads as **three findings resolved** — the shape of good news, arriving at the
exact moment the service stopped answering.

`drift` and `ghosts` already state this per operation, in the finding itself.
`GHOST-UNREACHABLE` reads *"this run establishes nothing about whether it is
still served"*. The monitor acts on those rules rather than ignoring them:

* an operation named by an unreachable finding is **carried forward** — what
  was known about it stays known, and nothing about it is called resolved;
* every other operation is differenced normally, so one dead endpoint does not
  silence the other thirty-nine;
* a run where the command reports measuring **nothing** is `inconclusive`, exits
  `3`, and names the reason.

That last one is read from the count the command reports for itself
(`operations_checked`, `probed`) — never guessed from the findings. "Every
finding is an unreachable one" is equally the shape of a healthy API with one
dead endpoint and of a total outage, and the two must not be conflated.

A command that reports no count at all gets no outage detection rather than a
guessed one.

## What makes two findings the same finding

`(rule_id, operation_key)`.

Not the message. A message carries a p95, a sample count, an observed status —
values that move between runs — and keying on it would report the whole set as
resolved-and-reappeared every five minutes.

The consequence is stated rather than hidden: a finding whose message changed
while its rule and operation did not is **not** a transition. It stays in the
unchanged set, with the latest message, and `message_changed` counts them.

## Flapping

A finding that appears and resolves on alternate runs is one alert every five
minutes in both directions. Each crossing increments a counter kept in the
state file, and `flapping` names the keys that have crossed more than once.

Nothing here suppresses an alert on its own. Whether to page on an unstable
finding is a policy decision; the count is what makes it possible to take one.

## The state file

`--state` is required. Without it every run would report the whole world as
new.

It is bound to the command that created it. Pointing two different commands at
one file makes each one's findings read as the other's full turnover — every
finding resolved, every finding new, on every alternate run — so the second one
is refused:

```
error: staging.json holds the state of `drift openapi.yaml --base-url https://staging`,
not `validate openapi.yaml`. Use a separate --state file per command.
```

A state file written by a different version of the format is also refused
rather than silently reset: starting over would alert on every existing finding
as though it were new. Delete it to take a fresh baseline.

Commit it or keep it on the monitoring host — either works. It is sorted JSON,
so two runs produce a readable diff.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | nothing new, or a baseline was recorded |
| `1` | something appeared |
| `2` | usage: no command, a mismatched state file, an unreadable one |
| `3` | the run was inconclusive |
| `4` | the report could not be written |

Exit `1` is the gate signal. Exit `3` is worth alerting on too — a monitor that
went quiet because it could not connect is the one you find out about last.

## Running it

One run per invocation is the cron shape:

```cron
*/5 * * * * apiverity monitor --state /var/lib/apiverity/staging.json -- \
  drift /etc/apiverity/openapi.yaml --base-url https://staging.example.com
```

`--runs N` with `--interval SECONDS` keeps one process alive across several
runs instead, which is useful for a container with no scheduler:

```bash
apiverity monitor --state s.json --runs 288 --interval 300 -- \
  drift openapi.yaml --base-url https://staging.example.com
```

Each run's summary goes to stderr as it happens; the last run's report is the
one printed to stdout and written to `--out`.

## Relationship to `watch`

The same shape, a different trigger.

| | trigger | output |
|---|---|---|
| [`watch`](ci.md) | a file changed | the command's own report |
| `monitor` | the clock | what changed since the previous run |

`watch` is for the machine you are editing on. `monitor` is for the one nobody
is looking at.

## Relationship to `drift --baseline`

`drift --baseline` compares one run against a file you saved deliberately, and
answers *"is anything wrong that was not wrong when we agreed this was the
baseline?"* — a pull-request question.

`monitor` compares each run against the one before it, and answers *"did
anything change in the last five minutes?"* — an operations question. It
advances its own state on every run, which is why it needs the unreachable
handling and `drift --baseline` does not.

They compose: a monitor can run `drift --baseline` and report the transitions
in what that comparison produced.
