---
description: >-
  Express naming, authentication, pagination and deprecation rules as YAML, and enforce them with `apiverity validate --policy-file` without writing Python.
---

# House rules in YAML

```bash
apiverity validate openapi.yaml --policy-file house-style.yaml
apiverity rules --policy-vocabulary
```

[Rule packs](rule-packs.md) are the right answer for a rule with real logic in
it. They are the wrong answer for *"every path must be kebab-case"* — which is
most of what an organisation actually wants to enforce, and does not justify a
Python package, a release process and somewhere to publish it.

```yaml
pack: acme-house-style
version: 1.0.0
rules:
  - id: ACME-PATHS-KEBAB
    severity: warn
    rationale: a mixed-case path is a support ticket about a 404
    remediation: rename it, adding the old path as a deprecated alias first
    select: operation
    where:
      path: {matches: '^(/[a-z0-9-]+|/\{[a-zA-Z0-9_]+\})+$'}
```

> Put a regular expression in **single** quotes. YAML processes escapes inside
> double quotes, so `"\{"` is a parse error before this file ever sees it.

## A fixed vocabulary, not an expression language

Every selector reads one field of the normalized contract model. There is no
`eval`, no JSONPath, no embedded language, and that ceiling is deliberate.

A general expression evaluator would be a second engine inside this one — the
same objection [the Spectral importer](spectral-migration.md) makes — and it
would let somebody write a rule this project cannot explain, in a tool whose
whole claim is that every finding has a stable id and a reason.

When the vocabulary runs out, write a [pack](rule-packs.md). It is twenty lines
of Python.

`apiverity rules --policy-vocabulary` prints the whole vocabulary, from the same
tables the loader validates against — so what the documentation says is
available cannot disagree with what is accepted.

### Selectors

| | |
|---|---|
| `operation` | one finding per operation that fails (the default) |
| `service` | one finding for the contract |

### Fields

**`operation`**: `operation_id`, `method`, `path`, `summary`, `description`,
`tags`, `security`, `responses`, `parameters`, `request_body`.

**`service`**: `title`, `version`, `servers`, `security_schemes`,
`global_security`.

### Predicates

| | |
|---|---|
| `present` / `absent` | the field is set, or is not |
| `matches` / `not_matches` | every value matches this regex, or none does |
| `includes` / `excludes` | the collection contains this value, or does not |
| `one_of` | every value is in this list |

`matches` on a field that is **not there** fails. `absent` is the predicate for
asking about that, and conflating the two would make `matches` silently pass on
every operation that omits the field.

## An unknown word fails the run

The failure this is built to avoid: a DSL that accepts an unrecognised selector,
matches nothing, and hands a team a gate they believe they have.

```
error: rule 'ACME-PATHS' selects `pathh`, which is not a field this vocabulary
has. Available: description, method, operation_id, parameters, path, …
```

At **load** time, before anything has been checked and reported clean. A regex
that will not compile is refused there too, rather than at check time against
the first contract somebody runs it on.

## Exemptions name what they exempt

```yaml
    except:
      - "POST /users"
```

A list of operation keys, not a pattern. A glob that grows to cover six
operations nobody reviewed is the escape hatch becoming the policy.

For an exemption with an owner, a reason and an expiry, use
[suppressions](ci.md#suppressions) instead — that is what they are for.

## Scoping

`protocols: [openapi, graphql]` restricts a rule to the protocols it makes
sense for. A protocol that does not exist is refused by name.

## What the artifact records

A run with a policy file names it:

```json
{ "command": "validate", "policies": ["house-style.yaml"], "findings": [...] }
```

Two runs over the same contract reporting different findings should say why.
