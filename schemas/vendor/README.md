# Vendored third-party schemas

Schemas published by other projects, copied here byte-for-byte so a CI gate can
run without network access. Nothing in this directory is written or maintained
by this project; a change to any file here is an upstream change, re-fetched.

| File | Source | Fetched | SHA-256 | Licence |
|---|---|---|---|---|
| `arazzo-1.1-2026-04-15.schema.json` | <https://spec.openapis.org/arazzo/1.1/schema/2026-04-15> | 2026-09-10 | `37be908409bdb2f7bffe61fa23685c7e84cbeebfafac475a1d01dbc50ff7ab9e` | Apache-2.0 (OpenAPI Initiative) |
| `tooltrace-task-2026-09-11.schema.json` | <https://raw.githubusercontent.com/webdevsamran/tooltrace-bench/main/schemas/task.schema.json> | 2026-09-11 | `76e505435d85a84b4140552838e0d61df356b4803947109dbb373d549cb33f93` | Apache-2.0 (tooltrace-bench) |

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

## Why the tooltrace-bench schema is fetched from `main` rather than a tag

tooltrace-bench publishes its schemas in the repository, not at a versioned
URL, so `main` is the only address a reader can check this copy against. The
row records the date and the digest; re-fetching is how it is updated, and a
diff is an upstream change.

Two consequences worth stating rather than discovering:

- **`main` moves.** A copy taken on one date can fall behind without anything
  here failing, because nothing in CI reaches the network. That is the same
  trade the Arazzo copy makes.
- **A working checkout is not the published schema.** The copy taken on
  2026-09-11 has `requires_tools` and not `tool_descriptions` or `attachments`,
  which exist only in an unpushed working tree of the sibling project.
  `apiverity agent-tasks` therefore uses neither: an export built on a field
  nobody else can fetch would validate here and nowhere else.
