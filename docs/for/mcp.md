# MCP tool manifest breaking changes

<!-- generated:landing -->

A saved `tools/list` response, diffed under the same rules as any other contract, plus a `BRK-MCP-*` family for the parts that are MCP's alone: annotation hints, `outputSchema` presence and tool-description edits. An agent routes on the description, so a silent edit to one is a change to what your agents do.

```bash
apiverity breaking tools-v1.json tools-v2.json
```

## The 31 catalogued rules observed firing on mcp

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
| `BRK-MCP-DESTRUCTIVE-HINT-SET` | WARN | A tool now declares it may perform irreversible updates. |
| `BRK-MCP-OUTPUT-SCHEMA-ADDED` | WARN | A tool now declares an outputSchema, so its own results must conform to it from this version on. |
| `BRK-MCP-OUTPUT-SCHEMA-REMOVED` | ERROR | A tool stopped declaring an outputSchema; consumers parsing its structuredContent lose the guarantee they were written against. |
| `BRK-MCP-READONLY-HINT-CLEARED` | WARN | A tool stopped claiming readOnlyHint. A host that auto-approved it as safe to call may now be invoking something that writes. |
| `BRK-MCP-TOOL-DESCRIPTION-CHANGED` | WARN | A tool description changed. For an MCP tool the description is the routing input the model reads, not documentation for a human, so a silent edit can redirect an agent (OWASP MCP03, tool poisoning). WARN rather than ERROR because copy edits are routine; raise it with --severity-override if you treat a manifest as supply chain. |
| `BRK-PARAM-ADDED-OPTIONAL` | INFO | A new optional request parameter was added. |
| `BRK-PARAM-ADDED-REQUIRED` | ERROR | A new required request parameter was added. |
| `BRK-REQ-BODY-ADDED-OPTIONAL` | INFO | An optional request body was added. |
| `BRK-REQ-BODY-REMOVED` | ERROR | The request body was removed. |
| `BRK-REQ-FIELD-ADDED-OPTIONAL` | INFO | An optional field was added to a request body. |
| `BRK-REQ-FIELD-ADDED-REQUIRED` | ERROR | A required field was added to a request body. |
| `BRK-REQ-FIELD-BECAME-REQUIRED` | ERROR | A request body field became required. |
| `BRK-REQ-FIELD-OPTIONALIZED` | INFO | A request body field became optional; senders are unaffected. |
| `BRK-REQ-FIELD-REMOVED` | ERROR | A request body field was removed. |
| `BRK-RESP-FIELD-ADDED` | INFO | A response body field was added (consumers ignore unknown fields). |
| `BRK-RESP-FIELD-GUARANTEED` | INFO | A response field that was optional is now always present; consumers gain a guarantee they did not have. |
| `BRK-RESP-FIELD-OPTIONALIZED` | ERROR | A response field is no longer guaranteed; consumers reading it unconditionally will break. |
| `BRK-RESP-FIELD-REMOVED` | ERROR | A response body field was removed; readers of it break. |
| `BRK-RESP-STATUS-ADDED` | INFO | A new response status was declared. |
| `BRK-RESP-TYPE-CHANGED` | WARN | A response field's type changed; consumers may misparse values. |
| `BRK-RPC-ADDED` | INFO | A new gRPC RPC was added (additive, non-breaking). |
| `BRK-RPC-REMOVED` | ERROR | A gRPC RPC was removed; existing callers will fail. |
| `BRK-SECURITY-CHANGED` | ERROR | Security requirements changed; unprepared clients fail auth. |
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
