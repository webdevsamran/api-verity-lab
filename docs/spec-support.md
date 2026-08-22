# Spec Support Matrix

| Capability | OpenAPI 3.0/3.1 | GraphQL | gRPC |
|---|---|---|---|
| Load + normalize | ✅ files/URLs, JSON/YAML | ✅ SDL | ✅ .proto text |
| Validation findings | ✅ refs, opIDs, params, dupes | ✅ parse errors | ✅ syntax |
| Semantic diff | ✅ full | ✅ fields/types/nullability/enums | ✅ RPC/field-number/wire-type |
| Breaking rules | ✅ 35 rules | ✅ structural subset | ✅ structural subset |
| Schema-driven testing | ✅ | 📋 v0.2 | 📋 v0.2 |
| Mock server | ✅ | 📋 | 📋 |
| Drift detection | ✅ live + recorded | 📋 | 📋 reflection-based |
| Coverage | ✅ | 📋 | 📋 |

Prior art this project learns from (independently implemented):
oasdiff / openapi-diff (spec diffing), Schemathesis (schema-driven fuzzing),
Dredd (contract testing), Protocompile/buf (proto breaking checks),
graphql-inspector (GraphQL diffing), har-sanitizer tooling, and
hypothesis for property-based generation.