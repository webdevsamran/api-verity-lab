---
description: >-
  Breaking-change rules for the JSON Schema 2020-12 keywords OpenAPI 3.1 brought in: prefixItems, if/then, dependentRequired and patternProperties.
---

# JSON Schema 2020-12 breaking changes

<!-- generated:landing -->

OpenAPI 3.1 aligned with JSON Schema 2020-12, which brought keywords the older rules could not see: `prefixItems`, `if`/`then`, `dependentRequired`, `patternProperties`. These rules fire only against a contract that uses them.

```bash
apiverity breaking v1.yaml v2.yaml
```

## The 29 catalogued rules observed firing on openapi (2020-12)

Measured, not asserted: this format's own shipped fixture is perturbed in each of
several dozen ways and the result is whatever the rules said. A rule listed here
was seen firing on this protocol in this build; one that is absent was not, which
may mean the rule does not apply or that no mutation reached it.

| Rule | Severity | What it means |
|---|---|---|
| `BRK-CONSTRAINT-TIGHTENED` | ERROR | A request constraint was tightened; previously valid inputs fail. |
| `BRK-CONTAINS-CHANGED` | WARN | An array's `contains` requirement or its bounds changed; an array that satisfied the old rule may not satisfy the new one. |
| `BRK-DEPENDENT-REQUIRED-ADDED` | ERROR | Sending one field now requires another. A request that set the first without the second was valid and is not. |
| `BRK-DEPRECATION-ADDED` | WARN | The operation is now deprecated; plan migration. |
| `BRK-ENUM-NARROWED-REQUEST` | ERROR | Request enum values were removed; clients sending old values fail. |
| `BRK-ENUM-WIDENED` | INFO | Enum values were added (additive). |
| `BRK-HEADER-ADDED` | INFO | A new response header was declared. |
| `BRK-OP-ADDED` | INFO | A new operation was added (additive, non-breaking). |
| `BRK-OP-REMOVED` | ERROR | An operation was removed; existing callers will fail. |
| `BRK-PARAM-ADDED-OPTIONAL` | INFO | A new optional request parameter was added. |
| `BRK-PARAM-ADDED-REQUIRED` | ERROR | A new required request parameter was added. |
| `BRK-REQ-BODY-ADDED-OPTIONAL` | INFO | An optional request body was added. |
| `BRK-REQ-BODY-REMOVED` | ERROR | The request body was removed. |
| `BRK-REQ-FIELD-ADDED-OPTIONAL` | INFO | An optional field was added to a request body. |
| `BRK-REQ-FIELD-ADDED-REQUIRED` | ERROR | A required field was added to a request body. |
| `BRK-REQ-FIELD-BECAME-REQUIRED` | ERROR | A request body field became required. |
| `BRK-REQ-FIELD-OPTIONALIZED` | INFO | A request body field became optional; senders are unaffected. |
| `BRK-REQ-FIELD-REMOVED` | ERROR | A request body field was removed. |
| `BRK-RESP-CONSTRAINT-TIGHTENED` | WARN | A response constraint was tightened; returned values may fall outside what clients expect. |
| `BRK-RESP-FIELD-ADDED` | INFO | A response body field was added (consumers ignore unknown fields). |
| `BRK-RESP-FIELD-GUARANTEED` | INFO | A response field that was optional is now always present; consumers gain a guarantee they did not have. |
| `BRK-RESP-FIELD-OPTIONALIZED` | ERROR | A response field is no longer guaranteed; consumers reading it unconditionally will break. |
| `BRK-RESP-FIELD-REMOVED` | ERROR | A response body field was removed; readers of it break. |
| `BRK-RESP-STATUS-ADDED` | INFO | A new response status was declared. |
| `BRK-RESP-TYPE-CHANGED` | WARN | A response field's type changed; consumers may misparse values. |
| `BRK-SECURITY-CHANGED` | ERROR | Security requirements changed; unprepared clients fail auth. |
| `BRK-TUPLE-SHAPE-CHANGED` | ERROR | Positional array items changed length or type. Tuple members are read by index, so a change at one position shifts or misparses every reader. |
| `COMPAT-MEDIA-ADDED` | INFO | An operation gained a media type. |
| `COMPAT-STATUS-ADDED` | INFO | An operation documents a status code it did not before. |

[The full catalogue](../rule-catalog.md) has the rationale and the remediation for
each. [Rule parity](../rule-parity.md) is the same measurement across every format
at once.

## The rest of the toolchain speaks this format too

One contract model means the other commands are not separate tools:

```bash
apiverity validate contract          # lint and security checks
apiverity changelog old new          # a human changelog of the same diff
apiverity coverage contract          # which operations your tests reach
apiverity drift contract --base-url  # does the running service still match?
```

[Protocol support](../protocol-support.md) is the full matrix of what each format
supports, and what it does not.
