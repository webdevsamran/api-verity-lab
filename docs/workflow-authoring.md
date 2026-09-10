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

## Arazzo

A manifest can be written as an [Arazzo 1.1.0 description](arazzo.md), and an
Arazzo description can be run directly -- with everything that has no
equivalent in this engine reported rather than dropped.