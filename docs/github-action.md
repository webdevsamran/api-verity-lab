---
description: >-
  Pin, configure and publish the api-verity-lab GitHub Action: every input and output, and what the Marketplace listing needs.
---

# The GitHub Action

`action.yml` at the root of this repository is a composite action, and it is
the thing GitHub offers to publish to the Marketplace.

## Pin the major tag

`v0` moves to each release, so this is the reference to use:

```yaml
- uses: webdevsamran/api-verity-lab@v0
```

`release.yml` moves `v0` after it creates the release, and
`scripts/check_action_metadata.py --check` holds every documented `uses:` line
to the major in `pyproject.toml` — so the tag the docs name and the tag the
release creates cannot disagree.

Pin the exact release instead — `@v0.3.0` — if you would rather take upgrades
deliberately. Pin a commit SHA if your policy requires it; `.github/workflows`
in this repository pins every third-party action that way.

## An action, not the reusable workflow

Both exist and they are not interchangeable:

| | What you get |
|---|---|
| `uses: webdevsamran/api-verity-lab@v0` | A **step** inside a job you own: your runner, your matrix, your checkout, your steps before and after. |
| `uses: webdevsamran/api-verity-lab/.github/workflows/api-verity.yml@v0` | A whole **job**. Less to write, and you cannot put your own steps around it. |

The README advertised the first for a long time while only the second existed,
so anyone who copied the line got `Can't find 'action.yml'`. Both are real now,
and `ci.yml` runs the action on every push to prove it.
<!-- generated:action -->

`API Verity contract gate` — Validate API contracts changed in a pull request, diff them against the base branch, and fail on breaking changes. Works on OpenAPI, AsyncAPI, GraphQL and gRPC contracts through one engine and one result format.

```yaml
- uses: actions/checkout@v5
  with: { fetch-depth: 0 }   # the diff needs the base revision
- uses: webdevsamran/api-verity-lab@v0
```

## Inputs

| Input | Default | What it does |
|---|---|---|
| `spec-paths` | _(empty)_ | Newline- or space-separated contract paths to check. Leave empty to auto-detect contracts changed in this pull request under `spec-dirs`. |
| `spec-dirs` | `^(fixtures/apis\|openapi\|specs\|contracts)/` | Extended regular expression matching directories that hold contracts, used only when `spec-paths` is empty. An allowlist by design: a denylist leaks, and once handed `.pre-commit-config.yaml` to an OpenAPI loader it blocked every merge in this repository. |
| `base-ref` | _(empty)_ | Git ref to diff against. Defaults to the pull request's base branch. |
| `fail-on` | `error` | Lowest severity that fails the step: `error`, `warn`, or `never`. `never` reports without failing, for adopting the gate on an existing API. |
| `check-semver` | `true` | Also check that the version bump matches the change (`true`/`false`). |
| `python-version` | `3.12` | Python used to run apiverity. 3.11 is the floor. |
| `install-from` | `action` | Where to install apiverity from. `action` (default) installs the exact revision the caller pinned with `uses:`, so the tool and this action can never disagree about what a flag means. `pypi` installs the published distribution -- use it once you want to pin the tool independently of the action. |
| `version` | _(empty)_ | Version specifier when `install-from: pypi`, e.g. `==0.2.0`. Empty installs the latest. |
| `working-directory` | `.` | Directory to run in, for monorepos. |
| `comment` | `false` | Post the findings as a pull request comment, editing the previous one rather than adding another. Off by default: it writes to the pull request, and a step that does that without being asked is a surprise. Requires `permissions: pull-requests: write` on the calling job and a `pull_request` event. |
| `github-token` | `${{ github.token }}` | Token used to post the comment. Defaults to the job's `github.token`, which is enough for a pull request in the same repository. A fork's `pull_request` event gets a read-only token, so the comment is skipped there with a notice rather than a failure. |

## Outputs

| Output | What it carries |
|---|---|
| `result` | `pass`, `findings`, or `error`. |
| `specs-checked` | Number of contracts the gate actually examined. |
| `findings-count` | Findings at or above `fail-on`. |
| `comment-url` | API URL of the comment that was posted or updated. Empty when commenting was off, or when the token could not write to the pull request. |
| `artifacts-dir` | Directory of per-contract `result-v1` JSON artifacts. Upload it, or read it in a later step -- the schema is published at schemas/result-v1.schema.json and versioned. |

Branding for the Marketplace listing: `git-pull-request` on `blue`.

<!-- /generated:action -->

## Publishing it to the Marketplace

Deliberately not automated. Listing software under an account's name is that
account owner's to do, and a workflow with a token that could do it is a
workflow with more access than it needs.

Everything the listing requires is in the repository and checked on every
build — root `action.yml`, branding GitHub accepts, a description, a
description on every input and output. What is left is three steps in the
web interface:

1. **Accept the GitHub Marketplace Developer Agreement.** Once, per account.
2. **Cut a release.** Push a `v*` tag; `release.yml` builds it, creates the
   release, and moves `v0`.
3. **On that release, tick _Publish this Action to the GitHub Marketplace_**,
   then choose a primary and secondary category. *Continuous integration* and
   *Code quality* are the ones that fit.

GitHub validates the metadata at that point and refuses the listing if any of
it is wrong. That check runs after the tag exists, which is the worst moment
to discover a typo in a colour name — which is why
`scripts/check_action_metadata.py` runs first.

Two things it cannot check from here, stated rather than implied:

- **The name must be unique across the Marketplace**, and must not collide
  with an existing GitHub account name. Only GitHub knows that, at publish
  time.
- **The icon must be a Feather icon GitHub accepts.** The colours are eight
  values and the refused icons are a published list, so both are checked. The
  ~280 accepted icon names are not vendored here: writing them from memory and
  calling them the Feather set would be provenance this repository does not
  have, and a list that is subtly short rejects a valid icon.
