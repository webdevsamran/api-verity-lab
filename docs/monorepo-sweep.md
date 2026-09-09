# Sweeping a monorepo, and who owns what

```bash
apiverity sweep .
apiverity sweep . --base ../main-worktree
```

## The gap

A repository with twelve services has twelve contract gates and no view across
them. Each pipeline says whether its own contract is fine; nothing says how
many of the twelve are failing, or which team should be told.

`sweep` walks the tree once and answers both.

```
0 of 6 contract(s) failing.
  @org/orders: 2 error(s), 1 warning(s) across 3 contract(s)
  (unowned): 0 error(s), 4 warning(s) across 1 contract(s)
```

The JSON carries the whole thing: a record per contract with its protocol,
title, operation count, findings and owners, plus a `by_owner` rollup and an
`unowned` list.

## Discovery is deep, on purpose

`apiverity init` looks in the conventional directories at the top of a project
and stops at the first that yields anything — that is how it learns the
project's convention. `sweep` cannot do that. Monorepo contracts live at
`services/<name>/api/openapi.yaml`, and none of those directory names appear at
the root, so a sweep that stopped at the top would report a clean tree it never
finished reading.

So `sweep` walks everything, skipping `node_modules`, `.git`, virtualenvs and
build output, and `--limit` is the backstop.

**An empty tree is a usage error, not a clean sweep.** Zero contracts found and
zero contracts broken read identically in a summary line, and only one of them
is good news.

**A contract that will not load is reported, not skipped.** Skipping it would
make the sweep read cleaner than the repository is. Malformed YAML raises an
exception that is not a `ValueError`, so one bad file used to end the whole run
with "internal error" — the least useful thing a sweep can say. Now it becomes
one `unreadable` row and the other ninety-nine services still get checked.

## Ownership comes from CODEOWNERS

Not from a second file. A second ownership file goes stale the week after it is
written, and the repository already answers this question.

One rule is worth stating because getting it backwards silently assigns the
wrong team: **the last matching pattern wins**, not the most specific one.

```
*                   @org/platform
/api/               @org/payments
api/orders/*.yaml   @org/orders @alice
```

`api/users.yaml` belongs to `@org/payments`, not `@org/platform`. A reader
scanning top-down for the first match would conclude the opposite.

Patterns are gitignore-shaped: a leading `/` anchors to the root, a trailing
`/` covers a directory and everything under it, a pattern with no slash matches
at any depth, `**` spans directories and a bare `*` does not. All three
locations GitHub looks in are read: `.github/CODEOWNERS`, `CODEOWNERS`,
`docs/CODEOWNERS`.

A path no rule matches is reported as unowned. Guessing an owner from a
directory name would produce a plausible team that never agreed to anything.

## Comparing a whole repository against a base

```bash
git worktree add ../main-worktree origin/main
apiverity sweep . --base ../main-worktree
```

Each contract is compared with the file at the same relative path under
`--base`, so a monorepo gets one breaking-change verdict instead of one per
service. A contract with no counterpart is recorded as new, with
`compared: null` and a note — "no findings" for something that was never
compared is not the same claim, and a rollup that conflated them would count a
brand-new service as a passing one.

## Routing

`by_owner` is the payload a notifier needs: who, which contracts, how many
errors. Delivery is not built in — the self-hosted server already has signed
webhooks, and adding a second, unsigned notification path next to it would be
the wrong place to put an integration.
