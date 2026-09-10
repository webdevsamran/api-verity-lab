# CI Integration

There are three ways to wire this up, in increasing order of how much you want
to control. Pick the first one that fits.

## 1. The action (a step in a job you own)

```yaml
name: api-verity
on: pull_request
permissions:
  contents: read
jobs:
  contract:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
        with: { fetch-depth: 0 }          # the diff needs the base branch
      - uses: webdevsamran/api-verity-lab@v1
```

That auto-detects contracts changed in the pull request, validates each one,
diffs it against the base branch, checks the version bump, and fails on
ERROR-severity findings.

`fetch-depth: 0` is not optional — with a shallow clone there is no base
revision to diff against, and the gate degrades to validation only.

Everything is an input:

| Input | Default | What it does |
|---|---|---|
| `spec-paths` | *(auto-detect)* | Explicit contracts to check, instead of detecting changes |
| `spec-dirs` | `^(fixtures/apis\|openapi\|specs\|contracts)/` | Where contracts live. An allowlist by design — see below |
| `base-ref` | the PR base | What to diff against |
| `fail-on` | `error` | `error`, `warn`, or `never` to report without failing |
| `check-semver` | `true` | Also check the version bump matches the change |
| `python-version` | `3.12` | 3.11 is the floor |
| `install-from` | `action` | `action` installs the revision you pinned with `uses:`; `pypi` installs the published distribution |
| `version` | *(latest)* | Version specifier when `install-from: pypi` |
| `working-directory` | `.` | For monorepos |

and it sets four outputs — `result` (`pass`/`findings`/`error`),
`specs-checked`, `findings-count`, and `artifacts-dir`, a directory of
per-contract [`result-v1`](../schemas/result-v1.schema.json) JSON:

```yaml
      - uses: webdevsamran/api-verity-lab@v1
        id: gate
        with: { fail-on: warn }
      - if: always()
        run: echo "${{ steps.gate.outputs.findings-count }} findings"
      - if: always()
        uses: actions/upload-artifact@v5
        with:
          name: contract-findings
          path: ${{ steps.gate.outputs.artifacts-dir }}
```

**`spec-dirs` is an allowlist, deliberately.** A denylist leaks: every new
root-level YAML a tool adds would be handed to the OpenAPI loader. This
repository learned that when `.pre-commit-config.yaml` reached the loader and
blocked every merge.

Each artifact carries a plain-English summary — a verdict, what changed
grouped and counted, and the version to release it as — rendered from
deterministic templates with no model call, so it is the same on every run:

> **This change is breaking.** (1.2.0 → 2.0.0) 6 findings at ERROR across 9 changes.
>
> **What changed**
> - Constraints were tightened, so previously valid input now fails (2)
> - Operations were removed
>
> **What to do**
> - Release this as **2.0.0**, not a patch.
> - Or make it additive: deprecate with a sunset date instead of removing.

Read it out of the artifact with `jq -r '.summary.markdown'` and post it
wherever your team reads.

**Adopting on an existing API?** Start with `fail-on: never`. You get the full
report and the artifacts on every pull request without blocking anyone, which
is how you find out what your contract history actually contains before you
turn the gate on.

## 2. The reusable workflow (a whole job)

If you want the PR-comment experience — one concise summary comment, updated
on push rather than re-posted:

```yaml
jobs:
  contract:
    uses: webdevsamran/api-verity-lab/.github/workflows/api-verity.yml@v1
    permissions:
      contents: read
      pull-requests: write
```

This is a *workflow*, not the action above, and the two are not
interchangeable: a reusable workflow is the whole job and brings its own
runner, checkout and Python, so you cannot put your own steps around it. The
action is a step inside a job you control. Use the workflow when you want the
comment, the action when you want the control.

## 3. Wiring the CLI yourself

```yaml
name: api-verity
on:
  pull_request:
    paths: ["**/openapi*.yaml", "**/openapi*.json"]
permissions:
  contents: read
jobs:
  contract:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0 }
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -e .
      - name: Validate PR contract
        run: apiverity validate api/openapi.yaml
      - name: Diff vs base
        run: |
          git fetch origin ${{ github.base_ref }}
          apiverity diff <(git show origin/${{ github.base_ref }}:api/openapi.yaml) api/openapi.yaml --json > diff.json
      - name: Breaking gate
        run: apiverity breaking <(git show origin/${{ github.base_ref }}:api/openapi.yaml) api/openapi.yaml --check-semver
```

Exit code `1` fails the job when findings reach the threshold — that is the
release gate. The threshold and the per-rule severities come from
`.apiverity.yaml` when there is one, and `--severity-override` still wins for a
single run:

```yaml
version: 1
profile: balanced       # strict | balanced | advisory
fail_on: never          # report without blocking, while adopting the gate
severity_overrides:
  BRK-DEPRECATION-ADDED: INFO
suppressions: .apiverity-suppressions.json
suppression_max_days: 90          # how far ahead an `expires` date may sit
suppression_require_approver: false
```

`profile` is a starting position; everything else in the file, and every flag
on the command line, takes precedence over it. `strict` raises every WARN in
the catalogue to ERROR, `balanced` is the catalogue as shipped, and `advisory`
reports without blocking. `apiverity rules --profiles` prints the three and
what each one does; `apiverity rules` prints every rule at the severity *this*
run would apply, not the shipped one. The table is generated into
[the rule catalogue](rule-catalog.md#severity-profiles).

`fail_on` takes `error` (the default), `warn`, or `never`. A gate that fails on
its first run against an API that already has history gets removed rather than
adopted, which is what `never` is for.

## Suppressions

A suppressions file silences a finding *from the gate*, not from the record.
The suppressed findings are listed in the artifact under `suppressions`, so a
gate that dropped a finding on the say-so of a file is still one somebody can
audit.

An entry has to be **justified** and **bounded**, and an entry that is neither
does not suppress:

```json
{
  "suppressions": [
    {
      "rule_id": "BRK-RESP-FIELD-REMOVED",
      "operation_key": "GET /things",
      "owner": "platform-team",
      "reason": "both consumers confirmed on 2026-05-20; the field goes in 3.0",
      "expires": "2026-06-15",
      "approved_by": "sre-lead"
    }
  ]
}
```

- **`owner` and `reason`** are what make it justified. Without either, the
  entry does not suppress and a `SUPPRESSION-INCOMPLETE` warning names the
  missing field.
- **`expires`** is what makes it bounded, and it has a maximum: **90 days**,
  or whatever `suppression_max_days` says. `"expires": "2099-01-01"` satisfies
  "each one needs an expiry" and is a permanent ignore with a date on it, so it
  is treated as one and does not suppress either.
- **`approved_by`** is optional unless the project sets
  `suppression_require_approver: true`. The owner carries the work; the
  approver accepted the risk of not doing it yet.
- An **expiry that has passed** becomes a `SUPPRESSION-EXPIRED` warning and
  stops suppressing. Re-justify it with a new date and a reason that says what
  changed -- extending an expiry without one is the same as never having set
  it.
- Omitting **`operation_key`** silences the rule across every operation. That
  is allowed and it still suppresses; it also emits `SUPPRESSION-UNSCOPED` at
  INFO, because a rule silenced contract-wide will not fire on the operation
  somebody adds next month either.

Failing closed is deliberate. An entry that does not qualify leaves the finding
it named in the run at its own severity, so the build stays red and the warning
beside it says which line of the file to open. `apiverity explain
SUPPRESSION-INCOMPLETE` prints the same thing without a run.

An ignore-list nobody can audit and nobody has to revisit is the thing this
format exists to avoid, and until these rules were enforced,
`{"rule_id": "BRK-RESP-FIELD-REMOVED"}` on its own was a valid file that
switched the rule off for good.


`--no-config` ignores the file entirely, for a run that must not inherit
project policy.

## Artifacts
- `apiverity report <bundle> --format junit` → JUnit test reporting.
- `apiverity report <bundle> --format sarif` → upload with
  `github/codeql-action/upload-sarif` or `actions/upload-artifact`.
- `apiverity report <bundle> --format markdown` → paste into the PR summary.
- `apiverity report <bundle> --format pr-comment` → a review comment that
  leads with the non-breaking route to the same change. See below.

### The pull request comment

`--format pr-comment` is not the markdown report with a different heading. Two
things make a review comment a different document, and both follow from one
observation: **a gate that only says no gets switched off.**

The non-breaking alternative leads. Every rule in the catalogue has one, and
the objection is the evidence for it rather than the point of the comment. Run
`breaking --suggest-fix` so the artifact carries them; without that flag the
comment still renders, with the objection alone.

Findings are grouped by **rule**, not by severity. Forty rows saying a required
field was added, each followed by the same paragraph, is noise; one group of
forty with one instruction is a review comment.

The body opens with `<!-- apiverity:pr-comment:v1 -->` so a workflow can find
its own previous comment and edit it. One comment per pull request, not one per
push — a bot with twelve comments on a busy branch gets muted, and a muted gate
is the same as no gate. It also stays inside GitHub's 65,536-character limit
and says how many findings it dropped to get there, because silent truncation
reads as "that was everything".

The bundled action does all of this with one input:

```yaml
permissions:
  contents: read
  pull-requests: write     # required for `comment: true`

jobs:
  contracts:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
        with:
          fetch-depth: 0
      - uses: webdevsamran/api-verity-lab@v1
        with:
          comment: "true"
```

The comment step runs even when the gate failed — that is the pull request it
is most useful on — and a clear run replaces yesterday's red comment rather
than leaving it standing. A pull request from a fork gets a read-only token, so
there the step skips with a notice instead of failing a run whose findings were
already reported.

### Telling the right people

A gate that posts everything to one #api-alerts channel produces a channel
that is muted within a month, and after that the gate is decorative.
`apiverity notify` routes a result artifact's findings to the teams they
concern, using two things this project already reads:

```bash
apiverity breaking old.yaml new.yaml --json > findings.json
apiverity notify findings.json --routes routes.yaml --consumers consumers.yaml
```

```yaml
# routes.yaml
routes:
  "@platform-team": https://hooks.slack.com/services/...
  checkout: {url: "https://outlook.office.com/webhook/...", kind: teams}
```

**CODEOWNERS** says who owns the contract file; the **consumer registry** says
who calls the operation. They are two different audiences and they do not want
the same message: an owner needs to know what they changed, a consumer needs to
know what is about to break for them. Only ERROR findings reach a consumer — a
warning is a conversation the owning team has with itself, and forwarding every
one of them to five other teams recreates the channel this replaces.

Findings that reached nobody are listed under `unrouted`, with which kind of
gap it was: no CODEOWNERS entry, or an owner with no route configured. A
routing layer that drops those silently is worse than the shared channel.

**Nothing is sent without `--send`.** A tool that posts to a team's channel as
a side effect of being run has done something the person running it did not ask
for — the same reason `replay` and `--invoke-tool` are dry by default.

SARIF results carry `region` line and column information from the spec, so
GitHub annotates the changed line rather than the repository, and
`partialFingerprints` keep an alert attached to the same problem when the
numbers in its message change.

---

# Performance gates

A latency gate that fires on noise gets disabled, and a gate that has been
loosened until it stops firing detects nothing. This page is about landing
between the two.

## The short version

```bash
apiverity regression openapi.yaml \
  --base-url http://localhost:8080 \
  --iterations 100 \
  --warmup 20 \
  --baseline .apiverity/baseline.json \
  --tolerance 25 \
  --tolerance error_rate=0
```

Exit codes: `0` no violations, `1` violations found, `2` bad usage, `3`
target unreachable. Inconclusive notes do not affect the exit code — see
below.

## Why a percentage on its own is not enough

`p95 <= previous * 1.2` compares two point estimates and says nothing about
how much either would move on a rerun. With 20 requests a p95 is a single
observation near the tail of the distribution; on a shared CI runner it
routinely moves by tens of percent between identical runs.

Measured here, against a fixed local target, 10 consecutive runs compared to
the same baseline — every "regressed" verdict is a false positive by
construction, because nothing changed:

| | asserted regressions |
|---|---|
| point estimates only | **22** |
| with the interval guard | **8** (plus 14 reported as inconclusive) |

So a change has to clear two bars before it is called a regression:

1. it exceeds the tolerance for that metric, and
2. the two 95% confidence intervals do not overlap.

When the intervals overlap, the run is reported as **inconclusive** rather
than passed. That distinction is the point: a gate that silently passes a
change it did not have the samples to evaluate is indistinguishable from one
that checked and found nothing.

Intervals come from a seeded bootstrap for percentiles and throughput, and a
Wilson score interval for the error rate. Seeded, so the same samples always
produce the same verdict.

## Warmup

`--warmup N` sends N requests before measuring and discards them, along with
any errors they produce. The first requests to a cold target measure TLS
handshakes, connection-pool setup, lazy imports, an empty cache and a cold
JIT — none of which is the thing under test, and all of which land in the tail
where p95 and p99 live.

The report keeps the two counts apart:

- `requests` — everything sent, warmup included
- `samples` — what the percentiles were computed from

so `p95` over 60 samples after 20 warmup requests is not mistakable for `p95`
over 80 cold ones.

**How much:** enough for the connection pool to reach steady state. 10–20 is
usually plenty for a local HTTP target. If p50 and p95 are far apart on a
target you know to be uniform, that gap is warmup, not the service.

## Noise floors

These are what we measure on this project's own CI, against a local target on
a GitHub-hosted `ubuntu-latest` runner. They are a starting point for choosing
a tolerance, not a guarantee — a runner under different load will differ, and
the honest way to get your own numbers is to run the gate against an unchanged
service a few times and look at the spread.

| Metric | Typical run-to-run spread | Suggested tolerance |
|---|---|---|
| `p50` | 5–15% | 25% |
| `p90` | 10–25% | 30% |
| `p95` | 15–35% | 35% |
| `p99` | 25–60% | 50%, or do not gate on it |
| `throughput` | 10–20% | 25% |
| `error_rate` | — | `0` |

`p99` on 100 samples is the single slowest request or two. It is a legitimate
thing to *record* and a poor thing to *gate*; if you want tail coverage that
holds still, raise `--iterations` rather than tightening the tolerance.

`error_rate=0` is the one metric worth gating hard. A new 5xx is a fact, not a
measurement, and it should not need a tolerance to be believed. New errors
against a clean baseline are reported regardless of tolerance.

## Per-metric tolerance

`--tolerance` is repeatable and takes either a bare percentage for everything
or `metric=percentage` for one metric:

```bash
--tolerance 30            # everything
--tolerance p95=20        # ...except p95
--tolerance error_rate=0  # ...and errors, which get no slack at all
```

A bare number sets the metrics that are not named explicitly, so the order of
the three lines above does not matter. Known metrics: `p50`, `p90`, `p95`,
`p99`, `throughput`, `error_rate`. An unknown one is an error listing the real
ones rather than a silently ignored flag.

## Choosing `--iterations`

The interval width scales roughly with `1/sqrt(n)`, so detecting a smaller
change costs quadratically more requests.

| Smallest change you want to detect | Rough iterations needed |
|---|---|
| 50% | 20 |
| 25% | 60 |
| 10% | 300 |
| 5% | 1000+ |

If the gate keeps reporting *inconclusive* on a change you believe is real,
that is the tool telling you the run is too short to decide — raise
`--iterations`, do not lower the tolerance. Lowering the tolerance does not
make the measurement better; it makes the gate assert things it cannot
support.

## Recording a baseline

```bash
apiverity regression openapi.yaml --base-url "$URL" \
  --iterations 100 --warmup 20 --json > run.json
python -c "import json,sys; json.dump(json.load(open('run.json'))['report'], open('.apiverity/baseline.json','w'), indent=2)"
```

Record it on the same runner class you will compare on. A baseline taken on a
developer laptop and compared against a CI container measures the hardware,
not the change.

Baselines written before confidence intervals existed still work: when either
side has no interval, the tolerance check stands alone.

## A worked CI job

```yaml
- name: Performance gate
  run: |
    apiverity regression openapi.yaml \
      --base-url http://localhost:8080 \
      --iterations 100 --warmup 20 \
      --baseline .apiverity/baseline.json \
      --tolerance 30 --tolerance p95=25 --tolerance error_rate=0 \
      --json > perf.json
  continue-on-error: false

- name: Upload measurements
  if: always()
  uses: actions/upload-artifact@v4
  with:
    name: performance
    path: perf.json
```

Upload the JSON even when the step fails — the intervals and sample counts in
it are what tell you whether a red gate found a regression or simply ran out
of samples.

## Adopting a drift gate on an API that already drifts

Point `drift` at a service that has been running for three years and it reports
forty findings. All true, none of them today's problem. The gate goes red on
the first run, somebody sets it to advisory, and it never comes back.

Record what is already wrong, once:

```bash
apiverity drift openapi.yaml --corpus traffic.har --save-baseline drift-baseline.json
git add drift-baseline.json
```

Then fail only on what is newly wrong:

```bash
apiverity drift openapi.yaml --corpus traffic.har --baseline drift-baseline.json
```

Known findings stay in the artifact with `state: known` -- silenced for the
gate, not deleted from the report -- and the run names anything in the baseline
that has since been fixed, because that half is what makes the other half
credible. Works with any of the four detection modes: a baseline from a live
probe and one from a recorded corpus are the same kind of file.

