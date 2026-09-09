# Spec Support Matrix

| Capability | OpenAPI 3.0/3.1 | GraphQL | gRPC | MCP |
|---|---|---|---|---|
| Load + normalize | ✅ files/URLs, JSON/YAML | ✅ SDL | ✅ .proto text | ✅ saved `tools/list` |
| Validation findings | ✅ refs, opIDs, params, dupes | ✅ parse errors | ✅ syntax | ✅ missing/duplicate tools, non-object schemas |
| Semantic diff | ✅ full | ✅ fields/types/nullability/enums | ✅ RPC/field-number/wire-type | ✅ via the shared model |
| Breaking rules | ✅ shared catalog | ✅ structural subset | ✅ structural subset | ✅ shared catalog + `BRK-MCP-*` |
| Schema-driven testing | ✅ | 📋 v0.2 | 📋 v0.2 | 📋 |
| Mock server | ✅ | 📋 | 📋 | 📋 |
| Drift detection | ✅ live + recorded | 📋 | 📋 reflection-based | 📋 |
| Coverage | ✅ | 📋 | 📋 | 📋 |

Rule counts are deliberately not written here -- this table said "35 rules"
while the catalog held 44, and then 57. The live list is
[`docs/rule-catalog.md`](rule-catalog.md), generated from the code, or
`apiverity rules --json`.

Prior art this project learns from (independently implemented):
oasdiff / openapi-diff (spec diffing), Schemathesis (schema-driven fuzzing),
Dredd (contract testing), Protocompile/buf (proto breaking checks),
graphql-inspector (GraphQL diffing), har-sanitizer tooling, and
hypothesis for property-based generation.