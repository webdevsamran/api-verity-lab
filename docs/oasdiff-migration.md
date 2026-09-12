---
description: >-
  Moving a CI gate from oasdiff: which of your jq filters keep matching, the change-code mapping, and `report --format oasdiff` so leaving again is cheap.
---

# Migrating from oasdiff

Migration cost is the real competitor. A team already gating on
[oasdiff](https://github.com/oasdiff/oasdiff) has `jq` filters, ignore-lists and
dashboards keyed on its output, and asking them to rewrite all of that to *try*
something else is asking for more than a trial is worth.

```bash
apiverity report ./bundle --format oasdiff
```

writes the same shape `oasdiff breaking -f json` does: a bare JSON array of
change objects, most severe first, so an existing filter keeps matching.

**This page is generated** from `apiverity/reports/oasdiff.py`. A hand-written
migration table goes stale the first time somebody adds a rule, and a stale one
is worse than none — it promises a filter still works after it has stopped.

## What was verified, and when

Checked **2026-09-10** against `oasdiff/oasdiff` at `main`, release
**v1.31.0**, Apache-2.0.

`formatters/changes.go` defines the emitted object: `id`, `text`, `comment`,
`disclaimers`, `level`, `operation`, `operationId`, `path`, `section`,
`attributes`, `baseSource`, `revisionSource`, `fingerprint` — all `omitempty`
except `level`. `checker/source.go` makes `baseSource`/`revisionSource`
`{file, line, column, endLine, endColumn}`. `checker/rules/level.go` declares
`type Level int` with `ERR = 3`, `WARN = 2`, `INFO = 1`, `NONE = 0`,
`INVALID = -1` and **no** `MarshalJSON` — so `level` is a *number*, not the
string its `String()` method returns. That last one is the detail a
from-memory implementation gets wrong.


## Rules that map exactly

| This tool | oasdiff |
|---|---|
| `BRK-DEPRECATION-ADDED` | `endpoint-deprecated` |
| `BRK-HEADER-ADDED` | `response-header-added` |
| `BRK-MEDIA-TYPE-CHANGED` | `response-media-type-name-changed` |
| `BRK-OP-ADDED` | `endpoint-added` |
| `BRK-OP-REMOVED` | `api-removed-without-deprecation` |
| `BRK-PARAM-ADDED-OPTIONAL` | `new-optional-request-parameter` |
| `BRK-PARAM-ADDED-REQUIRED` | `new-required-request-parameter` |
| `BRK-PARAM-OPTIONALIZED` | `request-parameter-became-optional` |
| `BRK-PARAM-REMOVED` | `request-parameter-removed` |
| `BRK-PARAM-REQUIRED` | `request-parameter-became-required` |
| `BRK-PARAM-TYPE-CHANGED` | `request-parameter-type-changed` |
| `BRK-REQ-BODY-ADDED-OPTIONAL` | `request-body-added-optional` |
| `BRK-REQ-BODY-ADDED-REQUIRED` | `request-body-added-required` |
| `BRK-REQ-BODY-REQUIRED` | `request-body-became-required` |
| `BRK-REQ-FIELD-ADDED-OPTIONAL` | `new-optional-request-property` |
| `BRK-REQ-FIELD-ADDED-REQUIRED` | `new-required-request-property` |
| `BRK-REQ-FIELD-BECAME-REQUIRED` | `request-property-became-required` |
| `BRK-RESP-FIELD-OPTIONALIZED` | `response-property-became-optional` |
| `BRK-RESP-FIELD-REMOVED` | `response-required-property-removed` |
| `BRK-RESP-TYPE-CHANGED` | `response-property-type-changed` |
| `BRK-RPC-ADDED` | `endpoint-added` |
| `BRK-RPC-REMOVED` | `api-removed-without-deprecation` |
| `BRK-RESP-STATUS-ADDED` (2xx) | `response-success-status-added` |
| `BRK-RESP-STATUS-ADDED` (other) | `response-non-success-status-added` |
| `BRK-RESP-STATUS-REMOVED` (2xx) | `response-success-status-removed` |
| `BRK-RESP-STATUS-REMOVED` (other) | `response-non-success-status-removed` |

## Rules with a near miss, and why they are not mapped

These come out as `x-apiverity-<rule id>`, which cannot collide with an oasdiff check id and can be grepped for. Each one is a decision somebody can argue with rather than an omission.

| This tool | Why not |
|---|---|
| `BRK-CONSTRAINT-LOOSENED` | the same, in the other direction |
| `BRK-CONSTRAINT-TIGHTENED` | oasdiff has a separate id per constraint and direction (request-parameter-max-decreased, -max-length-decreased, ...); this rule names the constraint in its message rather than in its id |
| `BRK-ENUM-NARROWED-REQUEST` | oasdiff separates request-parameter-enum-value-removed from request-property-enum-value-removed; this rule covers both and does not record which |
| `BRK-ENUM-NARROWED-RESPONSE` | oasdiff's nearest is response-mediatype-enum-value-removed, which is about the media type's enum rather than a property's |
| `BRK-HEADER-REMOVED` | oasdiff separates required-response-header-removed from optional-response-header-removed; response header requiredness is not modelled here |
| `BRK-RESP-FIELD-ADDED` | oasdiff's response-required-property-added asserts the new field is required, which this rule does not determine |
| `BRK-RESP-FIELD-GUARANTEED` | oasdiff has response-property-became-optional and no counterpart for the opposite direction |
| `BRK-SECURITY-CHANGED` | oasdiff splits api-security-added, -removed, -updated and the scope variants; this rule does not record which |

## Rules with no oasdiff counterpart at all

oasdiff reads OpenAPI. A protobuf field number, an MCP annotation and a SOAPAction have no check to map onto, so these are namespaced too — listed rather than left for somebody to discover when a filter silently stops matching.

- `BRK-CONDITIONAL-SCHEMA-CHANGED` — An `if`/`then`/`else` branch was added, removed or changed. What is valid now depends on a condition, and the condition moved.
- `BRK-CONTAINS-CHANGED` — An array's `contains` requirement or its bounds changed; an array that satisfied the old rule may not satisfy the new one.
- `BRK-DEPENDENT-REQUIRED-ADDED` — Sending one field now requires another. A request that set the first without the second was valid and is not.
- `BRK-DEPENDENT-REQUIRED-REMOVED` — A field no longer forces another to be present. Harmless in a request; in a response it withdraws a guarantee consumers may read unconditionally.
- `BRK-DEPENDENT-SCHEMA-CHANGED` — A schema that applies only when some field is present was added, removed or changed; what is valid now depends on which fields are sent.
- `BRK-DEPRECATION-REMOVED` — The deprecation marker was removed.
- `BRK-ENUM-WIDENED` — Enum values were added (additive).
- `BRK-FIELD-NUMBER-REUSED` — A protobuf field number now names a different field; stored data misdecodes.
- `BRK-FIELD-NUMBER-UNRESERVED` — A protobuf field was removed without reserving its number.
- `BRK-FIELD-PRESENCE-LOST` — A protobuf field lost explicit presence; unset and default are now the same.
- `BRK-MCP-ANNOTATION-DECLARATION-CHANGED` — An annotation moved between false and undeclared without changing what it asserts.
- `BRK-MCP-DESTRUCTIVE-HINT-CLEARED` — A tool stopped declaring destructiveHint; hosts may stop gating behaviour that nobody re-verified as safe.
- `BRK-MCP-DESTRUCTIVE-HINT-SET` — A tool now declares it may perform irreversible updates.
- `BRK-MCP-IDEMPOTENT-HINT-CLEARED` — A tool stopped claiming idempotentHint; a retry that was safe may now duplicate its effect.
- `BRK-MCP-IDEMPOTENT-HINT-SET` — A tool now claims idempotentHint; hosts may begin retrying a call that was not previously retry-safe.
- `BRK-MCP-MANIFEST-TRUNCATED` — One side is a single page of a paginated tools/list. Every tool past the page boundary reads as removed, so the whole comparison is unsound.
- `BRK-MCP-OPENWORLD-HINT-CHANGED` — openWorldHint changed. It describes the domain a tool reaches into and constrains no caller.
- `BRK-MCP-OUTPUT-SCHEMA-ADDED` — A tool now declares an outputSchema, so its own results must conform to it from this version on.
- `BRK-MCP-OUTPUT-SCHEMA-REMOVED` — A tool stopped declaring an outputSchema; consumers parsing its structuredContent lose the guarantee they were written against.
- `BRK-MCP-READONLY-HINT-CLEARED` — A tool stopped claiming readOnlyHint. A host that auto-approved it as safe to call may now be invoking something that writes.
- `BRK-MCP-READONLY-HINT-SET` — A tool now claims readOnlyHint; hosts may stop asking for confirmation on a claim nobody verified.
- `BRK-MCP-TOOL-DESCRIPTION-CHANGED` — A tool description changed. For an MCP tool the description is the routing input the model reads, not documentation for a human, so a silent edit can redirect an agent (OWASP MCP03, tool poisoning). WARN rather than ERROR because copy edits are routine; raise it with --severity-override if you treat a manifest as supply chain.
- `BRK-MCP-TOOL-RENAME-SUSPECTED` — Exactly one tool disappeared and one appeared with an identical schema. Context for the removal, which is still reported: a manifest carries no identity but the name, so a rename cannot be distinguished from remove-plus-add.
- `BRK-ONEOF-NARROWED` — A protobuf field moved into a oneof; it is now exclusive with the others.
- `BRK-ONEOF-WIDENED` — A protobuf field moved out of a oneof; no existing sender can notice.
- `BRK-PATTERN-PROPERTIES-CHANGED` — The schema applied to properties matching a name pattern was added, removed or changed; a whole family of fields changed shape at once.
- `BRK-PROPERTY-NAMES-CHANGED` — The constraint on what property *names* are allowed changed; keys that used to be accepted may not be.
- `BRK-REQ-BODY-REMOVED` — The request body was removed.
- `BRK-REQ-FIELD-OPTIONALIZED` — A request body field became optional; senders are unaffected.
- `BRK-REQ-FIELD-REMOVED` — A request body field was removed.
- `BRK-REQ-NULLABLE-ADDED` — A request field now accepts null as well (additive).
- `BRK-REQ-NULLABLE-REMOVED` — A request field that accepted null no longer does; payloads that were valid are now rejected.
- `BRK-RESERVATION-REMOVED` — A protobuf field number is no longer reserved and can be reused by mistake.
- `BRK-RESP-CONSTRAINT-LOOSENED` — A bound on a response field was relaxed or removed; the service may now return values a consumer written against the old bound rejects.
- `BRK-RESP-CONSTRAINT-TIGHTENED` — A response constraint was tightened; returned values may fall outside what clients expect.
- `BRK-RESP-NULLABLE-ADDED` — A response value that was never null may now be null; every reader that did not check breaks on the first one, and in a generated client the field changes type at every use site.
- `BRK-RESP-NULLABLE-REMOVED` — A response value can no longer be null (narrowing a response is safe for readers).
- `BRK-RPC-STREAMING-CHANGED` — An RPC changed streaming cardinality; generated clients call it wrongly.
- `BRK-SOAP-ACTION-CHANGED` — The SOAPAction header changed. Gateways and ESBs route on it and generated stubs send the old one, with an unchanged body that now reaches nothing.
- `BRK-SOAP-STYLE-CHANGED` — A binding moved between document and rpc style, which changes how the body is wrapped; every existing client serializes it the old way.
- `BRK-SOAP-VERSION-CHANGED` — A port moved between SOAP 1.1 and 1.2. The envelope namespace and the Content-Type both change, so a 1.1 client gets a 415 rather than a fault.
- `BRK-STREAM-ENCODING-CHANGED` — The encoding of a streamed item changed; the part still arrives and the parser reading it fails.
- `BRK-STREAM-ITEM-SCHEMA-ADDED` — A sequential media type now declares `itemSchema`.
- `BRK-STREAM-ITEM-SCHEMA-REMOVED` — A sequential media type stopped declaring `itemSchema`, so nothing describes one item any more.
- `BRK-STREAM-PREFIX-COUNT-CHANGED` — The number of leading parts in a multipart stream changed; `prefixEncoding` is positional, so a reader counting parts reads the wrong one from there on.
- `BRK-STREAM-SEQUENTIAL-CHANGED` — A payload moved between a single document and a sequence of items; every client has to be rewritten even when the item shape is identical.
- `BRK-TUPLE-SHAPE-CHANGED` — Positional array items changed length or type. Tuple members are read by index, so a change at one position shifts or misparses every reader.

## Fields this export does not write

| Field | Why |
|---|---|
| `fingerprint` | oasdiff hashes its own change identity; a value computed differently would compare unequal to theirs and break the ignore-lists this export exists to preserve |
| `attributes, section, disclaimers` | no equivalent here |

## Contracts that are not OpenAPI

Every finding from a gRPC, GraphQL, AsyncAPI, MCP or WSDL contract is namespaced, whatever its rule. A removed gRPC RPC really is an endpoint removal, but emitting `api-removed-without-deprecation` for one would make a consumer's tooling report an OpenAPI endpoint removal that never happened.

_24 of 79 rules map onto an oasdiff check id; the other 55 are namespaced._
