# Spec Support Matrix

| Capability | OpenAPI 3.0/3.1/3.2 | GraphQL | gRPC | MCP |
|---|---|---|---|---|
| Load + normalize | ✅ files/URLs, JSON/YAML; 3.2 `query`, `additionalOperations`, `querystring`, tag hierarchy, device flow | ✅ SDL | ✅ .proto text | ✅ saved `tools/list` |
| Validation findings | ✅ refs, opIDs, params, dupes | ✅ parse errors | ✅ syntax | ✅ missing/duplicate tools, non-object schemas |
| Semantic diff | ✅ full | ✅ fields/types/nullability/enums | ✅ RPC/field-number/wire-type | ✅ via the shared model |
| Breaking rules | ✅ shared catalog | ✅ structural subset | ✅ structural subset | ✅ shared catalog + `BRK-MCP-*` |
| Schema-driven testing | ✅ | 📋 v0.2 | 📋 v0.2 | 📋 |
| Mock server | ✅ | 📋 | 📋 | 📋 |
| Drift detection | ✅ live + recorded | 📋 | 📋 reflection-based | 📋 |
| Coverage | ✅ | 📋 | 📋 | 📋 |

## JSON Schema 2020-12 keywords

Schemas in every one of the six formats normalize into the same `SchemaNode`,
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

Rule counts are deliberately not written here -- this table said "35 rules"
while the catalog held 44, and then 57. The live list is
[`docs/rule-catalog.md`](rule-catalog.md), generated from the code, or
`apiverity rules --json`.

Prior art this project learns from (independently implemented):
oasdiff / openapi-diff (spec diffing), Schemathesis (schema-driven fuzzing),
Dredd (contract testing), Protocompile/buf (proto breaking checks),
graphql-inspector (GraphQL diffing), har-sanitizer tooling, and
hypothesis for property-based generation.