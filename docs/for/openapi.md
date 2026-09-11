# OpenAPI breaking changes

<!-- generated:landing -->

OpenAPI 3.0, 3.1 and 3.2, plus Swagger 2.0. Paths, parameters, request and response schemas, security schemes, and the 3.2 additions: the `query` method, `additionalOperations`, `querystring` parameters and hierarchical tags.

```bash
apiverity breaking openapi-v1.yaml openapi-v2.yaml --check-semver
```

## The 26 catalogued rules observed firing on openapi

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
| `BRK-HEADER-ADDED` | INFO | A new response header was declared. |
| `BRK-MEDIA-TYPE-CHANGED` | ERROR | A request/response media type was added or removed. |
| `BRK-OP-ADDED` | INFO | A new operation was added (additive, non-breaking). |
| `BRK-OP-REMOVED` | ERROR | An operation was removed; existing callers will fail. |
| `BRK-PARAM-ADDED-OPTIONAL` | INFO | A new optional request parameter was added. |
| `BRK-PARAM-ADDED-REQUIRED` | ERROR | A new required request parameter was added. |
| `BRK-PARAM-OPTIONALIZED` | INFO | A required request parameter became optional. |
| `BRK-PARAM-REMOVED` | ERROR | A request parameter was removed. |
| `BRK-PARAM-REQUIRED` | ERROR | An optional request parameter became required. |
| `BRK-PARAM-TYPE-CHANGED` | ERROR | A request parameter's type/format changed. |
| `BRK-REQ-BODY-ADDED-OPTIONAL` | INFO | An optional request body was added. |
| `BRK-REQ-BODY-REMOVED` | ERROR | The request body was removed. |
| `BRK-REQ-BODY-REQUIRED` | ERROR | The request body became required. |
| `BRK-REQ-FIELD-ADDED-OPTIONAL` | INFO | An optional field was added to a request body. |
| `BRK-REQ-FIELD-ADDED-REQUIRED` | ERROR | A required field was added to a request body. |
| `BRK-REQ-FIELD-BECAME-REQUIRED` | ERROR | A request body field became required. |
| `BRK-REQ-FIELD-OPTIONALIZED` | INFO | A request body field became optional; senders are unaffected. |
| `BRK-REQ-FIELD-REMOVED` | ERROR | A request body field was removed. |
| `BRK-RESP-FIELD-ADDED` | INFO | A response body field was added (consumers ignore unknown fields). |
| `BRK-RESP-STATUS-ADDED` | INFO | A new response status was declared. |
| `BRK-SECURITY-CHANGED` | ERROR | Security requirements changed; unprepared clients fail auth. |

### 3 more fired here and are not in the catalogue

Recorded rather than dropped. A rule id a reader receives and cannot look up is
the defect this project has fixed in its own README twice, and hiding it here
would make this page's count disagree with the engine's.

- `COMPAT-MEDIA-ADDED`
- `COMPAT-MEDIA-REMOVED`
- `COMPAT-STATUS-ADDED`

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
