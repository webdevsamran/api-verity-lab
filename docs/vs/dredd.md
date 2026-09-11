# api-verity-lab compared with Dredd

<!-- generated:landing -->

Generated from `data/competitive-capabilities.json`, which is gathered by
`scripts/fetch_competitor_meta.py`. Repository facts below were fetched 2026-09-09.

| | |
|---|---|
| Repository | [apiaryio/dredd](https://github.com/apiaryio/dredd) |
| Licence | MIT |
| Stars | 4222 |
| Latest release | dredd@14.1.0 |
| Deployment | CLI (Node.js) |
| Audience | (historical) docs-driven HTTP API testing |

## What Dredd is good at

- Simple docs-as-tests idea

That list is from the evidence file, not from this project's opinion of Dredd.
A comparison page that only enumerated the other tool's gaps would be an
advertisement, and this project's whole credibility rests on claims a reader can
check.

## Where it stops

- ARCHIVED (verified): no maintenance since 2024; OpenAPI 3.1 unsupported

## Protocols

**Dredd:** API Blueprint, OpenAPI 2.0, Swagger

**api-verity-lab:** OpenAPI 3.0/3.1/3.2, Swagger 2.0, AsyncAPI 2.x/3.x, GraphQL SDL, gRPC (proto and descriptor sets), MCP tool manifests, WSDL 1.1.

## Capability by capability

| | Dredd | api-verity-lab |
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
| mock server | no | yes — `apiverity mock` |
| openapi diff | no | yes — `apiverity diff` |
| otel export | no | yes — `apiverity test --otlp-endpoint` |
| performance budgets | no | yes — `apiverity regression` |
| plugin api | yes (hooks) | yes — `apiverity plugins` |
| rbac audit | no | yes — `apiverity audit` |
| response validation | yes | yes — `apiverity test` |
| sarif export | no | yes — `apiverity report --format sarif` |
| schema driven fuzzing | partial (documented example requests) | yes — `apiverity test` |
| self hosted server | no | yes — `apiverity serve` |
| semver verdicts | no | yes — `apiverity breaking --check-semver` |
| service virtualization | no | yes — `apiverity mock --workspace` |
| stateful workflows | partial (resource shorthands) | yes — `apiverity workflow` |
| traffic replay | no | yes — `apiverity replay` |

The Dredd column is `yes` / `partial` / `no` / `unknown` from the evidence file,
with `no` recorded only where the absence is verifiable or the area is clearly
outside that product's documented scope; the legend and the evidence notes are in
the data file. The api-verity-lab column names the command that provides each one,
because that column is not in the evidence file -- it was gathered to describe other
tools -- and an unsourced `yes` in every row is the thing this project exists to not
do. A test asserts every command named there exists.

## Using both

Nothing here argues for replacing Dredd. A tool that owns its lane is worth using
in it; this project's claim is a different one -- one contract model and one result
format across every protocol you speak, including the ones your agents speak.

[The full comparison](../competitive-analysis.md) covers every tool at once, and
[the benchmark](../benchmark.md) is reproducible, including where this project
loses.
