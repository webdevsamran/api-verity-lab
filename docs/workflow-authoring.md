# Authoring Workflow Manifests

Workflows are **human-authored** YAML. The engine never invents destructive
sequences and refuses hosts outside `allowed_hosts`.

```yaml
name: crud-lifecycle
description: create -> get -> delete
allowed_hosts: ["http://127.0.0.1"]     # origins permitted to receive traffic
allowed_methods: [GET, POST, DELETE]    # optional restriction
inputs: [tenant]                        # required; supplied with --input
steps:
  - name: create
    request:
      method: POST
      path: /users
      body: {name: alice, role: user}
    assert: {status: 201, jsonpath: {"$.role": "user"}}
    extract: {user_id: "$.id"}          # tiny JSONPath subset: $.a.b[0]
    timeout: 15                          # seconds
  - name: get
    request: {method: GET, path: "/users/{user_id}"}   # {var} substitution
    assert: {status: 200}
cleanup:                                 # always runs, best-effort
  - name: delete
    request: {method: DELETE, path: "/users/{user_id}"}
```

Run: `apiverity workflow wf.yaml --base-url http://127.0.0.1:8091 --input tenant=acme`
Exit `0` when every step passes; cleanup failures never fail the run.

## Inputs

Names in `inputs` are **required**. A declared input that is not supplied stops
the run before the first request, because `{var}` substitution leaves an
unknown name exactly as written -- a workflow missing `tenant` would otherwise
send a literal `/t/{tenant}` and report whatever the server made of it.

Values stay strings. `inputs` is a list of names with no types, so parsing
`--input limit=1` into an integer would be the command deciding something the
manifest did not say.

## Checked before anything is sent

`workflow` validates the manifest as a graph first: a step may only use a
variable an earlier step extracted or an input you supplied, step names must be
unique, and cleanup may not delete something nothing created. An **error stops
the run** -- a request going out with a literal `{user_id}` in its path is the
thing this exists to prevent, and by the time anybody notices, the steps before
it have already been sent. Warnings (a created resource with no cleanup) print
and the run continues. `--no-preflight` skips the check.

The variable syntax is single braces, `{name}`, everywhere: paths, headers,
bodies and query values. Extraction and assertion paths use the engine's
JSONPath subset, `$.a.b` with an optional trailing `[0]` -- a bare `id` matches
nothing.

## Arazzo

A manifest can be written as an [Arazzo 1.1.0 description](arazzo.md), and an
Arazzo description can be run directly -- with everything that has no
equivalent in this engine reported rather than dropped.