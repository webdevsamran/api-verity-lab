---
description: >-
  Serve several mocked contracts from one workspace file under one seed, so a whole dependency surface comes up deterministically with one command.
---

# Virtualization workspaces

`apiverity mock openapi.yaml` serves one contract. `apiverity mock --workspace`
serves several, from one file, under **one seed**, and prints the address of
each before it blocks.

```yaml
# checkout-stack.yaml
name: checkout-stack
seed: 42
services:
  - name: users
    spec: ../apis/crud/openapi.yaml
  - name: catalogue
    spec: ../apis/versioned/v2.yaml
  - name: billing
    spec: ../apis/governance/openapi.yaml
    faults:
      latency_ms: 120
      rate_limit_after: 50
```

```bash
apiverity mock --workspace fixtures/workspaces/checkout-stack.yaml
```

```text
workspace 'checkout-stack', seed 42
  users      http://127.0.0.1:49971
  catalogue  http://127.0.0.1:60312
  billing    http://127.0.0.1:60313   faults: {'latency_ms': 120, 'rate_limit_after': 50}
Ctrl+C to stop.
```

`--json` emits the same table as an artifact, so a test harness can read the
addresses it is about to talk to.

## Why not three `mock` commands

`apiverity mock a.yaml & apiverity mock b.yaml &` gets you two servers. What it
does not get you is a **reproducible** pair.

Each process seeds its own response generator from its own default, so the data
a frontend sees depends on which flags each was started with. A test that
passed yesterday against `--latency-ms 0` fails today against `--latency-ms 50`
for reasons that have nothing to do with latency — the generated ids moved.

A workspace is one seed across the set. Change a fault on one service and the
data everywhere stays exactly where it was, which is the only way "run the
frontend against the stack with billing degraded" is a test rather than an
anecdote.

## The file

| Key | Meaning |
|---|---|
| `name` | The workspace's name, for the printed table and the artifact. Defaults to the file's stem |
| `seed` | One integer, for every service. There is no per-service seed |
| `services[].spec` | A contract, in any format this tool reads. Resolved **relative to the workspace file**, so a workspace checked into a repository works from anywhere in it |
| `services[].name` | How `base_url(name)` addresses it and how the table reads. Defaults to the spec file's stem; two the same is an error |
| `services[].port` | A fixed port. Omit for an ephemeral one — the normal case, which is why the addresses are printed |
| `services[].faults` | `latency_ms`, `force_status`, `malformed_json`, `rate_limit_after` |

Every key is checked, and an unknown one is an error rather than a warning —
the reason [the project config](ci.md) gives: a key nobody reads is a setting
the reader believes is active. `latencyms` would otherwise be a fault somebody
spends an afternoon looking for.

**There is no per-service seed, deliberately.** A set of services that
reproduce independently is not a workspace; it is several mocks in one file.

## Provenance

One run serves several contracts, so no single `contract_hash` names what was
served. The artifact is stamped with the **workspace file's** hash — the file
that named all of them — and each service carries its own contract's path and
hash beside its address.

```json
{
  "workspace": "checkout-stack",
  "seed": 42,
  "services": [
    {
      "name": "billing",
      "base_url": "http://127.0.0.1:60313",
      "operations": 2,
      "contract": "fixtures/apis/governance/openapi.yaml",
      "contract_hash": "55035c2d…",
      "faults": {"latency_ms": 120, "rate_limit_after": 50}
    }
  ],
  "contract_hash": "3d4451d7…",
  "protocol_version": "workspace"
}
```

The seed appears once, beside the workspace name, and not on each service.
Repeating it per service would suggest it can differ, and it is exactly the
thing that must not.

## History

This module existed, with tests, before any of the above, and no command
reached it — so `PRODUCT_GAPS.md`'s answer to "why are there no hand-authored
stub DSLs (WireMock territory)", *"virtualization derives from contracts"*,
pointed at code a user could not run.

It also did not quite do what its own docstring said. `start()` read

```python
faults = self.definition.faults.get(vs.name) or FaultConfig(seed=self.definition.seed)
```

so the workspace seed reached a service **only when that service had no fault
override at all**: a `FaultConfig` written for latency carries the default seed
of 0, and `or` takes it whole. Configuring latency on one service silently
reseeded that service's data, and the one setting a workspace exists to hold
constant varied with whether somebody had configured that service.
