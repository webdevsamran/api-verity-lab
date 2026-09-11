# Merge queues and required checks

## The gap a pull-request gate leaves

A contract gate that runs on `pull_request` proves something about **that
branch merged into the base as it was when the check ran**. It proves nothing
about what actually merges.

Two pull requests, each individually safe:

- **A** removes the last declared consumer of `GET /users.legacy_id` from
  `consumers.yaml`. Nothing breaks: the field is still there.
- **B** removes `legacy_id` from the contract. Nothing breaks *in B's view*:
  the blast radius says one consumer, and the gate is configured to warn rather
  than block on a single known consumer.

Both pass. Both merge. The field is gone and the consumer that used it was
removed from the registry by a different pull request, so nothing ever
evaluated the combination.

The merge queue is the only place that combination is built before it is
`main`. So the gate has to run there:

```yaml
on:
  pull_request:
    branches: [main]
  merge_group:
```

Both, not one. The merge queue is the *last* gate; finding out there is finding
out after review.

## The base ref is different, and that is not cosmetic

A `merge_group` event has no `github.base_ref` — it is not a pull request. The
base is `github.event.merge_group.base_ref`, and it arrives fully qualified
(`refs/heads/main`).

The action reads it, strips the prefix, and diffs against it. Before that it
reached its "no base ref to diff against" branch and exited 1, which meant it
could not be a required check in a merge queue at all — safe, in that it failed
rather than passing vacuously, and useless.

If you find no base ref at all, the action still refuses. A gate that cannot
find a base and proceeds anyway is a gate that passes.

## Required checks match by name, byte for byte

Branch protection stores required checks as strings. Rename a job and the
required check keeps waiting for a name nothing reports — the pull request
hangs forever, or, if somebody drops the requirement to unblock it, merges with
nothing having run.

This repository's required jobs are pinned in
`tests/unit/test_required_checks.py`:

```
python · platform-matrix · schema-validation · frontend · sbom
```

The test fails in **both** directions. A required job that disappears from
`ci.yml` is the hang above. A job added to `ci.yml` and not listed is a check
somebody has to decide about — required, or advisory — rather than one that
quietly is neither.

## What does not run in a merge queue

The PR comment. There is no pull request to comment on, and a step that tried
would fail the gate for a reason that has nothing to do with the contract — so
it stays scoped to `github.event_name == 'pull_request'`.

The findings are still in the job summary and the uploaded artifact, which is
where you look when a queued merge is rejected.

## Configuring it

Merge queue settings live in branch protection: require a merge queue, and
require the checks above. Nothing in this repository can configure that for
you — it is a setting on the repository, and a tool that claimed to have set it
would be claiming something it cannot see.
