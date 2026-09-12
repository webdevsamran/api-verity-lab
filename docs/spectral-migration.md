---
description: >-
  Import an existing Spectral ruleset with `apiverity import-rules`, and see which rules translate, which approximate and which have no equivalent.
---

# Migrating a Spectral ruleset

```bash
apiverity import-rules .spectral.yaml
```

Spectral owns rule-catalog linting, and a team that has a ruleset has invested
in it. Migration cost is the real competitor, so this reads the file and says
what moving it would actually cost.

## It is a report, not a compatibility layer

This does **not** run Spectral's rules.

A Spectral rule is a JSONPath `given` plus a function over the document.
Reimplementing that would mean a second engine inside this one, producing
findings that look like this project's and were computed by different code —
and the whole design here is that every engine reads one normalized contract
model. A bolted-on JSONPath evaluator is exactly the thing that design exists
to avoid.

## Three answers, and the useful one is not the first

| | |
|---|---|
| `covered` | a rule with an equivalent here, named. Turn it off in Spectral if you like. |
| `not_covered` | a rule this project could express and does not. **The backlog.** |
| `not_expressible` | a rule about the *document* rather than the contract. |
| `disabled` | a rule your ruleset turns off. Named, not silently re-enabled. |

A migration tool reporting only the first list would be claiming a completeness
it does not have. The number that decides whether to migrate is the second and
third together.

### Why `not_expressible` is not a backlog

`info-description`, `path-keys-no-trailing-slash`, `operation-tags`. Those ask
about the wording of a description, how a path is written, a tagging
convention — properties of the YAML file, not of the API it describes.

This project compiles a document into a normalized model, and most of that does
not survive the compile by design. Those are good rules, answered well by a
tool built to answer them. Keep Spectral for them.

## Matching is by name, and errs toward the backlog

Spectral rule names are conventional rather than standardised. The mapping
covers the names the published sets use — `spectral:oas`, `spectral:asyncapi` —
plus common styleguide names.

A custom rule with a bespoke name lands in `not_covered` **even when this
project happens to check the same thing**. That is the safe direction to be
wrong in: it over-reports the backlog rather than over-claiming the coverage.

## `extends` is counted separately, because the file does not list it

```
3 covered, 2 not covered, 3 not expressible here, 2 disabled in the ruleset.
This ruleset extends spectral:oas, whose rules are not listed in the file and
are not counted above
```

`extends: spectral:oas` is sixty-odd rules the ruleset never names. A report
counting only the named ones describes a fraction of the gate being migrated
and reads as though the migration is nearly done.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | every named rule is covered or is about the document |
| `1` | there is a backlog — the normal result, and the point |
| `2` | the file is not a Spectral ruleset |
