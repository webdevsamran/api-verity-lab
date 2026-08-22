# Community Backlog (seed issues)

Meaningful, scoped contributions wanted. Comment on an item to claim it.

## Compatibility rules
1. **Multipart/form-data request diffing** — extend SchemaNode diff to
   multipart parts and binary formats; add rules for removed parts.
2. **Default-value change rule** — changing a default alters behavior for
   clients that omit the field; needs direction-aware severity.
3. **Response header type tightening** — today only presence is compared;
   add schema-level header diffs.

## GraphQL
4. **Argument-level fuzzing from SDL** — generate cases per argument
   constraint once the generator consumes GraphQL input types.
5. **Custom scalar registry** — pluggable generators/validation for
   scalars like `DateTime`, `UUID`.

## gRPC
6. **Descriptor-set loading** — accept compiled `FileDescriptorSet`
   alongside `.proto` text for toolchain parity.
7. **Reflection-based drift** — live server reflection vs proto contract.

## Plugins & ecosystem
8. **AsyncAPI spec plugin** — normalize channels/messages into the core
   model; diff message payloads.
9. **Example exporter plugin** — Postman/OpenAPI-collection export from
   generated cases.
10. **Transport plugin for auth profiles** — mTLS/OAuth device-flow
    reference implementation.

## Workflow inference
11. **OpenAPI `links` inference** — build suggested (never auto-run)
    workflow drafts from explicit response links.

## Drift & reports
12. **Recorded-corpus drift at scale** — streaming evaluation over large
    sanitized HAR sets without loading into memory.
13. **SARIF location mapping** — attach source locations to SARIF
    `region` fields for GitHub code annotations.

## Frontend
14. **Contract Explorer page** — endpoint tree + schema viewer over the
    normalized model export.
15. **Workflow graph view** — render step DAG with pass/fail coloring.
16. **Shareable filter state** — encode severity/page filters in URL.