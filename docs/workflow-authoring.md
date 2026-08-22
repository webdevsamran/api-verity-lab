# Authoring Workflow Manifests

Workflows are **human-authored** YAML. The engine never invents destructive
sequences and refuses hosts outside `allowed_hosts`.

```yaml
name: crud-lifecycle
description: create -> get -> delete
allowed_hosts: ["http://127.0.0.1"]     # origins permitted to receive traffic
allowed_methods: [GET, POST, DELETE]    # optional restriction
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

Run: `apiverity workflow wf.yaml --base-url http://127.0.0.1:8091`
Exit `0` when every step passes; cleanup failures never fail the run.