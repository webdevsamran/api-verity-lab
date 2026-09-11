# SOAP and WSDL breaking changes

<!-- generated:landing -->

WSDL 1.1: portTypes, bindings and the XSD subset a WSDL actually uses, plus a `BRK-SOAP-*` family for SOAPAction, binding style and SOAP version -- the three facts that break every generated stub while leaving every message schema identical.

```bash
apiverity breaking orders-v1.wsdl orders-v2.wsdl
```

## The 24 catalogued rules observed firing on wsdl

Measured, not asserted: this format's own shipped fixture is perturbed in each of
several dozen ways and the result is whatever the rules said. A rule listed here
was seen firing on this protocol in this build; one that is absent was not, which
may mean the rule does not apply or that no mutation reached it.

| Rule | Severity | What it means |
|---|---|---|
| `BRK-CONSTRAINT-TIGHTENED` | ERROR | A request constraint was tightened; previously valid inputs fail. |
| `BRK-DEPENDENT-REQUIRED-ADDED` | ERROR | Sending one field now requires another. A request that set the first without the second was valid and is not. |
| `BRK-DEPRECATION-ADDED` | WARN | The operation is now deprecated; plan migration. |
| `BRK-HEADER-ADDED` | INFO | A new response header was declared. |
| `BRK-PARAM-ADDED-OPTIONAL` | INFO | A new optional request parameter was added. |
| `BRK-PARAM-ADDED-REQUIRED` | ERROR | A new required request parameter was added. |
| `BRK-REQ-BODY-ADDED-OPTIONAL` | INFO | An optional request body was added. |
| `BRK-REQ-BODY-REMOVED` | ERROR | The request body was removed. |
| `BRK-REQ-FIELD-ADDED-OPTIONAL` | INFO | An optional field was added to a request body. |
| `BRK-REQ-FIELD-ADDED-REQUIRED` | ERROR | A required field was added to a request body. |
| `BRK-REQ-FIELD-OPTIONALIZED` | INFO | A request body field became optional; senders are unaffected. |
| `BRK-REQ-FIELD-REMOVED` | ERROR | A request body field was removed. |
| `BRK-RESP-FIELD-ADDED` | INFO | A response body field was added (consumers ignore unknown fields). |
| `BRK-RESP-FIELD-OPTIONALIZED` | ERROR | A response field is no longer guaranteed; consumers reading it unconditionally will break. |
| `BRK-RESP-FIELD-REMOVED` | ERROR | A response body field was removed; readers of it break. |
| `BRK-RESP-STATUS-ADDED` | INFO | A new response status was declared. |
| `BRK-RESP-STATUS-REMOVED` | ERROR | A declared response status was removed. |
| `BRK-RESP-TYPE-CHANGED` | WARN | A response field's type changed; consumers may misparse values. |
| `BRK-RPC-ADDED` | INFO | A new gRPC RPC was added (additive, non-breaking). |
| `BRK-RPC-REMOVED` | ERROR | A gRPC RPC was removed; existing callers will fail. |
| `BRK-SECURITY-CHANGED` | ERROR | Security requirements changed; unprepared clients fail auth. |
| `BRK-SOAP-ACTION-CHANGED` | ERROR | The SOAPAction header changed. Gateways and ESBs route on it and generated stubs send the old one, with an unchanged body that now reaches nothing. |
| `BRK-SOAP-STYLE-CHANGED` | ERROR | A binding moved between document and rpc style, which changes how the body is wrapped; every existing client serializes it the old way. |
| `BRK-SOAP-VERSION-CHANGED` | ERROR | A port moved between SOAP 1.1 and 1.2. The envelope namespace and the Content-Type both change, so a 1.1 client gets a 415 rather than a fault. |

### 3 more fired here and are not in the catalogue

Recorded rather than dropped. A rule id a reader receives and cannot look up is
the defect this project has fixed in its own README twice, and hiding it here
would make this page's count disagree with the engine's.

- `COMPAT-MEDIA-ADDED`
- `COMPAT-STATUS-ADDED`
- `COMPAT-STATUS-REMOVED`

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
