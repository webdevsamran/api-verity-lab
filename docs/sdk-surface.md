# Generated-SDK break detection

```bash
apiverity breaking old.yaml new.yaml --sdk
```

A contract diff asks what happens to bytes on a socket. A generated SDK is a
second contract, derived from the first by naming conventions, and it can break
while the wire stays identical.

## The one-line example

```diff
   /users/{id}:
     get:
-      operationId: getUser
+      operationId: fetchUser
```

Nothing about the request or the response moves. Every rule in the catalogue is
silent, and `apiverity diff` reports **no change at all** — `operationId` is
compared by nothing, because nothing on the wire depends on it.

Every generated client's `client.getUser(...)` stops compiling.

## The rules

| Rule | Change | Convention it assumes |
|---|---|---|
| `SDK-OPERATION-ID-CHANGED` | operationId renamed | `operation-id-names` |
| `SDK-OPERATION-ID-REMOVED` | operationId dropped | `operation-id-names` |
| `SDK-OPERATION-ID-ADDED` | operationId introduced | `operation-id-names` |
| `SDK-TAG-NAMESPACE-CHANGED` | first tag changed | `tag-namespaces` |
| `SDK-MODEL-NAME-CHANGED` | response schema `title` renamed | `title-model-names` |
| `SDK-ENUM-VALUE-ADDED` | a response enum gained a value | `closed-enums` |
| `SDK-PARAMETER-ORDER-CHANGED` | required parameters reordered | `positional-parameters` |

`apiverity explain SDK-OPERATION-ID-CHANGED` gives the full entry for any of
them.

## What this claims, and what it does not

**Nothing here is tested against any particular generator.** Each rule names
the convention it rests on, and the assumption travels on the finding itself:

```json
{
  "rule_id": "SDK-TAG-NAMESPACE-CHANGED",
  "metadata": {
    "convention": "tag-namespaces",
    "assumes": "operations are grouped into a namespace per tag"
  }
}
```

| Convention | What a generator has to do |
|---|---|
| `operation-id-names` | method names derive from `operationId` |
| `tag-namespaces` | operations are grouped into a class or namespace per tag |
| `title-model-names` | model class names come from a schema's title |
| `closed-enums` | enums become closed types that reject unknown values |
| `positional-parameters` | required parameters become positional arguments |

These are what generators *do*, stated as assumptions rather than asserted as
facts about tools this project has not run. If yours does not follow one, turn
it off:

```bash
apiverity breaking old.yaml new.yaml --sdk \
  --sdk-convention operation-id-names \
  --sdk-convention closed-enums
```

Rules that depend on the conventions you left out **do not run** — they are not
downgraded, hidden or counted. And the artifact records what the run was
allowed to assume, under `sdk_conventions`, because a narrowed run and a full
one would otherwise read as the same run with fewer problems.

## Why it is off by default

Two reasons, and only one of them is the conventions.

The other is severity. Nothing in this family is ever `ERROR`. These changes
are real and they are not wire-breaking, and a rule that outranks *"you deleted
a required response field"* because a class got renamed is a rule somebody
switches off along with everything near it.

## The two verdicts that disagree

Adding a value to a response enum produces two findings, and they say different
things:

- `BRK-ENUM-WIDENED` — **INFO**. Additive. Nothing that was valid becomes
  invalid. True.
- `SDK-ENUM-VALUE-ADDED` — **WARN**. A client may now receive a value its
  generated type has no member for: a deserialization failure, or a match that
  is no longer exhaustive. Also true.

That disagreement is the point of the family. Where the two agree, there is
only one rule — a response field becoming nullable is
`BRK-RESP-NULLABLE-ADDED` and nothing else, because a second rule saying the
same thing in generator vocabulary is one finding printed twice.

## The silent one

`SDK-PARAMETER-ORDER-CHANGED` is the only rule here whose failure is not a
compile error.

Swap two required parameters of the same type and a generator that emits them
positionally produces a signature that still accepts every existing call site.
The arguments arrive the other way round. Nothing fails to build; the wrong
tenant gets read.

Its severity is WARN like the others, because severity is about what the gate
should do, not about how much the failure deserves to be feared.
