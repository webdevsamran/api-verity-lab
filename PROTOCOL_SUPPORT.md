# Protocol Support

Status legend, verified against this repository's code and tests:

- **VERIFIED** — behavior implemented, deterministic tests pass in CI.
- **PARTIAL** — real foundation exists; named limitations apply.
- **BLOCKED** — needs hardware/credentials/services we do not have; interface + local mocks only.

| Capability | OpenAPI 3.0/3.1 | Swagger 2.0 | GraphQL SDL | gRPC/protobuf | AsyncAPI | SSE / WebSocket |
|---|---|---|---|---|---|---|
| Load + normalize | VERIFIED | VERIFIED | VERIFIED | VERIFIED | PARTIAL | PARTIAL |
| Source locations | VERIFIED | VERIFIED | VERIFIED | VERIFIED | PARTIAL | n/a |
| Semantic diff | VERIFIED | via v2 normalization | VERIFIED | VERIFIED | PARTIAL | PARTIAL |
| Breaking rules | VERIFIED | via v2 normalization | VERIFIED | VERIFIED | BLOCKED* | BLOCKED* |
| Dangerous-change category | n/a | n/a | VERIFIED | PARTIAL (width changes) | n/a | n/a |
| Lint / governance packs | VERIFIED | via v2 normalization | VERIFIED (protocol-filtered) | VERIFIED (protocol-filtered) | PARTIAL | PARTIAL |
| Case generation (pos/neg) | VERIFIED | via v2 normalization | BLOCKED* | BLOCKED* | BLOCKED* | BLOCKED* |
| Conformance testing vs runtime | VERIFIED | via v2 normalization | PARTIAL | BLOCKED* | BLOCKED* | BLOCKED* |
| Mock / virtualization | VERIFIED | via v2 normalization | BLOCKED | BLOCKED | BLOCKED | BLOCKED |
| Drift detection | VERIFIED | via v2 normalization | BLOCKED* | BLOCKED* | BLOCKED* | BLOCKED* |
| Performance budgets/regressions | VERIFIED | via v2 normalization | BLOCKED* | BLOCKED* | BLOCKED* | BLOCKED* |

\* *Interface and fixtures exist or are planned; live validation requires a real GraphQL server / gRPC
server / broker, which this project does not ship or impersonate. Nothing here fakes a passing run.*

## Notes per protocol

- **OpenAPI** is the strongest lane: full pipeline from diff through testing,
  drift, replay gating, mock/virtualization and performance budgets.
- **Swagger 2.0** imports are normalized into the protocol-v2 model with
  explicit loss/ambiguity findings; analysis quality then matches OpenAPI.
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

Evidence: every VERIFIED cell maps to tests under `tests/` that run on every
push (see `.github/workflows/ci.yml`).
