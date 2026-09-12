---
description: >-
  Which breaking-change rules actually fire for OpenAPI, Swagger 2.0, AsyncAPI, GraphQL, gRPC, MCP and WSDL -- measured by making every rule fire, not asserted.
---

# Rule parity across protocols

Which of the breaking-change rules actually fire, for each format this tool
reads.

**This table is derived, not asserted.** Each protocol's shipped contract is
loaded into the normalized model, perturbed in each of the ways listed below,
and diffed against itself; the cells record what the rules said. A matrix
claiming coverage nobody demonstrated is worse than no matrix, because it is
the kind of thing that gets quoted in an evaluation.

## How to read an empty cell

It means **no mutation here produced that rule for that protocol**. It does not
mean the rule cannot fire. The mutation list is finite and deliberately small —
changes a person would actually make — so an empty cell is a fact
about this harness, not a limit of the engine.

The useful signal is the *shape*: a rule that fires for one protocol and not
another usually means the second format cannot express the change, or its
parser does not carry the field the rule reads. `BRK-FIELD-NUMBER-*` firing only
for gRPC is the model working correctly; a schema rule firing only for OpenAPI
would be a parser that is not populating something.


## What was changed

| Mutation | Stands for |
|---|---|
| remove an operation | an endpoint or RPC is deleted |
| deprecate an operation | an endpoint is marked deprecated |
| remove a response field | a field consumers read is gone |
| add a required request field | callers must now send something new |
| remove a request field | an accepted input disappears |
| change a response field's type | consumers parse the wrong thing |
| narrow an enum | a previously valid value is refused |
| tighten a constraint | previously valid input fails |
| make an optional request field required | an omission that used to be fine is not |
| remove a parameter | a query or path input is gone |
| add a required parameter | callers must send more |
| remove a response status | a declared outcome is gone |
| remove a response header | a promised header is gone |
| change security | what a caller must present changes |
| reuse a field number | stored protobuf data misdecodes |
| remove a reservation | a retired number can be reused |
| change streaming | generated clients call the RPC wrongly |
| widen an enum | a new value starts being accepted |
| narrow a response enum | a value consumers switched on stops being returned |
| loosen a constraint | a declared bound is dropped |
| add a response field | the response grows |
| guarantee a response field | an optional response field starts always being sent |
| make a response field optional | a guarantee is withdrawn |
| add an operation | a new endpoint or RPC |
| un-deprecate an operation | a retirement is called off |
| add an optional parameter | a new opt-in input |
| make a parameter optional | an input stops being needed |
| make a parameter required | an input starts being needed |
| change a parameter's type | callers send the wrong shape |
| add a response header | a new promised header |
| add a response status | a new declared outcome |
| change a media type | the wire format moves |
| remove the request body | an endpoint stops taking one |
| require the request body | it stops being optional |
| lose field presence | unset and default become the same |
| move a field into a oneof | fields become exclusive |
| un-reserve a field number | a retired protobuf number can be handed out again |
| change a dependent requirement | sending one field starts requiring another |
| change a tuple | positional items shift |
| change `contains` | an array's membership rule moves |
| change pattern properties | a whole family of fields changes at once |
| change property names | which keys are allowed moves |
| change a conditional | an if/then branch applies elsewhere |
| set an MCP annotation | a tool claims something new |
| clear an MCP annotation | a tool stops claiming it |
| change a tool description | the routing input an agent reads is edited |
| add an output schema | a tool starts guaranteeing a shape |
| remove an output schema | it stops guaranteeing one |
| add an optional request field | a new input callers may send |
| make a request field optional | an input stops being mandatory |
| add a required request body | an endpoint that took nothing now needs a body |
| change the SOAPAction | the header a gateway routes on, with every schema untouched |
| change the binding style | document becomes rpc |
| change the SOAP version | 1.1 becomes 1.2 |
| bump the version | a release, with nothing else changed |

## Rules

| Rule | Severity | asyncapi | grpc | mcp | openapi | openapi (2020-12) | swagger2 | wsdl |
|---|---|---|---|---|---|---|---|---|
| `BRK-CONDITIONAL-SCHEMA-CHANGED` | WARN |  |  |  |  |  |  |  |
| `BRK-CONSTRAINT-LOOSENED` | INFO |  |  |  |  |  |  |  |
| `BRK-CONSTRAINT-TIGHTENED` | ERROR | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `BRK-CONTAINS-CHANGED` | WARN |  |  |  |  | ✓ |  |  |
| `BRK-DEPENDENT-REQUIRED-ADDED` | ERROR | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `BRK-DEPENDENT-REQUIRED-REMOVED` | WARN |  |  |  |  |  |  |  |
| `BRK-DEPENDENT-SCHEMA-CHANGED` | WARN |  |  |  |  |  |  |  |
| `BRK-DEPRECATION-ADDED` | WARN | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `BRK-DEPRECATION-REMOVED` | INFO |  |  |  |  |  |  |  |
| `BRK-ENUM-NARROWED-REQUEST` | ERROR | ✓ |  | ✓ | ✓ | ✓ | ✓ |  |
| `BRK-ENUM-NARROWED-RESPONSE` | WARN |  |  |  |  |  |  |  |
| `BRK-ENUM-WIDENED` | INFO | ✓ |  | ✓ | ✓ | ✓ | ✓ |  |
| `BRK-FIELD-NUMBER-REUSED` | ERROR |  | ✓ |  |  |  |  |  |
| `BRK-FIELD-NUMBER-UNRESERVED` | WARN |  | ✓ |  |  |  |  |  |
| `BRK-FIELD-PRESENCE-LOST` | ERROR |  | ✓ |  |  |  |  |  |
| `BRK-HEADER-ADDED` | INFO |  | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `BRK-HEADER-REMOVED` | WARN |  |  |  |  |  |  |  |
| `BRK-MCP-ANNOTATION-DECLARATION-CHANGED` | INFO |  |  |  |  |  |  |  |
| `BRK-MCP-DESTRUCTIVE-HINT-CLEARED` | WARN |  |  |  |  |  |  |  |
| `BRK-MCP-DESTRUCTIVE-HINT-SET` | WARN |  |  | ✓ |  |  |  |  |
| `BRK-MCP-IDEMPOTENT-HINT-CLEARED` | WARN |  |  |  |  |  |  |  |
| `BRK-MCP-IDEMPOTENT-HINT-SET` | WARN |  |  |  |  |  |  |  |
| `BRK-MCP-MANIFEST-TRUNCATED` | ERROR |  |  |  |  |  |  |  |
| `BRK-MCP-OPENWORLD-HINT-CHANGED` | INFO |  |  |  |  |  |  |  |
| `BRK-MCP-OUTPUT-SCHEMA-ADDED` | WARN |  |  | ✓ |  |  |  |  |
| `BRK-MCP-OUTPUT-SCHEMA-REMOVED` | ERROR |  |  | ✓ |  |  |  |  |
| `BRK-MCP-READONLY-HINT-CLEARED` | WARN |  |  | ✓ |  |  |  |  |
| `BRK-MCP-READONLY-HINT-SET` | WARN |  |  |  |  |  |  |  |
| `BRK-MCP-TOOL-DESCRIPTION-CHANGED` | WARN |  |  | ✓ |  |  |  |  |
| `BRK-MCP-TOOL-RENAME-SUSPECTED` | INFO |  |  |  |  |  |  |  |
| `BRK-MEDIA-TYPE-CHANGED` | ERROR |  |  |  | ✓ |  | ✓ |  |
| `BRK-ONEOF-NARROWED` | ERROR |  |  |  |  |  |  |  |
| `BRK-ONEOF-WIDENED` | INFO |  |  |  |  |  |  |  |
| `BRK-OP-ADDED` | INFO |  |  |  | ✓ | ✓ | ✓ |  |
| `BRK-OP-REMOVED` | ERROR |  |  |  | ✓ | ✓ | ✓ |  |
| `BRK-PARAM-ADDED-OPTIONAL` | INFO | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `BRK-PARAM-ADDED-REQUIRED` | ERROR | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `BRK-PARAM-OPTIONALIZED` | INFO |  |  |  | ✓ |  | ✓ |  |
| `BRK-PARAM-REMOVED` | ERROR |  |  |  | ✓ |  | ✓ |  |
| `BRK-PARAM-REQUIRED` | ERROR |  |  |  | ✓ |  | ✓ |  |
| `BRK-PARAM-TYPE-CHANGED` | ERROR |  |  |  | ✓ |  | ✓ |  |
| `BRK-PATTERN-PROPERTIES-CHANGED` | WARN |  |  |  |  |  |  |  |
| `BRK-PROPERTY-NAMES-CHANGED` | WARN |  |  |  |  |  |  |  |
| `BRK-REQ-BODY-ADDED-OPTIONAL` | INFO | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `BRK-REQ-BODY-ADDED-REQUIRED` | ERROR |  |  |  |  |  |  |  |
| `BRK-REQ-BODY-REMOVED` | ERROR | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `BRK-REQ-BODY-REQUIRED` | ERROR |  |  |  | ✓ |  |  |  |
| `BRK-REQ-FIELD-ADDED-OPTIONAL` | INFO | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `BRK-REQ-FIELD-ADDED-REQUIRED` | ERROR | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `BRK-REQ-FIELD-BECAME-REQUIRED` | ERROR | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| `BRK-REQ-FIELD-OPTIONALIZED` | INFO | ✓ |  | ✓ | ✓ | ✓ | ✓ | ✓ |
| `BRK-REQ-FIELD-REMOVED` | ERROR | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `BRK-REQ-NULLABLE-ADDED` | INFO |  |  |  |  |  |  |  |
| `BRK-REQ-NULLABLE-REMOVED` | ERROR |  |  |  |  |  |  |  |
| `BRK-RESERVATION-REMOVED` | WARN |  | ✓ |  |  |  |  |  |
| `BRK-RESP-CONSTRAINT-LOOSENED` | WARN |  |  |  |  |  |  |  |
| `BRK-RESP-CONSTRAINT-TIGHTENED` | WARN |  |  |  |  | ✓ |  |  |
| `BRK-RESP-FIELD-ADDED` | INFO |  | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `BRK-RESP-FIELD-GUARANTEED` | INFO |  | ✓ | ✓ |  | ✓ |  |  |
| `BRK-RESP-FIELD-OPTIONALIZED` | ERROR |  |  | ✓ |  | ✓ |  | ✓ |
| `BRK-RESP-FIELD-REMOVED` | ERROR |  | ✓ | ✓ |  | ✓ |  | ✓ |
| `BRK-RESP-NULLABLE-ADDED` | WARN |  |  |  |  |  |  |  |
| `BRK-RESP-NULLABLE-REMOVED` | INFO |  |  |  |  |  |  |  |
| `BRK-RESP-STATUS-ADDED` | INFO |  | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `BRK-RESP-STATUS-REMOVED` | ERROR |  |  |  |  |  | ✓ | ✓ |
| `BRK-RESP-TYPE-CHANGED` | WARN |  | ✓ | ✓ |  | ✓ |  | ✓ |
| `BRK-RPC-ADDED` | INFO |  | ✓ | ✓ |  |  |  | ✓ |
| `BRK-RPC-REMOVED` | ERROR | ✓ | ✓ | ✓ |  |  |  | ✓ |
| `BRK-RPC-STREAMING-CHANGED` | ERROR |  | ✓ |  |  |  |  |  |
| `BRK-SECURITY-CHANGED` | ERROR | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `BRK-SOAP-ACTION-CHANGED` | ERROR |  |  |  |  |  |  | ✓ |
| `BRK-SOAP-STYLE-CHANGED` | ERROR |  |  |  |  |  |  | ✓ |
| `BRK-SOAP-VERSION-CHANGED` | ERROR |  |  |  |  |  |  | ✓ |
| `BRK-STREAM-ENCODING-CHANGED` | ERROR |  |  |  |  |  |  |  |
| `BRK-STREAM-ITEM-SCHEMA-ADDED` | INFO |  |  |  |  |  |  |  |
| `BRK-STREAM-ITEM-SCHEMA-REMOVED` | ERROR |  |  |  |  |  |  |  |
| `BRK-STREAM-PREFIX-COUNT-CHANGED` | ERROR |  |  |  |  |  |  |  |
| `BRK-STREAM-SEQUENTIAL-CHANGED` | ERROR |  |  |  |  |  |  |  |
| `BRK-TUPLE-SHAPE-CHANGED` | ERROR |  |  |  |  | ✓ |  |  |

## Rules no mutation produced

The interesting column. Each of these is either a mutation this harness does not make, or a rule no input can produce — and the second is a defect this project has found four separate times. Listed rather than hidden in a table of empty cells.

- `BRK-CONDITIONAL-SCHEMA-CHANGED` — An `if`/`then`/`else` branch was added, removed or changed. What is valid now depends on a condition, and the condition moved.
- `BRK-CONSTRAINT-LOOSENED` — A request constraint was loosened (previously invalid inputs pass).
- `BRK-DEPENDENT-REQUIRED-REMOVED` — A field no longer forces another to be present. Harmless in a request; in a response it withdraws a guarantee consumers may read unconditionally.
- `BRK-DEPENDENT-SCHEMA-CHANGED` — A schema that applies only when some field is present was added, removed or changed; what is valid now depends on which fields are sent.
- `BRK-DEPRECATION-REMOVED` — The deprecation marker was removed.
- `BRK-ENUM-NARROWED-RESPONSE` — Response enum values were removed; clients may encounter undeclared values at runtime.
- `BRK-HEADER-REMOVED` — A declared response header was removed.
- `BRK-MCP-ANNOTATION-DECLARATION-CHANGED` — An annotation moved between false and undeclared without changing what it asserts.
- `BRK-MCP-DESTRUCTIVE-HINT-CLEARED` — A tool stopped declaring destructiveHint; hosts may stop gating behaviour that nobody re-verified as safe.
- `BRK-MCP-IDEMPOTENT-HINT-CLEARED` — A tool stopped claiming idempotentHint; a retry that was safe may now duplicate its effect.
- `BRK-MCP-IDEMPOTENT-HINT-SET` — A tool now claims idempotentHint; hosts may begin retrying a call that was not previously retry-safe.
- `BRK-MCP-MANIFEST-TRUNCATED` — One side is a single page of a paginated tools/list. Every tool past the page boundary reads as removed, so the whole comparison is unsound.
- `BRK-MCP-OPENWORLD-HINT-CHANGED` — openWorldHint changed. It describes the domain a tool reaches into and constrains no caller.
- `BRK-MCP-READONLY-HINT-SET` — A tool now claims readOnlyHint; hosts may stop asking for confirmation on a claim nobody verified.
- `BRK-MCP-TOOL-RENAME-SUSPECTED` — Exactly one tool disappeared and one appeared with an identical schema. Context for the removal, which is still reported: a manifest carries no identity but the name, so a rename cannot be distinguished from remove-plus-add.
- `BRK-ONEOF-NARROWED` — A protobuf field moved into a oneof; it is now exclusive with the others.
- `BRK-ONEOF-WIDENED` — A protobuf field moved out of a oneof; no existing sender can notice.
- `BRK-PATTERN-PROPERTIES-CHANGED` — The schema applied to properties matching a name pattern was added, removed or changed; a whole family of fields changed shape at once.
- `BRK-PROPERTY-NAMES-CHANGED` — The constraint on what property *names* are allowed changed; keys that used to be accepted may not be.
- `BRK-REQ-BODY-ADDED-REQUIRED` — A required request body was added.
- `BRK-REQ-NULLABLE-ADDED` — A request field now accepts null as well (additive).
- `BRK-REQ-NULLABLE-REMOVED` — A request field that accepted null no longer does; payloads that were valid are now rejected.
- `BRK-RESP-CONSTRAINT-LOOSENED` — A bound on a response field was relaxed or removed; the service may now return values a consumer written against the old bound rejects.
- `BRK-RESP-NULLABLE-ADDED` — A response value that was never null may now be null; every reader that did not check breaks on the first one, and in a generated client the field changes type at every use site.
- `BRK-RESP-NULLABLE-REMOVED` — A response value can no longer be null (narrowing a response is safe for readers).
- `BRK-STREAM-ENCODING-CHANGED` — The encoding of a streamed item changed; the part still arrives and the parser reading it fails.
- `BRK-STREAM-ITEM-SCHEMA-ADDED` — A sequential media type now declares `itemSchema`.
- `BRK-STREAM-ITEM-SCHEMA-REMOVED` — A sequential media type stopped declaring `itemSchema`, so nothing describes one item any more.
- `BRK-STREAM-PREFIX-COUNT-CHANGED` — The number of leading parts in a multipart stream changed; `prefixEncoding` is positional, so a reader counting parts reads the wrong one from there on.
- `BRK-STREAM-SEQUENTIAL-CHANGED` — A payload moved between a single document and a sequence of items; every client has to be rewritten even when the item shape is identical.

_49 of 79 rules observed firing across 7 protocol(s) and 55 mutations._
