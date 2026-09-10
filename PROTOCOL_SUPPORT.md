# Protocol Support

Status legend, verified against this repository's code and tests:

- **VERIFIED** — behavior implemented, deterministic tests pass in CI.
- **PARTIAL** — real foundation exists; named limitations apply.
- **BLOCKED** — needs hardware/credentials/services we do not have; interface + local mocks only.

| Capability | OpenAPI 3.0/3.1/3.2 | Swagger 2.0 | GraphQL SDL | gRPC/protobuf | AsyncAPI | SSE / WebSocket | MCP | WSDL 1.1 / SOAP |
|---|---|---|---|---|---|---|---|---|
| Load + normalize | VERIFIED | VERIFIED | VERIFIED | VERIFIED | PARTIAL | PARTIAL | VERIFIED | VERIFIED |
| Source locations | VERIFIED | VERIFIED | VERIFIED | VERIFIED | PARTIAL | n/a | PARTIAL (JSON pointer, no line numbers) | VERIFIED (line numbers, from a paired expat pass) |
| Semantic diff | VERIFIED | as OpenAPI | VERIFIED | VERIFIED | PARTIAL | PARTIAL | VERIFIED | VERIFIED |
| Breaking rules | VERIFIED | as OpenAPI | VERIFIED | VERIFIED | BLOCKED* | BLOCKED* | VERIFIED | VERIFIED |
| Dangerous-change category | n/a | n/a | VERIFIED | PARTIAL (width changes) | n/a | n/a | VERIFIED (hints, description edits) | VERIFIED (`BRK-SOAP-*`: action, style, version) |
| Lint / governance packs | VERIFIED | as OpenAPI | VERIFIED (protocol-filtered) | VERIFIED (protocol-filtered) | PARTIAL | PARTIAL | PARTIAL | PARTIAL (security lint applies; the adapter reads no security requirements) |
| Case generation (pos/neg) | VERIFIED | as OpenAPI | BLOCKED* | BLOCKED* | BLOCKED* | BLOCKED* | BLOCKED* | BLOCKED (generators emit JSON, not SOAP envelopes) |
| Conformance testing vs runtime | VERIFIED | as OpenAPI | PARTIAL | BLOCKED* | BLOCKED* | BLOCKED* | VERIFIED (`MCP-CONF-*`) | BLOCKED |
| Mock / virtualization | VERIFIED | as OpenAPI | BLOCKED | BLOCKED | BLOCKED | BLOCKED | BLOCKED | BLOCKED |
| Drift detection | VERIFIED | as OpenAPI | BLOCKED* | BLOCKED* | BLOCKED* | BLOCKED* | VERIFIED (Streamable HTTP; stdio out of scope, see docs/mcp-drift.md) | BLOCKED |
| Performance budgets/regressions | VERIFIED | as OpenAPI | BLOCKED* | BLOCKED* | BLOCKED* | BLOCKED* | BLOCKED* | BLOCKED |

\* *Interface and fixtures exist or are planned; live validation requires a real GraphQL server / gRPC
server / broker, which this project does not ship or impersonate. Nothing here fakes a passing run.*

## Notes per protocol

- **OpenAPI** is the strongest lane: full pipeline from diff through testing,
  drift, replay gating, mock/virtualization and performance budgets.
- **Swagger 2.0** compiles into the *same* normalized model as OpenAPI 3 --
  `host`/`basePath`/`schemes` folded into servers, a `body` parameter into a
  request body, `definitions` into schemas -- so every capability in that
  column is whatever the OpenAPI column is, minus what the adapter reports as
  lost at load: `SWAGGER2-SERVER-SYNTHESIZED` when one server URL is
  synthesised from three fields, `SWAGGER2-OAUTH-FLOW-LOSSY` when 2.0's
  one-flow-per-definition model is flattened, `SWAGGER2-PARAM-IN` for an `in:`
  value 2.0 does not define.

  This table said "via v2 normalization" in eight cells and the paragraph here
  said the same. There was a `core/model_v2.py` -- stable entity ids, canonical
  hashes, artifact migration and contract bundles, nothing to do with Swagger,
  and `specs/swagger2.py` did not import it. The mechanism named was not the
  mechanism involved, and that module has since been deleted.

  `fixtures/apis/swagger2/petstore.yaml` is the document these cells are now
  measured against; there was no Swagger 2.0 fixture at all before it.
- **GraphQL**: root-type fields become operations; arguments become typed
  parameters; return types are captured so nullability evolution
  (`String! -> String`, `String -> String!`) is analyzed with a distinct
  dangerous-change category. Enum/interface/union member semantics inside
  output types are not yet modeled.
- **gRPC**: lightweight built-in proto parser (no protoc). Field-number reuse
  and duplicate RPCs detected at load; cross-revision wire compatibility
  covers RPC removal, message type swaps, scalar wire-type changes,
  integer-width changes and enum-value removal. Streaming RPC shapes are
  parsed but not exercised at runtime.
- **AsyncAPI**: channels/messages/bindings normalize into operations;
  message-level compat rules land with production-quality bindings coverage.
- **SSE/WebSocket**: documented event/message contracts are represented as
  first-class operations (`EVENT`, `WS_MESSAGE`) — no inference of
  undocumented protocols.
- **WSDL 1.1 / SOAP**: portTypes become operations keyed
  `portType.operation`; the XSD subset a WSDL actually uses becomes
  `SchemaNode`s, with `xs:choice` carried as a `oneof` and attributes under an
  `@` prefix. Faults are keyed by name rather than by the HTTP 500 they all
  share. A `DOCTYPE` is refused before any entity is expanded. Everything the
  model does not carry — `xs:group`, `xs:union`, restriction-derived complex
  types, `substitutionGroup`, external schema documents — emits a
  `SPEC-WSDL-*` finding naming it rather than being dropped silently. Nothing
  downstream of the contract (mocking, fuzzing, drift) speaks SOAP; see
  docs/spec-support.md.

Evidence: every VERIFIED cell maps to tests under `tests/` that run on every
push (see `.github/workflows/ci.yml`).
