# api-verity-lab compared with Prism

<!-- generated:landing -->

Generated from `data/competitive-capabilities.json`, which is gathered by
`scripts/fetch_competitor_meta.py`. Repository facts below were fetched 2026-09-09.

| | |
|---|---|
| Repository | [stoplightio/prism](https://github.com/stoplightio/prism) |
| Licence | Apache-2.0 |
| Stars | 5012 |
| Latest release | v5.16.0 |
| Deployment | CLI (Node.js) |
| Audience | Frontend/QA needing a spec-accurate mock server |

## What Prism is good at

- Spec-accurate mocking with validation

That list is from the evidence file, not from this project's opinion of Prism.
A comparison page that only enumerated the other tool's gaps would be an
advertisement, and this project's whole credibility rests on claims a reader can
check.

## Where it stops

- Mocking only: no scenarios/state persistence, no governance/testing suite

## Protocols

**Prism:** OpenAPI 2/3, Postman Collections

**api-verity-lab:** OpenAPI 3.0/3.1/3.2, Swagger 2.0, AsyncAPI 2.x/3.x, GraphQL SDL, gRPC (proto and descriptor sets), MCP tool manifests, WSDL 1.1.

## Capability by capability

| | Prism | api-verity-lab |
|---|---|---|
| asyncapi support | no | yes — `apiverity breaking` |
| breaking change rules | no | yes — `apiverity breaking` |
| broker publication | no | no |
| can i deploy | no | yes — `apiverity serve (/v1/can-i-deploy)` |
| consumer contracts | no | yes — `apiverity breaking --consumers` |
| drift detection | no | yes — `apiverity drift` |
| frontend ui | no | yes — `apiverity serve (web/)` |
| graphql breaking | no | yes — `apiverity breaking` |
| grpc compat | no | yes — `apiverity breaking` |
| linting | no | yes — `apiverity validate` |
| load testing | no | yes — `apiverity regression --shape` |
| mock server | yes | yes — `apiverity mock` |
| openapi diff | no | yes — `apiverity diff` |
| otel export | no | yes — `apiverity test --otlp-endpoint` |
| performance budgets | no | yes — `apiverity regression` |
| plugin api | no | yes — `apiverity plugins` |
| rbac audit | no | yes — `apiverity audit` |
| response validation | yes (in mock/proxy) | yes — `apiverity test` |
| sarif export | no | yes — `apiverity report --format sarif` |
| schema driven fuzzing | no | yes — `apiverity test` |
| self hosted server | no | yes — `apiverity serve` |
| semver verdicts | no | yes — `apiverity breaking --check-semver` |
| service virtualization | partial (proxy mode) | yes — `apiverity mock --workspace` |
| stateful workflows | no | yes — `apiverity workflow` |
| traffic replay | partial (proxy recording) | yes — `apiverity replay` |

The Prism column is `yes` / `partial` / `no` / `unknown` from the evidence file,
with `no` recorded only where the absence is verifiable or the area is clearly
outside that product's documented scope; the legend and the evidence notes are in
the data file. The api-verity-lab column names the command that provides each one,
because that column is not in the evidence file -- it was gathered to describe other
tools -- and an unsourced `yes` in every row is the thing this project exists to not
do. A test asserts every command named there exists.

## Using both

Nothing here argues for replacing Prism. A tool that owns its lane is worth using
in it; this project's claim is a different one -- one contract model and one result
format across every protocol you speak, including the ones your agents speak.

[The full comparison](../competitive-analysis.md) covers every tool at once, and
[the benchmark](../benchmark.md) is reproducible, including where this project
loses.
