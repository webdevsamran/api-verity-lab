# api-verity-lab compared with Spectral

<!-- generated:landing -->

Generated from `data/competitive-capabilities.json`, which is gathered by
`scripts/fetch_competitor_meta.py`. Repository facts below were fetched 2026-09-09.

| | |
|---|---|
| Repository | [stoplightio/spectral](https://github.com/stoplightio/spectral) |
| Licence | Apache-2.0 |
| Stars | 3186 |
| Latest release | v6.16.3 |
| Deployment | CLI/library/VS Code extension |
| Audience | API governance/style-guide authors |

## What Spectral is good at

- De-facto standard linter
- Rich built-in ruleset (oas)

That list is from the evidence file, not from this project's opinion of Spectral.
A comparison page that only enumerated the other tool's gaps would be an
advertisement, and this project's whole credibility rests on claims a reader can
check.

## Where it stops

- Linting only: no compatibility semantics, testing, runtime, or deployment decisions

## Protocols

**Spectral:** OpenAPI 2.0/3.0/3.1, Arazzo 1.0, AsyncAPI 2.x (per repo description)

**api-verity-lab:** OpenAPI 3.0/3.1/3.2, Swagger 2.0, AsyncAPI 2.x/3.x, GraphQL SDL, gRPC (proto and descriptor sets), MCP tool manifests, WSDL 1.1.

## Capability by capability

| | Spectral | api-verity-lab |
|---|---|---|
| asyncapi support | partial (AsyncAPI v2 rulesets per VERIFIED description) | yes — `apiverity breaking` |
| breaking change rules | no | yes — `apiverity breaking` |
| broker publication | no | no |
| can i deploy | no | yes — `apiverity serve (/v1/can-i-deploy)` |
| consumer contracts | no | yes — `apiverity breaking --consumers` |
| drift detection | no | yes — `apiverity drift` |
| frontend ui | partial (VS Code extension) | yes — `apiverity serve (web/)` |
| graphql breaking | no | yes — `apiverity breaking` |
| grpc compat | no | yes — `apiverity breaking` |
| linting | yes | yes — `apiverity validate` |
| load testing | no | yes — `apiverity regression --shape` |
| mock server | no | yes — `apiverity mock` |
| openapi diff | no | yes — `apiverity diff` |
| otel export | no | yes — `apiverity test --otlp-endpoint` |
| performance budgets | no | yes — `apiverity regression` |
| plugin api | yes (rulesets/functions) | yes — `apiverity plugins` |
| rbac audit | no | yes — `apiverity audit` |
| response validation | no | yes — `apiverity test` |
| sarif export | yes (SARIF output) | yes — `apiverity report --format sarif` |
| schema driven fuzzing | no | yes — `apiverity test` |
| self hosted server | no | yes — `apiverity serve` |
| semver verdicts | no | yes — `apiverity breaking --check-semver` |
| service virtualization | no | yes — `apiverity mock --workspace` |
| stateful workflows | no | yes — `apiverity workflow` |
| traffic replay | no | yes — `apiverity replay` |

The Spectral column is `yes` / `partial` / `no` / `unknown` from the evidence file,
with `no` recorded only where the absence is verifiable or the area is clearly
outside that product's documented scope; the legend and the evidence notes are in
the data file. The api-verity-lab column names the command that provides each one,
because that column is not in the evidence file -- it was gathered to describe other
tools -- and an unsourced `yes` in every row is the thing this project exists to not
do. A test asserts every command named there exists.

## Using both

Nothing here argues for replacing Spectral. A tool that owns its lane is worth using
in it; this project's claim is a different one -- one contract model and one result
format across every protocol you speak, including the ones your agents speak.

[The full comparison](../competitive-analysis.md) covers every tool at once, and
[the benchmark](../benchmark.md) is reproducible, including where this project
loses.
