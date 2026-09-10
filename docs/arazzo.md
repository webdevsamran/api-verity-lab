# Arazzo workflows

`apiverity workflow` runs a manifest this project invented. [Arazzo][spec] is
the OpenAPI Initiative's specification for the same job, and a proprietary
format is a reason not to adopt a tool no matter how good the engine behind it
is. So a manifest can be written as an Arazzo description, and an Arazzo
description can be run.

Version **1.1.0**, released 2026-05-18 — checked at the
[release list][releases] on 2026-09-10.

```bash
# Run an Arazzo description. Detected by its own `arazzo` field, not by name.
apiverity workflow fixtures/workflows/arazzo/users.arazzo.yaml \
  --base-url http://127.0.0.1:8090 \
  --input user_name=alice --input user_role=user

# Write a manifest as an Arazzo 1.1.0 description.
apiverity workflow fixtures/workflows/crud-lifecycle.yaml \
  --to-arazzo --spec fixtures/apis/crud/openapi.yaml
```

`--to-arazzo` requires `--spec`, for two reasons in one flag. An Arazzo
description must name at least one Source Description with a URL, and inventing
one would put a document nobody serves into the output. And the contract is
what turns this engine's path template into the contract's own — see
[Paths are not the same thing in the two formats](#paths-are-not-the-same-thing-in-the-two-formats).

A description that declares several workflows runs the first and says so; pass
`--workflow-id` to choose another.

## This is not an Arazzo runtime

The manifest is a straight line: steps in document order, one request each,
stop at the first failure, then best-effort cleanup. Arazzo describes a graph.
`onSuccess` and `onFailure` actions can `goto` another step or another
workflow, `retry` with a limit and a delay, and `end` the run; steps can
`dependsOn` other steps; a step can *be* another workflow; and 1.1.0 added
AsyncAPI steps that publish to or subscribe from a channel.

None of that has an equivalent here. Dropping it silently would hand back a
workflow that looks imported whole and behaves differently from the one
somebody wrote — a `retry` that vanished and a `goto` that vanished both leave
a description that still runs. So every construct with no equivalent is
reported, naming the workflow, the step, the construct and the reason:

```text
note: Read 2 workflow(s) from an Arazzo 1.1.0 description ('Verity CRUD
      lifecycle (fixture)'). 7 construct(s) have no equivalent in this engine
      and 3 step(s) were dropped. ...
  not carried: user-lifecycle.delete: onFailure -- `retry`, `goto` and `end`
      have no equivalent in a straight-line run
```

Those notes go to stderr, so a `--json` run is still one document on stdout.

## What maps

| Arazzo | Manifest | Note |
|---|---|---|
| `operationPath` | `request.method` + `request.path` | The JSON Pointer names both literally, so this resolves with no source document |
| `operationId` | — | The method and path are in the source description, which is not read here; the step is dropped and reported |
| `parameters` (`path`) | `{var}` in `request.path` | The placeholder is renamed to the variable the value expression names |
| `parameters` (`query`, `header`) | `request.query`, `request.headers` | |
| `parameters` (`querystring`, `cookie`) | — | A `WorkflowRequest` has a path, a query and headers, and nothing else |
| `requestBody.payload` | `request.body` | Runtime expressions inside become `{var}`; `replacements` are reported |
| `outputs` (`$response.body#/a/b`) | `extract` (`$.a.b`) | A JSON Pointer and this engine's JSONPath subset are the same shape |
| `successCriteria` (`$statusCode == 200`) | `assert_status` | An `OR` chain becomes the list |
| `successCriteria` (`$response.body#/a == 'x'`) | `assert_jsonpath` | Only against a literal — see below |
| `successCriteria` (`regex`, `jsonpath`, `xpath`) | — | Reported |
| `timeout` (milliseconds) | `timeout_seconds` | A unit carried across unchanged would make a 15-second step wait four hours |
| `inputs` (JSON Schema) | `inputs` (names) | Types are dropped on the way in and every name becomes a required string on the way out; the manifest has nowhere to put a type |

Every name in `inputs` is required and is supplied with `--input name=value`. A
declared input that is not supplied stops the run before the first request:
`{var}` substitution leaves an unknown name exactly as written, so the
alternative is a request carrying a literal `{user_name}`.

### An expectation cannot need a runtime value

The engine substitutes `{var}` into paths, bodies, headers and query values. It
does not substitute into an *expected* value. So

```yaml
- condition: $response.body#/name == '{$inputs.user_name}'
```

is reported rather than imported. Carrying it across would compare the response
against the literal text `{$inputs.user_name}` and fail every time it ran, which
is worse than not carrying it.

### Paths are not the same thing in the two formats

`/users/{user_id}` in a manifest is a template over *this engine's variables*.
`/users/{id}` in the contract is the parameter the contract *declares*. They
coincide only when the person who wrote the manifest happened to use the
declared name.

Both directions handle it, in opposite ways:

- **Importing**, the placeholder is renamed to whatever the value expression
  names — `/users/{id}` with `value: $steps.create.outputs.user_id` becomes
  `/users/{user_id}`, because the manifest substitutes by variable name and a
  `{id}` nothing fills would be sent as a literal path segment.
- **Exporting**, `--spec` supplies the contract, the step is matched on method
  and path *shape*, and the contract's own path goes into the pointer with the
  contract's own parameter name beside it. Called from the SDK without a
  contract, the manifest's template is written as-is and reported.

## The allowlist an imported description does not have

A manifest carries `allowed_hosts`, and the engine refuses to send traffic
anywhere else ([safety model](safety-model.md)). Arazzo has no such field, and
nothing in a description implies one: a Source Description's `url` is where the
*specification document* lives, which is frequently not where the API is.

So an import leaves `allowed_hosts` empty and the engine's host check does not
fire. Every request still goes to one place — the `--base-url` given on the
command line — and an imported workflow has no `base_url` of its own, so that
flag is required and the operator has named the target themselves. The import
note says this every time.

An imported description can contain `DELETE` steps, as the bundled fixture
does. Read it before you run it against anything you care about.

## What checks the export

Structure is checked against the OpenAPI Initiative's **own published JSON
Schema**, vendored at `schemas/vendor/arazzo-1.1-2026-04-15.schema.json` with
its URL, fetch date and SHA-256 in [`schemas/vendor/README.md`][vendor]. Both
the exported document and the bundled fixture are validated against it in CI,
along with a control case that must fail — a validator accepting everything
would pass the first two.

That schema iteration is dated **before** the 1.1.0 release. It is the most
recent one the OAI publishes for the 1.1 line, and the schema's own README says
the specification rather than the schema is the source of truth and that some
constraints cannot be expressed in JSON Schema at all.

What is **not** checked anywhere is the grammar inside a criterion's
`condition`, because no Arazzo runtime is vendored in this repository. A
condition this project writes is known to be structurally valid and known to
read back as what produced it. It is not known to have been executed by another
implementation, and that sentence is the whole of the claim.

[spec]: https://spec.openapis.org/arazzo/latest.html
[releases]: https://github.com/OAI/Arazzo-Specification/releases
[vendor]: https://github.com/webdevsamran/api-verity-lab/blob/main/schemas/vendor/README.md
