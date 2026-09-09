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

Exit code `1` fails the job when ERROR-severity findings exist — that is the
release gate. Use `--severity-override` to tune strictness per repo.

## Artifacts
- `apiverity report <bundle> --format junit` → JUnit test reporting.
- `apiverity report <bundle> --format sarif` → upload with
  `github/codeql-action/upload-sarif` or `actions/upload-artifact`.
- `apiverity report <bundle> --format markdown` → paste into the PR summary
  (keep it to one comment; update it on push instead of adding new ones).

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
