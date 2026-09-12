---
description: >-
  api-verity-lab compared with WireMock, from dated GitHub evidence: service virtualization against contract governance, and where the two overlap.
---

# api-verity-lab compared with WireMock

<!-- generated:landing -->

Generated from `data/competitive-capabilities.json`, which is gathered by
`scripts/fetch_competitor_meta.py`. Repository facts below were fetched 2026-09-09.

| | |
|---|---|
| Repository | [wiremock/wiremock](https://github.com/wiremock/wiremock) |
| Licence | Apache-2.0 |
| Stars | 7342 |
| Latest release | 3.13.2 |
| Deployment | Embedded Java library, standalone JAR, Docker |
| Audience | Java/JVM integration testers; API simulators |

## What WireMock is good at

- Deep HTTP simulation incl. faults/delays/scenarios

That list is from the evidence file, not from this project's opinion of WireMock.
A comparison page that only enumerated the other tool's gaps would be an
advertisement, and this project's whole credibility rests on claims a reader can
check.

## Where it stops

- JVM-centric; stubs are hand-authored rather than derived from contracts; no governance/diff/perf workflow

## Protocols

**WireMock:** HTTP/HTTPS, Webhooks, gRPC (experimental since 3.x - KNOWLEDGE-BASED)

**api-verity-lab:** OpenAPI 3.0/3.1/3.2, Swagger 2.0, AsyncAPI 2.x/3.x, GraphQL SDL, gRPC (proto and descriptor sets), MCP tool manifests, WSDL 1.1.

## Capability by capability

| | WireMock | api-verity-lab |
|---|---|---|
| asyncapi support | no | yes — `apiverity breaking` |
| breaking change rules | no | yes — `apiverity breaking` |
| broker publication | no | no |
| can i deploy | no | yes — `apiverity serve (/v1/can-i-deploy)` |
| consumer contracts | no | yes — `apiverity breaking --consumers` |
| drift detection | no | yes — `apiverity drift` |
| frontend ui | partial (admin API/UI) | yes — `apiverity serve (web/)` |
| graphql breaking | no | yes — `apiverity breaking` |
| grpc compat | partial (experimental gRPC) | yes — `apiverity breaking` |
| linting | no | yes — `apiverity validate` |
| load testing | no | yes — `apiverity regression --shape` |
| mock server | yes | yes — `apiverity mock` |
| openapi diff | no | yes — `apiverity diff` |
| otel export | no | yes — `apiverity test --otlp-endpoint` |
| performance budgets | no | yes — `apiverity regression` |
| plugin api | yes (extensions) | yes — `apiverity plugins` |
| rbac audit | no | yes — `apiverity audit` |
| response validation | partial (request matching) | yes — `apiverity test` |
| sarif export | no | yes — `apiverity report --format sarif` |
| schema driven fuzzing | no | yes — `apiverity test` |
| self hosted server | yes (standalone server) | yes — `apiverity serve` |
| semver verdicts | no | yes — `apiverity breaking --check-semver` |
| service virtualization | yes | yes — `apiverity mock --workspace` |
| stateful workflows | partial (scenario state machine) | yes — `apiverity workflow` |
| traffic replay | yes (record/playback) | yes — `apiverity replay` |

The WireMock column is `yes` / `partial` / `no` / `unknown` from the evidence file,
with `no` recorded only where the absence is verifiable or the area is clearly
outside that product's documented scope; the legend and the evidence notes are in
the data file. The api-verity-lab column names the command that provides each one,
because that column is not in the evidence file -- it was gathered to describe other
tools -- and an unsourced `yes` in every row is the thing this project exists to not
do. A test asserts every command named there exists.

## Using both

Nothing here argues for replacing WireMock. A tool that owns its lane is worth using
in it; this project's claim is a different one -- one contract model and one result
format across every protocol you speak, including the ones your agents speak.

[The full comparison](../competitive-analysis.md) covers every tool at once, and
[the benchmark](../benchmark.md) is reproducible, including where this project
loses.
