---
description: >-
  Which specification versions api-verity-lab reads, how a document is detected, and exactly what each format supports -- OpenAPI 3.0 to 3.2 through WSDL 1.1.
---

# Spec Support Matrix

| Capability | OpenAPI 3.0/3.1/3.2 | GraphQL | gRPC | MCP | WSDL 1.1 / SOAP |
|---|---|---|---|---|---|
| Load + normalize | ✅ files/URLs, JSON/YAML; 3.2 `query`, `additionalOperations`, `querystring`, tag hierarchy, device flow, `itemSchema`/`itemEncoding`/`prefixEncoding` ([streaming](streaming.md)) | ✅ SDL | ✅ .proto text | ✅ saved `tools/list` | ✅ portTypes, bindings, ports, and the XSD subset below |
| Validation findings | ✅ refs, opIDs, params, dupes | ✅ parse errors | ✅ syntax | ✅ missing/duplicate tools, non-object schemas | ✅ `SPEC-WSDL-*`: unresolved names, unmodelled constructs, unbound portTypes, encoded bodies |
| Semantic diff | ✅ full | ✅ fields/types/nullability/enums | ✅ RPC/field-number/wire-type | ✅ via the shared model | ✅ via the shared model |
| Breaking rules | ✅ shared catalog | ✅ structural subset | ✅ structural subset | ✅ shared catalog + `BRK-MCP-*` | ✅ shared catalog + `BRK-SOAP-*` |
| Schema-driven testing | ✅ | 📋 v0.2 | 📋 v0.2 | 📋 | ❌ the generators emit JSON, not SOAP envelopes |
| Mock server | ✅ | 📋 | 📋 | 📋 | ❌ |
| Drift detection | ✅ live + recorded | 📋 | 📋 reflection-based | 📋 | ❌ |
| Coverage | ✅ | 📋 | 📋 | 📋 | ❌ |

## Naming the format

Detection is content sniffing: `openapi:` makes a document OpenAPI, `type Query`
makes it GraphQL, a `service` declaration makes it gRPC. A document that merely
*mentions* the wrong word — a GraphQL schema whose comment discusses the OpenAPI
gateway in front of it — was unloadable by any means, and failed as a parse
error about a format nobody asked for.

`--spec-format {openapi,swagger2,asyncapi,graphql,grpc,mcp,wsdl}` skips detection.
It is keyed on the format rather than the protocol, because OpenAPI and Swagger
2.0 share one protocol and are exactly the pair a caller needs to disambiguate.

Detection is skipped, not reordered: an override that only moved a plugin to
the front would still fall through when that plugin declined, which is the
misdetection being overridden, reached a second time and now silently. So a
document named as a format that cannot read it fails *as that format*.

When the override contradicts detection the load is honoured and a
`SPEC-FORMAT-OVERRIDDEN` WARN says so — the caller may know something the
sniffer does not, and the other explanation is a typo in the flag. An override
that agrees with detection is silent, because a warning on every correct use is
a warning people learn to ignore.

## Multi-file contracts

An entry document with a `schemas/` directory beside it, and often a
`../../shared/` tree in a monorepo, is the normal shape of a real OpenAPI
contract. Every `$ref` into one of those used to produce `SPEC-REF-EXTERNAL`
and resolve to nothing — and the nothing is the part that mattered. The schema
behind the ref was **absent from the model**, so the differ compared two
absences and reported no change, and `validate_value` accepted anything at that
position.

Relative file refs are followed now, resolved against whichever document
contains them (not against the entry document), with the fragments hoisted into
`components.schemas` under deterministic, checkout-independent names — so the
next diff on another machine does not call every schema renamed. Findings name
the file the schema actually lives in, with a real line number.

Two things are refused, each with a finding that names the reference:

| Refused | Why |
|---|---|
| An absolute filesystem path (`/etc/passwd`, `C:\...`) | A portable contract never contains one, so refusing it costs nothing real. Following it would let a *document* choose which file this process reads. |
| A `$ref` naming a URL, unless `--allow-remote-refs` | It makes this process request an address the caller never chose — the hazard [`SAFETY_MODEL.md`](safety-model.md) §1 exists for. With the flag, the fetch really happens; a flag that changed nothing would be worse than no flag. |

A reference cycle across files terminates, and both the file count and the
number of remote fetches are capped, with the cap reported rather than applied
silently.

## JSON Schema 2020-12 keywords

Schemas in every one of the seven formats normalize into the same `SchemaNode`,
so a keyword the model does not carry is dropped for all of them at once. That
is worse than it sounds: a dropped keyword does not fail, it *narrows what the
contract says* without telling anyone. The differ then reports a tightened
contract as unchanged, and `validate_value` accepts data the document forbids.

**Modelled, diffed and enforced:** `type`, `enum`, `const`, `format`,
`required`, `properties`, `additionalProperties`, `items`, `prefixItems`,
`contains` with `minContains`/`maxContains`, `patternProperties`,
`propertyNames`, `dependentRequired`, `dependentSchemas`,
`if`/`then`/`else`, `allOf`, `anyOf`, `oneOf`, `not`, `nullable`, `default`,
and the numeric, string, array and object bounds.

**Not modelled, and why.** These four are named rather than left to be
discovered, and `apiverity validate` on an MCP manifest reports any schema that
uses one:

| Keyword | Why it is not modelled |
|---|---|
| `unevaluatedProperties` | Its meaning depends on which *other* keywords already matched a property, across `allOf`/`anyOf`/`oneOf`/`if` branches. It cannot be evaluated against a single node; it needs an annotation-collecting evaluator, which is a different validator from the one here. |
| `unevaluatedItems` | The same, for array positions. |
| `$dynamicRef` | Resolves against a dynamic scope built from the chain of schemas being applied at the time, not from the document. Two documents that look identical can resolve it differently. |
| `$dynamicAnchor` | The other half of that mechanism. |

Implementing them without an annotation-collecting evaluator would mean
guessing, and a guessed constraint in a contract tool is worse than a declared
gap: it produces findings that are confidently wrong.

## WSDL 1.1 and SOAP

A WSDL is read into the same `Service`/`Operation`/`SchemaNode` model as
everything else, so the shared catalogue applies without a rule being written
for it: a removed operation is `BRK-RPC-REMOVED`, a newly required element is
`BRK-REQ-FIELD-ADDED-REQUIRED`, a removed enumeration value is
`BRK-ENUM-NARROWED-RESPONSE`.

**A DOCTYPE is refused, not expanded.** `xml.etree.ElementTree` on this Python
refuses external entities — an entity naming `file:///etc/passwd` raises
`undefined entity` rather than reading the file — but it *does* expand internal
ones, which is the billion-laughs shape. Both halves are asserted by tests that
run the parser rather than quote a changelog. So a document declaring a DTD at
all is refused at the declaration, before an entity is expanded. A WSDL has no
legitimate use for a DTD; its schema language is XSD.

**Identity.** Operations are keyed `portType.operation`, not by method and
path: every operation on a port shares one URL and one HTTP verb, so keying on
those would collapse a whole service into a single entry. `method` and `path`
are left unset for the same reason, and the endpoint address becomes a
`Server`.

**Faults.** A SOAP fault comes back as HTTP 500, and so does every other fault
on the same operation — keying responses by HTTP status would silently merge
them. The status carried is `fault:<name>`; the shared HTTP status is in
`bindings["soap"]["fault_http_status"]`.

**The three facts no schema rule can see.** `SOAPAction`, the binding style and
the SOAP version live in `bindings["soap"]`, and each can change while every
message schema stays byte for byte identical — so each has a rule:
`BRK-SOAP-ACTION-CHANGED`, `BRK-SOAP-STYLE-CHANGED`, `BRK-SOAP-VERSION-CHANGED`.
SOAPAction is the one that forced it: an ESB routes on that header, and moving
it is a one-word edit that leaves the entire body identical.

### The XSD subset

**Modelled:** `element` with `type`, `ref`, `minOccurs`, `maxOccurs`,
`nillable`, `default` and `fixed`; `complexType` with `sequence`, `all` and
`choice`; `complexContent`/`extension` (the base type's members are merged in);
`simpleContent`/`extension` (the text value becomes a `#text` member);
`simpleType`/`restriction` with `enumeration`, `length`, `minLength`,
`maxLength`, `pattern`, `minInclusive`, `maxInclusive`, `minExclusive` and
`maxExclusive`; `attribute` with `use`, `default` and `fixed`; `any` and
`anyAttribute`; and the builtin scalar types.

Two normalizations worth knowing, because both are visible in a diff:

| XSD | Model | Why |
|---|---|---|
| `xs:choice` | `oneofs` — the members as optional properties, plus the exclusivity | `xs:choice` is exactly-one-of, which the model already names for protobuf. Carrying the members as plain optional properties would drop the exclusivity, so a field moving into or out of a choice would read as no change. |
| `xs:attribute name="scale"` | a property named `@scale` | An XML element name cannot begin with `@`, so the prefix cannot collide with a child element of the same name. |

**Not modelled.** Each of these emits `SPEC-WSDL-UNMODELLED` naming the
construct and the element it was on, so the gap arrives as a finding rather
than as a diff that quietly reported nothing:

| Construct | Why it is not modelled |
|---|---|
| `xs:group`, `xs:attributeGroup` | Named particle reuse. Resolving them is mechanical, but shipping them unread-and-reported beats shipping them half-read. |
| `xs:union`, `xs:list` | A value whose type is a choice of types, or a whitespace-separated sequence of them. `SchemaNode` carries one `type`. |
| `complexContent/restriction`, `simpleContent/restriction` | Restriction *removes* members from a base type, so the derived type is not the base plus something — it needs the base walked and subtracted, and getting that subtly wrong produces confidently wrong findings. |
| `substitutionGroup` | A different element may appear in this position, and which one is decided by the instance document rather than the schema. |
| `xs:import`, `xs:include` | Another schema document is not followed. Reported as `SPEC-WSDL-EXTERNAL-SCHEMA`, because the types in it resolve to nothing and the differ would otherwise compare two absences. |
| `xsi:type` polymorphism | Chosen per instance, like `substitutionGroup`. |
| `totalDigits`, `fractionDigits` | No model field, and approximating them with a `pattern` this parser invented would be a constraint nobody wrote. |
| `whiteSpace` | A normalization directive rather than a constraint on the value set. |
| SOAP section-5 encoding (`use="encoded"`) | The body on the wire is an object graph the schema does not describe. Reported as `SPEC-WSDL-ENCODED`: the modelled shape is the declared one, not the transmitted one. |
| HTTP GET/POST and MIME bindings | Not SOAP. A port using one is reported as `SPEC-WSDL-NO-SOAP-BINDING` and produces no operations. |
| WSDL 2.0 | A different element vocabulary. Refused by name rather than read wrong. |

A portType no service port reaches produces `SPEC-WSDL-PORTTYPE-UNBOUND` and no
operations — nothing can call it. A document with no `wsdl:service` at all is
the abstract-interface shape, and its portTypes are compiled directly, with
`SPEC-WSDL-NO-SERVICE` saying no address is known.

Findings carry real line numbers. `ElementTree` exposes no position at all, so
they come from a second expat pass paired with the tree by document order;
guessing a line by searching the text for a name would point at the wrong one
of five identical `name="id"` attributes, which is worse than saying nothing.

Rule counts are deliberately not written here -- this table said "35 rules"
while the catalog held 44, and then 57. The live list is
[`docs/rule-catalog.md`](rule-catalog.md), generated from the code, or
`apiverity rules --json`.

Prior art this project learns from (independently implemented):
oasdiff / openapi-diff (spec diffing), Schemathesis (schema-driven fuzzing),
Dredd (contract testing), Protocompile/buf (proto breaking checks),
graphql-inspector (GraphQL diffing), har-sanitizer tooling, and
hypothesis for property-based generation.