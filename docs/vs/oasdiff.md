---
description: >-
  api-verity-lab compared with oasdiff, from dated GitHub evidence: what each covers, where oasdiff is stronger, and what migrating actually costs.
---

# api-verity-lab compared with oasdiff

<!-- generated:landing -->

Generated from `data/competitive-capabilities.json`, which is gathered by
`scripts/fetch_competitor_meta.py`. Repository facts below were fetched 2026-09-09.

| | |
|---|---|
| Repository | [oasdiff/oasdiff](https://github.com/oasdiff/oasdiff) |
| Licence | Apache-2.0 |
| Stars | 1327 |
| Latest release | v1.29.1 |
| Deployment | CLI/library/Docker; optional hosted diff endpoint |
| Audience | Backend/API teams doing OpenAPI change detection in CI |

## What oasdiff is good at

- Focused, fast, well-maintained
- Good breaking-change rule coverage for HTTP

That list is from the evidence file, not from this project's opinion of oasdiff.
A comparison page that only enumerated the other tool's gaps would be an
advertisement, and this project's whole credibility rests on claims a reader can
check.

## Where it stops

- Single-purpose: no testing, drift, replay, performance, or broker workflows

## Protocols

**oasdiff:** OpenAPI 3.x, OpenAPI/Swagger 2.0

**api-verity-lab:** OpenAPI 3.0/3.1/3.2, Swagger 2.0, AsyncAPI 2.x/3.x, GraphQL SDL, gRPC (proto and descriptor sets), MCP tool manifests, WSDL 1.1.

## Capability by capability

| | oasdiff | api-verity-lab |
|---|---|---|
| asyncapi support | unknown | yes — `apiverity breaking` |
| breaking change rules | yes | yes — `apiverity breaking` |
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
| openapi diff | yes | yes — `apiverity diff` |
| otel export | no | yes — `apiverity test --otlp-endpoint` |
| performance budgets | no | yes — `apiverity regression` |
| plugin api | no | yes — `apiverity plugins` |
| rbac audit | no | yes — `apiverity audit` |
| response validation | no | yes — `apiverity test` |
| sarif export | unknown | yes — `apiverity report --format sarif` |
| schema driven fuzzing | no | yes — `apiverity test` |
| self hosted server | no | yes — `apiverity serve` |
| semver verdicts | unknown | yes — `apiverity breaking --check-semver` |
| service virtualization | no | yes — `apiverity mock --workspace` |
| stateful workflows | no | yes — `apiverity workflow` |
| traffic replay | no | yes — `apiverity replay` |

The oasdiff column is `yes` / `partial` / `no` / `unknown` from the evidence file,
with `no` recorded only where the absence is verifiable or the area is clearly
outside that product's documented scope; the legend and the evidence notes are in
the data file. The api-verity-lab column names the command that provides each one,
because that column is not in the evidence file -- it was gathered to describe other
tools -- and an unsourced `yes` in every row is the thing this project exists to not
do. A test asserts every command named there exists.

## Using both

Nothing here argues for replacing oasdiff. A tool that owns its lane is worth using
in it; this project's claim is a different one -- one contract model and one result
format across every protocol you speak, including the ones your agents speak.

[The full comparison](../competitive-analysis.md) covers every tool at once, and
[the benchmark](../benchmark.md) is reproducible, including where this project
loses.
