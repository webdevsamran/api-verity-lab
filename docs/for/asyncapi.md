# AsyncAPI breaking changes

<!-- generated:landing -->

AsyncAPI 2.x and 3.x: channels, messages and payload schemas, with diffing that knows which direction a channel runs. A payload field removed from a message you publish breaks your subscribers; one removed from a message you subscribe to breaks you.

```bash
apiverity breaking events-v1.yaml events-v2.yaml
```

## The 18 catalogued rules observed firing on asyncapi

Measured, not asserted: this format's own shipped fixture is perturbed in each of
several dozen ways and the result is whatever the rules said. A rule listed here
was seen firing on this protocol in this build; one that is absent was not, which
may mean the rule does not apply or that no mutation reached it.

| Rule | Severity | What it means |
|---|---|---|
| `BRK-CONSTRAINT-TIGHTENED` | ERROR | A request constraint was tightened; previously valid inputs fail. |
| `BRK-DEPENDENT-REQUIRED-ADDED` | ERROR | Sending one field now requires another. A request that set the first without the second was valid and is not. |
| `BRK-DEPRECATION-ADDED` | WARN | The operation is now deprecated; plan migration. |
| `BRK-ENUM-NARROWED-REQUEST` | ERROR | Request enum values were removed; clients sending old values fail. |
| `BRK-ENUM-WIDENED` | INFO | Enum values were added (additive). |
| `BRK-PARAM-ADDED-OPTIONAL` | INFO | A new optional request parameter was added. |
| `BRK-PARAM-ADDED-REQUIRED` | ERROR | A new required request parameter was added. |
| `BRK-REQ-BODY-ADDED-OPTIONAL` | INFO | An optional request body was added. |
| `BRK-REQ-BODY-REMOVED` | ERROR | The request body was removed. |
| `BRK-REQ-FIELD-ADDED-OPTIONAL` | INFO | An optional field was added to a request body. |
| `BRK-REQ-FIELD-ADDED-REQUIRED` | ERROR | A required field was added to a request body. |
| `BRK-REQ-FIELD-BECAME-REQUIRED` | ERROR | A request body field became required. |
| `BRK-REQ-FIELD-OPTIONALIZED` | INFO | A request body field became optional; senders are unaffected. |
| `BRK-REQ-FIELD-REMOVED` | ERROR | A request body field was removed. |
| `BRK-RPC-REMOVED` | ERROR | A gRPC RPC was removed; existing callers will fail. |
| `BRK-SECURITY-CHANGED` | ERROR | Security requirements changed; unprepared clients fail auth. |
| `COMPAT-MEDIA-ADDED` | INFO | An operation gained a media type. |
| `COMPAT-MEDIA-REMOVED` | WARN | An operation dropped a media type it used to accept or return. |

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
