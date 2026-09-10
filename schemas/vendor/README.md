# Vendored third-party schemas

Schemas published by other projects, copied here byte-for-byte so a CI gate can
run without network access. Nothing in this directory is written or maintained
by this project; a change to any file here is an upstream change, re-fetched.

| File | Source | Fetched | SHA-256 | Licence |
|---|---|---|---|---|
| `arazzo-1.1-2026-04-15.schema.json` | <https://spec.openapis.org/arazzo/1.1/schema/2026-04-15> | 2026-09-10 | `37be908409bdb2f7bffe61fa23685c7e84cbeebfafac475a1d01dbc50ff7ab9e` | Apache-2.0 (OpenAPI Initiative) |

## Why the Arazzo schema is dated before the specification it validates

Arazzo 1.1.0 was released 2026-05-18. The most recent published JSON Schema
iteration for the 1.1 line is dated **2026-04-15**, and it is the newest one
the OAI lists at <https://spec.openapis.org/arazzo/> — checked 2026-09-10.

The OAI publishes schema iterations on their own cadence and says so in the
schema source's README: the specification, not the schema, is the source of
truth, and "some Specification constraints cannot be represented with the JSON
Schema". So a document that validates here is structurally well-formed against
the newest published iteration; it is not thereby proven to satisfy every
constraint Arazzo 1.1.0 states in prose.

`apiverity/stateful/arazzo.py` names this file's URL in `SCHEMA_ITERATION`, and
`tests/unit/test_arazzo.py` asserts the constant, the file name and this table
agree — so re-fetching a newer iteration cannot leave two of the three behind.
