# api-verity-lab compared with Postman/Newman

<!-- generated:landing -->

Generated from `data/competitive-capabilities.json`, which is gathered by
`scripts/fetch_competitor_meta.py`. Repository facts below were fetched 2026-09-09.

| | |
|---|---|
| Repository | [postmanlabs/newman](https://github.com/postmanlabs/newman) |
| Licence | Apache-2.0 |
| Stars | 7246 |
| Deployment | Newman = OSS CLI; Postman platform (collections, mocks, monitors, collaboration) is hosted/commercial |
| Audience | Postman-centric QA teams |

## What Postman/Newman is good at

- Huge ecosystem and UX investment

That list is from the evidence file, not from this project's opinion of Postman/Newman.
A comparison page that only enumerated the other tool's gaps would be an
advertisement, and this project's whole credibility rests on claims a reader can
check.

## Where it stops

- Collaboration locked to hosted platform; collections are not normalized contracts; no spec-level compatibility semantics

## Protocols

**Postman/Newman:** HTTP, WebSocket (Postman), gRPC (Postman desktop)

**api-verity-lab:** OpenAPI 3.0/3.1/3.2, Swagger 2.0, AsyncAPI 2.x/3.x, GraphQL SDL, gRPC (proto and descriptor sets), MCP tool manifests, WSDL 1.1.

## Capability by capability

| | Postman/Newman | api-verity-lab |
|---|---|---|
| asyncapi support | no | yes — `apiverity breaking` |
| breaking change rules | no | yes — `apiverity breaking` |
| broker publication | partial (hosted workspace publishing) | no |
| can i deploy | no | yes — `apiverity serve (/v1/can-i-deploy)` |
| consumer contracts | no | yes — `apiverity breaking --consumers` |
| drift detection | no | yes — `apiverity drift` |
| frontend ui | yes (full hosted app) | yes — `apiverity serve (web/)` |
| graphql breaking | no | yes — `apiverity breaking` |
| grpc compat | partial (desktop client) | yes — `apiverity breaking` |
| linting | no | yes — `apiverity validate` |
| load testing | no | yes — `apiverity regression --shape` |
| mock server | partial (hosted Postman mocks) | yes — `apiverity mock` |
| openapi diff | no | yes — `apiverity diff` |
| otel export | no | yes — `apiverity test --otlp-endpoint` |
| performance budgets | no | yes — `apiverity regression` |
| plugin api | partial (reporters) | yes — `apiverity plugins` |
| rbac audit | partial (hosted roles) | yes — `apiverity audit` |
| response validation | yes (test scripts) | yes — `apiverity test` |
| sarif export | no | yes — `apiverity report --format sarif` |
| schema driven fuzzing | no | yes — `apiverity test` |
| self hosted server | no | yes — `apiverity serve` |
| semver verdicts | no | yes — `apiverity breaking --check-semver` |
| service virtualization | no | yes — `apiverity mock --workspace` |
| stateful workflows | partial (collection chaining) | yes — `apiverity workflow` |
| traffic replay | no | yes — `apiverity replay` |

The Postman/Newman column is `yes` / `partial` / `no` / `unknown` from the evidence file,
with `no` recorded only where the absence is verifiable or the area is clearly
outside that product's documented scope; the legend and the evidence notes are in
the data file. The api-verity-lab column names the command that provides each one,
because that column is not in the evidence file -- it was gathered to describe other
tools -- and an unsourced `yes` in every row is the thing this project exists to not
do. A test asserts every command named there exists.

## Using both

Nothing here argues for replacing Postman/Newman. A tool that owns its lane is worth using
in it; this project's claim is a different one -- one contract model and one result
format across every protocol you speak, including the ones your agents speak.

[The full comparison](../competitive-analysis.md) covers every tool at once, and
[the benchmark](../benchmark.md) is reproducible, including where this project
loses.
