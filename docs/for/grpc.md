---
description: >-
  Breaking-change detection for gRPC and protobuf: field numbers, presence, streaming and reserved ranges, from .proto sources or descriptor sets.
---

# gRPC and protobuf breaking changes

<!-- generated:landing -->

`.proto` sources and compiled descriptor sets. Field numbers, presence, streaming, reserved ranges -- the things that break a generated stub while leaving the service definition looking similar.

```bash
apiverity breaking users_v1.proto users_v2.proto
```

## The 29 catalogued rules observed firing on grpc

Measured, not asserted: this format's own shipped fixture is perturbed in each of
several dozen ways and the result is whatever the rules said. A rule listed here
was seen firing on this protocol in this build; one that is absent was not, which
may mean the rule does not apply or that no mutation reached it.

| Rule | Severity | What it means |
|---|---|---|
| `BRK-CONSTRAINT-TIGHTENED` | ERROR | A request constraint was tightened; previously valid inputs fail. |
| `BRK-DEPENDENT-REQUIRED-ADDED` | ERROR | Sending one field now requires another. A request that set the first without the second was valid and is not. |
| `BRK-DEPRECATION-ADDED` | WARN | The operation is now deprecated; plan migration. |
| `BRK-FIELD-NUMBER-REUSED` | ERROR | A protobuf field number now names a different field; stored data misdecodes. |
| `BRK-FIELD-NUMBER-UNRESERVED` | WARN | A protobuf field was removed without reserving its number. |
| `BRK-FIELD-PRESENCE-LOST` | ERROR | A protobuf field lost explicit presence; unset and default are now the same. |
| `BRK-HEADER-ADDED` | INFO | A new response header was declared. |
| `BRK-PARAM-ADDED-OPTIONAL` | INFO | A new optional request parameter was added. |
| `BRK-PARAM-ADDED-REQUIRED` | ERROR | A new required request parameter was added. |
| `BRK-REQ-BODY-ADDED-OPTIONAL` | INFO | An optional request body was added. |
| `BRK-REQ-BODY-REMOVED` | ERROR | The request body was removed. |
| `BRK-REQ-FIELD-ADDED-OPTIONAL` | INFO | An optional field was added to a request body. |
| `BRK-REQ-FIELD-ADDED-REQUIRED` | ERROR | A required field was added to a request body. |
| `BRK-REQ-FIELD-BECAME-REQUIRED` | ERROR | A request body field became required. |
| `BRK-REQ-FIELD-REMOVED` | ERROR | A request body field was removed. |
| `BRK-RESERVATION-REMOVED` | WARN | A protobuf field number is no longer reserved and can be reused by mistake. |
| `BRK-RESP-FIELD-ADDED` | INFO | A response body field was added (consumers ignore unknown fields). |
| `BRK-RESP-FIELD-GUARANTEED` | INFO | A response field that was optional is now always present; consumers gain a guarantee they did not have. |
| `BRK-RESP-FIELD-REMOVED` | ERROR | A response body field was removed; readers of it break. |
| `BRK-RESP-STATUS-ADDED` | INFO | A new response status was declared. |
| `BRK-RESP-TYPE-CHANGED` | WARN | A response field's type changed; consumers may misparse values. |
| `BRK-RPC-ADDED` | INFO | A new gRPC RPC was added (additive, non-breaking). |
| `BRK-RPC-REMOVED` | ERROR | A gRPC RPC was removed; existing callers will fail. |
| `BRK-RPC-STREAMING-CHANGED` | ERROR | An RPC changed streaming cardinality; generated clients call it wrongly. |
| `BRK-SECURITY-CHANGED` | ERROR | Security requirements changed; unprepared clients fail auth. |
| `COMPAT-MEDIA-ADDED` | INFO | An operation gained a media type. |
| `COMPAT-STATUS-ADDED` | INFO | An operation documents a status code it did not before. |
| `PROTO-FIELD-REMOVED` | WARN | A message field was removed. |
| `PROTO-RPC-REMOVED` | ERROR | An RPC was removed; existing stubs fail at runtime rather than at compile time. |

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
