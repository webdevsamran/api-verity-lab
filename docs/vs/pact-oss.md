---
description: >-
  api-verity-lab compared with Pact, from dated GitHub evidence: consumer-driven contracts and a broker against contract diffing and runtime drift.
---

# api-verity-lab compared with Pact (OSS)

<!-- generated:landing -->

Generated from `data/competitive-capabilities.json`, which is gathered by
`scripts/fetch_competitor_meta.py`. Repository facts below were fetched 2026-09-09.

| | |
|---|---|
| Repository | [pact-foundation/pact-js](https://github.com/pact-foundation/pact-js) |
| Licence | NOASSERTION (MIT-family per repo docs; multi-language implementations) |
| Stars | 1801 |
| Latest release | v17.1.2 |
| Deployment | Language libraries + self-hostable Pact Broker (OSS); PactFlow is the commercial distribution |
| Audience | Consumer-driven contract testing teams |

## What Pact (OSS) is good at

- Mature consumer/provider workflow
- can-i-deploy environment-aware gating

That list is from the evidence file, not from this project's opinion of Pact (OSS).
A comparison page that only enumerated the other tool's gaps would be an
advertisement, and this project's whole credibility rests on claims a reader can
check.

## Where it stops

- Requires consumer test authoring; no schema-derived fuzzing/diff of specs; broker ops burden self-hosted

## Protocols

**Pact (OSS):** HTTP, async messaging, gRPC (via plugins), GraphQL (provider verification)

**api-verity-lab:** OpenAPI 3.0/3.1/3.2, Swagger 2.0, AsyncAPI 2.x/3.x, GraphQL SDL, gRPC (proto and descriptor sets), MCP tool manifests, WSDL 1.1.

## Capability by capability

| | Pact (OSS) | api-verity-lab |
|---|---|---|
| asyncapi support | yes (messaging) | yes — `apiverity breaking` |
| breaking change rules | yes (verification-based) | yes — `apiverity breaking` |
| broker publication | yes (self-hostable Pact Broker) | no |
| can i deploy | yes | yes — `apiverity serve (/v1/can-i-deploy)` |
| consumer contracts | yes | yes — `apiverity breaking --consumers` |
| drift detection | no | yes — `apiverity drift` |
| frontend ui | partial (basic broker UI) | yes — `apiverity serve (web/)` |
| graphql breaking | partial | yes — `apiverity breaking` |
| grpc compat | partial (protobuf plugin) | yes — `apiverity breaking` |
| linting | no | yes — `apiverity validate` |
| load testing | no | yes — `apiverity regression --shape` |
| mock server | yes (consumer-side mock) | yes — `apiverity mock` |
| openapi diff | no | yes — `apiverity diff` |
| otel export | no | yes — `apiverity test --otlp-endpoint` |
| performance budgets | no | yes — `apiverity regression` |
| plugin api | yes (plugins framework) | yes — `apiverity plugins` |
| rbac audit | partial (broker tokens; full RBAC in PactFlow) | yes — `apiverity audit` |
| response validation | yes (matching rules) | yes — `apiverity test` |
| sarif export | no | yes — `apiverity report --format sarif` |
| schema driven fuzzing | partial (generates requests from consumer expectations) | yes — `apiverity test` |
| self hosted server | yes (Pact Broker) | yes — `apiverity serve` |
| semver verdicts | no | yes — `apiverity breaking --check-semver` |
| service virtualization | no | yes — `apiverity mock --workspace` |
| stateful workflows | no | yes — `apiverity workflow` |
| traffic replay | no | yes — `apiverity replay` |

The Pact (OSS) column is `yes` / `partial` / `no` / `unknown` from the evidence file,
with `no` recorded only where the absence is verifiable or the area is clearly
outside that product's documented scope; the legend and the evidence notes are in
the data file. The api-verity-lab column names the command that provides each one,
because that column is not in the evidence file -- it was gathered to describe other
tools -- and an unsourced `yes` in every row is the thing this project exists to not
do. A test asserts every command named there exists.

## Using both

Nothing here argues for replacing Pact (OSS). A tool that owns its lane is worth using
in it; this project's claim is a different one -- one contract model and one result
format across every protocol you speak, including the ones your agents speak.

[The full comparison](../competitive-analysis.md) covers every tool at once, and
[the benchmark](../benchmark.md) is reproducible, including where this project
loses.
