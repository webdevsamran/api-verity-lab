# Credits and acknowledgements

Nothing here was built from nothing. This file names what it was built on, what
it was built *after*, and who it owes.

It is a separate file from `ARCHITECTURE.md` (which names design prior art in
passing) because credit that is a footnote in a technical document is credit
nobody reads.

## The people

**[@webdevsamran](https://github.com/webdevsamran)** — original creator,
founder and lead maintainer.

Contributors are listed in the repository's
[contributor graph](https://github.com/webdevsamran/api-verity-lab/graphs/contributors),
which is generated from the commits rather than from a list somebody maintains —
the same rule the rest of this project applies to its own documentation.

If you have contributed and the graph does not show it — a review that changed
a design, a bug report that found a false positive, an issue that named a gap —
open a pull request against this file. Work that does not produce a commit is
still work, and it is the kind this project most depends on.

## The specifications

This tool reads other people's formats. Every one of them is somebody's years
of committee work, published for free:

- **[OpenAPI Specification](https://spec.openapis.org/)** 3.0, 3.1 and 3.2, and
  **Swagger 2.0** — the OpenAPI Initiative, under the Linux Foundation.
- **[Arazzo Specification](https://www.openapis.org/arazzo-specification)** —
  the OAI's workflow format. `docs/arazzo.md` describes what survives the
  round trip and what does not.
- **[AsyncAPI](https://www.asyncapi.com/)** 2.x and 3.x.
- **[GraphQL](https://spec.graphql.org/)** — the GraphQL Foundation.
- **[Protocol Buffers](https://protobuf.dev/)** and **gRPC** — Google.
- **[Model Context Protocol](https://modelcontextprotocol.io/)** — Anthropic,
  and the wider MCP community. The `BRK-MCP-*` taxonomy is **this project's
  own**: upstream defines no breaking-change semantics for a tool surface, and
  `docs/mcp-drift.md` says so rather than implying otherwise.
- **[WSDL 1.1](https://www.w3.org/TR/wsdl)** and SOAP — the W3C.
- **[JSON Schema](https://json-schema.org/)** 2020-12.
- **[SARIF 2.1.0](https://docs.oasis-open.org/sarif/sarif/v2.1.0/)** — OASIS,
  for the static-analysis interchange format the reports render into.
- **[HAR 1.2](http://www.softwareishard.com/blog/har-12-spec/)** — the traffic
  interchange format the drift corpus reads.
- **RFC 8594** (`Sunset`), **RFC 9457** (problem details), **RFC 6749** and
  **RFC 8628** (OAuth 2.0 and the device flow) — the IETF.
- **[OWASP](https://owasp.org/)** — the API Security Top 10, the MCP Top 10 and
  the Top 10 for Agentic Applications, which `docs/compliance-mapping.md` maps
  findings onto, including the parts this tool **cannot** see.

Two vendored schema copies live in `schemas/vendor/` with their source, fetch
date, digest and licence recorded, because a copy with no provenance is a file
of unknown origin.

## The libraries this depends on

The runtime dependency list is five packages, and that is deliberate — a
governance tool that drags in forty transitive dependencies is a governance
tool with forty supply-chain surfaces.

| | |
|---|---|
| **[pydantic](https://docs.pydantic.dev/)** | The contract model. Every `Service`, `Operation` and `SchemaNode` in this project is a pydantic model, which is why a malformed document fails at the boundary instead of three layers in. |
| **[httpx](https://www.python-httpx.org/)** | Every outbound request, in one library, which is what makes `docs/egress.md` possible to generate. |
| **[PyYAML](https://pyyaml.org/)** | Reading contracts, and the source of two real bugs this repository has fixed (`off` parsing as `False`; escapes in double-quoted scalars). |
| **[Flask](https://flask.palletsprojects.com/)** | The self-hosted server. |
| **[packaging](https://packaging.pypa.io/)** | Semver comparison that agrees with the rest of the Python ecosystem rather than with a hand-rolled parser. |

Optional extras, each installed only by the people who need it:
**[graphql-core](https://github.com/graphql-python/graphql-core)**,
**[PyJWT](https://pyjwt.readthedocs.io/)**, **[grpcio-tools](https://grpc.io/)**.

The dashboard's only runtime dependency is
**[React](https://react.dev/)**. The build and test toolchain is
**[Vite](https://vite.dev/)**, **[Vitest](https://vitest.dev/)** and
**[TypeScript](https://www.typescriptlang.org/)**.

The development toolchain: **[pytest](https://pytest.org/)**,
**[Hypothesis](https://hypothesis.readthedocs.io/)**,
**[mypy](https://mypy-lang.org/)**, **[Ruff](https://docs.astral.sh/ruff/)**,
**[MkDocs](https://www.mkdocs.org/)** with
**[Material](https://squidfunk.github.io/mkdocs-material/)**, and
**[Pyodide](https://pyodide.org/)**, which is what lets the browser playground
run this project's real engine rather than a reimplementation of it.

## The projects this learned from

Independent implementation, and credit where the idea came from.
None of these projects' code is in this one.

| | |
|---|---|
| **[oasdiff](https://github.com/oasdiff/oasdiff)** | Framed OpenAPI diffing as a problem with an answer. It is the healthy incumbent, `docs/benchmark.md` measures against it **including where this tool loses**, and `apiverity report --format oasdiff` exists so leaving is cheap. |
| **[Schemathesis](https://github.com/schemathesis/schemathesis)** | The reference for property-based, schema-driven API testing. |
| **[Spectral](https://github.com/stoplightio/spectral)** | The rule-catalogue architecture, and the reason `explain` exists at all: rules nobody can look up get switched off. `apiverity import-rules` reads Spectral rulesets. |
| **[Pact](https://pact.io/)** | Consumer-driven contracts, and `can-i-deploy` as a question worth asking. |
| **[Dredd](https://github.com/apiaryio/dredd)** (archived) | The contract-testing workflow shape. |
| **[Karate](https://github.com/karatelabs/karate)** and **[Tavern](https://github.com/taverntesting/tavern)** | Declarative workflow authoring. |
| **[Microcks](https://microcks.io/)** | Multi-protocol mocking done seriously, and the first to expose mocks as MCP tools. |
| **[Optic](https://github.com/opticdev/optic)** (archived) | Traffic-driven contract inference. |
| **[Buf](https://buf.build/)** | Protobuf compatibility as a gate rather than a review comment. |
| **[k6](https://k6.io/)** | Thresholds as a first-class idea, which is where performance budgets came from. |
| **[ESLint](https://eslint.org/)** | Not an API tool at all, and the single strongest influence on the rule design: it won on explanations. A rule nobody understands is a rule somebody disables, and it takes its neighbours with it. |

`docs/competitive-analysis.md` is generated from dated, checked evidence in
`data/`, and it records what each of these does **better** than this project.
That is deliberate: a comparison that only lists the other tool's gaps is an
advertisement.

## The sibling projects

Also by the same maintainer, and sharing one rule rather than any code:

- **[devrepro-doctor](https://github.com/webdevsamran/devrepro-doctor)**
- **[tooltrace-bench](https://github.com/webdevsamran/tooltrace-bench)** — which
  `apiverity agent-tasks` hands a verified tool surface to.
- **[local-ai-hardware-bench](https://github.com/webdevsamran/local-ai-hardware-bench)**

## Sponsors

None yet. [`SPONSORS.md`](https://github.com/webdevsamran/api-verity-lab/blob/main/SPONSORS.md) says what sponsorship would fund and,
more importantly, what it does not buy.

## Licence

Apache-2.0. See [`LICENSE`](https://github.com/webdevsamran/api-verity-lab/blob/main/LICENSE) and [`NOTICE`](https://github.com/webdevsamran/api-verity-lab/blob/main/NOTICE).

Every dependency above is used under its own licence; `pip-audit` and
`npm audit` run in CI, and an SPDX SBOM is attached to every release.
