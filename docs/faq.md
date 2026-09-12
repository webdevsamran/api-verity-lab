---
description: >-
  Short answers about API contract governance, breaking-change detection, drift, MCP tool surfaces and CI gating, each backed by the command that proves it.
---

# Frequently asked questions

Short answers, each with the command or the page that backs it up.

## What is API contract governance?

Treating your API's contract — the OpenAPI, AsyncAPI, GraphQL, gRPC, MCP or
WSDL document — as something that gets checked on every change, rather than as
documentation somebody updates afterwards.

In practice it is four questions asked in CI:

1. **What changed** between this version and the last? (`apiverity diff`)
2. **Does any of it break a consumer?** (`apiverity breaking`)
3. **Does the running service still match?** (`apiverity drift`)
4. **Is it still fast enough?** (`apiverity regression`)

82% of organisations say they have an API-first strategy and about 10% have a
governance framework, with 43% planning one within a year
([DreamFactory, 2026](https://www.dreamfactory.com/hub/api-governance-trends/)).
The gap between those numbers is the reason this tool exists.

## How do I detect breaking changes in an OpenAPI spec?

```bash
apiverity breaking openapi-v1.yaml openapi-v2.yaml
```

Exit code 1 when anything at or above your threshold fires; 0 when nothing
does. Each finding carries a stable rule id you can look up:

```bash
apiverity explain BRK-RESP-FIELD-REMOVED
```

The full list is in the [rule catalogue](rule-catalog.md) — 79 breaking-change
rules and 247 checks, both generated from the code.

## Is it only for OpenAPI?

No. One contract model, seven formats: **OpenAPI 3.0/3.1/3.2**, **Swagger
2.0**, **AsyncAPI 2.x/3.x**, **GraphQL SDL**, **gRPC** (proto and descriptor
sets), **MCP tool manifests** and **WSDL 1.1 / SOAP**.

The same commands work on all of them, and [rule parity](rule-parity.md) is a
*measured* table of which rules actually fire for which format — not an
asserted one.

## What makes this different from oasdiff, Spectral or Pact?

Each of those owns one lane and owns it well. This project's claim is narrower
than "better":

> One contract model and one result format across every protocol you speak,
> including the ones your agents speak.

[The comparison](competitive-analysis.md) is generated from dated evidence and
records what each of those tools does better. [The
benchmark](benchmark.md) is reproducible and publishes where this tool loses,
because a benchmark that only wins reads as marketing.

Per-tool pages: [oasdiff](vs/oasdiff.md) · [Schemathesis](vs/schemathesis.md) ·
[Spectral](vs/spectral.md) · [Pact](vs/pact-oss.md) · [Buf](vs/buf.md).

## Can it check a *running* service, not just the file?

Yes, and it is the thing this project is built around.

```bash
apiverity drift openapi.yaml --base-url https://staging.example.com
apiverity drift openapi.yaml --corpus traffic.har      # or from recorded traffic
apiverity ghosts openapi.yaml --was v1.yaml --base-url https://staging.example.com
```

`drift` reports where the deployment and the contract disagree. `ghosts` finds
routes you deleted from the contract that are still answering — see
[ghost routes](ghost-routes.md).

## Does it send my API spec anywhere?

No. It reads local files, and it makes an outbound request only when you pass a
URL — a `--base-url`, a remote `$ref` you explicitly allowed, an OTLP endpoint.

You do not have to take that on trust: [`docs/egress.md`](egress.md) is
**generated from the source** by walking the AST for network calls, so a module
that acquires one without a stated trigger is reported by name.

There is no telemetry, no account, and no phone-home. The
[playground](playground.md) runs the real engine in your browser precisely so
that trying it does not require uploading a contract to anybody.

## Does it work with MCP servers and AI agents?

Yes — this is the part no other tool covers end to end.

```bash
apiverity breaking tools-v1.json tools-v2.json     # did the tool surface change?
apiverity drift tools.json --base-url https://mcp.example.com   # does the server match?
apiverity validate tools.json                      # is a description instructing the agent?
apiverity mcp-lock check --base-url ...            # did it change without review?
apiverity budget calls.json --budget budgets.yaml  # is an agent calling too often?
```

An MCP tool **description** is what an agent routes on, which makes it
executable text rather than documentation. `MCP-POISON-*` reports a description
that instructs rather than describes, hides text in markup, carries characters
the reviewer cannot see, or points the agent at a credential path — see
[tool poisoning](mcp-poisoning.md).

Findings map onto the [OWASP MCP Top 10 and the Agentic Top
10](compliance-mapping.md), including what this tool **cannot** see.

## Will it fail my build on day one?

Only if you ask it to. `apiverity init` writes a config with the gate **off**,
deliberately:

> A check that fails on its first run against an API with history gets removed
> rather than adopted.

Then `drift --baseline` fails on what is *newly* wrong rather than on three
years of accumulated findings, and [suppressions](ci.md#suppressions) have an
owner, a reason and an expiry rather than being a permanent ignore file.

## How do I add my own rules without forking?

Write a rule pack — a normal Python package declaring an `apiverity.rules`
entry point. There is no registry to register with: pip is the distribution
channel.

```bash
pip install -e examples/plugins/apiverity-house-rules
apiverity rules --packs
```

[The authoring guide](plugin-authoring.md) and a
[worked example](https://github.com/webdevsamran/api-verity-lab/tree/main/examples/plugins/apiverity-house-rules)
are both in the repository, and the example is installed into a throwaway
virtualenv by the test suite so it cannot rot.

For house style without writing Python, there is a
[YAML policy DSL](policy-dsl.md):

```bash
apiverity validate openapi.yaml --policy-file house.yaml
```

## Does it run in CI?

```yaml
- uses: webdevsamran/api-verity-lab@v0
  with:
    spec-paths: openapi.yaml
```

Exit codes are stable: `0` ok, `1` findings at or above the threshold, `2`
usage error, `3` target unreachable, `4` internal error. See
[the CI gate](ci.md) and [merge queues](merge-queue.md).

Reports render to JSON, SARIF (so findings appear in GitHub code scanning),
JUnit, HTML, YAML and markdown.

## Can I run it air-gapped?

Yes. No telemetry is not a policy statement here, it is what the
[egress map](egress.md) shows. [Air-gapped install](air-gapped.md) covers the
offline path, the container image has a CLI entrypoint, and there is a
[Helm chart](air-gapped.md) for the self-hosted server.

## Is there a UI?

Yes — a React dashboard that reads either a static result artifact or a live
self-hosted server. It is not required: every command works from the CLI, and
the server is optional.

## What does it cost?

Nothing. Apache-2.0, no paid tier, no sponsor-only build, no licence key — a
governance tool with a hidden half is a governance tool you cannot audit.

If it saves your team time, [sponsorship](https://github.com/sponsors/webdevsamran)
is what keeps it maintained; the terms are in
[SPONSORS.md](https://github.com/webdevsamran/api-verity-lab/blob/main/SPONSORS.md).

## How do I install it?

```bash
curl -fsSL https://raw.githubusercontent.com/webdevsamran/api-verity-lab/main/install.sh | sh
```

Windows, Docker, from source and every other channel — including the ones that
do **not** work yet and why — are in [Installing](install.md).

## How do I trust the numbers in this documentation?

Do not take them on trust; the project does not either. The rule catalogue, the
check-rule list, the competitive table, the README's examples and counts, the
benchmark, the per-protocol landing pages, the capability manifest, the terminal
recording and the [roadmap status](roadmap-status.md) are all **generated from
the code and re-checked in CI**. When one disagrees with the code, the build
fails.

The things this tool cannot do are written down too:
[product gaps](product-gaps.md), [capability status](capability-status.md), and
a "what this cannot see" section in the compliance mapping.
