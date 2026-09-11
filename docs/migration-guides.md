# Migration guides

A breaking-change finding says *what* broke. It does not say what to do
instead — and the person who knows that is the API owner, who very often wrote
it down next to the operation.

```yaml
/users/{id}:
  get:
    deprecated: true
    x-deprecation:
      announced: "2026-01-15"
      sunset: "2027-01-01"
      guide: https://docs.example.com/migrating-to-v2
      impact: mobile clients pinned below 3.4 will need a release
```

`apiverity breaking` now carries that to the reader looking at the objection:

```
**What to do**

- Release this behind a major version bump.
- Or make it additive: deprecate with a sunset date instead of removing…
- `GET /users/{id}` has a migration guide: https://docs.example.com/migrating-to-v2
  — mobile clients pinned below 3.4 will need a release
```

It is on every finding about that operation under `metadata.migration_guide`,
and listed once per operation under `migration_guides` in the artifact.
Eleven findings about one removed operation should not print the same link
eleven times.

## It comes from the *old* contract

The operation being broken is the one in the old document. A guide added to the
new contract in the same change that breaks people is the author's note to
themselves; the guide that helps a consumer is the one that was already
published when they wrote against it.

If the new contract adds a guide and the old one had none, the finding carries
nothing — and [`LIFECYCLE-DEPRECATED-NO-GUIDANCE`](check-rules.md) is the rule
that objects to that in advance, which is the point at which it is still cheap
to fix.

## Spellings

Both the structured block and the flat extensions in common use:

| | |
|---|---|
| `x-deprecation` | an object with `announced` / `sunset` / `guide` / `impact`, or a bare date |
| `x-deprecated` | the same object, other spelling |
| `x-migration`, `x-migration-guide`, `x-deprecation-link`, `x-sunset-link` | just the guide |
| `x-sunset`, `x-sunset-date` | just the date |

The lifecycle rules read all of them. They previously read only the flat keys,
which meant a contract using the structured block was told it *"names no
retirement date"* and *"points nowhere"* — two published rules firing on a
contract that satisfies both, which is the kind of false positive that gets a
governance rule switched off along with its neighbours.

## Approvals carry one too

The server has stored `migration_guide` on every approval since the table
existed, the dashboard's `Approval` type has always declared it, and nothing
rendered it. The approvals view has a column now, and an approval without a
guide reads **none given** rather than being blank — a breaking change somebody
approved without saying what a consumer should do about it is a fact worth
seeing.

## What this does not do

Fetch the guide. A URL in a contract is a URL somebody else controls, and this
project does not request addresses the caller did not choose — the same rule
`--allow-remote-refs` exists for. The finding carries the link; the reader
follows it.
