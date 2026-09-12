---
description: >-
  BOLA and BFLA probes: what happens when a different caller asks. Authorized-testing only, driven by the stateful engine across two identities.
---

# Authorization, between identities

Every other check in this project reads a contract, or watches one identity
talk to a service. Neither can see the two failures that matter most in
practice, because both are about what happens when a **different** caller asks.

```bash
export ALICE_TOKEN=... BOB_TOKEN=...
apiverity test openapi.yaml --base-url https://staging.example.com \
  --authz --include-mutations \
  --auth-profiles profiles.yaml --auth-profile alice --as bob
```

```yaml
# profiles.yaml
profiles:
  - name: alice
    kind: bearer
    token_env: ALICE_TOKEN
    scopes: [orders:read, orders:write]
  - name: bob
    kind: bearer
    token_env: BOB_TOKEN
    scopes: [orders:read]
```

## What it asks

**BOLA — [OWASP API1][api1].** Create a resource as `alice`, then ask `bob` to
read it, update it and delete it. Anything other than a refusal is a finding:

```text
AUTHZ-BOLA-READ   ERROR  'bob' GET /orders/{id} on an object created by 'alice'
                         and the service answered 200
```

The request was well-formed, the schema was satisfied, the status was 200, and
the data belongs to somebody else. That is exactly why no schema check and no
single-identity run can see it.

Read, update and delete are reported separately and the probe does not stop at
the first. A service that hides another tenant's object from a `GET` and
accepts a `PATCH` on it is checking visibility somewhere that is not the write
path — a different, and worse, defect from a plain read leak.

**BFLA — [OWASP API5][api5].** For every operation whose declared security
requires a scope `bob` does not hold, call it as `bob`. A 200 means either the
handler does not check the scope, or the profile is wrong about what `bob`
holds. Both are worth knowing; only one is a defect in the service.

## What it asks *you* to state

A scope check has to know what each identity holds, and no service will tell
you truthfully — that is the thing under test. So the profile declares it, and
a finding is always of the form *"you told me this identity does not hold
`orders:write`, and the service accepted the call anyway"*.

`scopes: []` and **not stated** are different, and only the first is a basis
for a finding. An identity with no `scopes` key produces
`AUTHZ-SCOPES-UNDECLARED` at INFO rather than a silent skip: assuming an
identity holds nothing would report every operation it can reach as a defect.

## What it does to the target

It creates one resource per collection and then attempts unauthorized access to
it. That is a write and a deliberate access attempt against a service you
named, so it needs `--include-mutations`, and the target rules in the
[safety model](safety-model.md) apply.

It does not escalate, chain, or exploit anything it finds. A finding records
the operation, the status and which identity made the call. There is no payload
here and there is not meant to be: the question is whether the service enforces
its own contract, and the answer is a status code.

A BFLA probe only issues `GET`, `HEAD` and `OPTIONS`. One that issued the
`DELETE` it was testing for would be indistinguishable from the attack, so an
operation that changes state is listed under `not_probed` with that reason.

## What a clean report means

```json
{"owner": "alice", "other": "bob", "attempts": 12, "findings": [], "not_probed": [...]}
```

Twelve attempts, all refused. That is evidence; "nothing happened" is not, and
the two look identical in a summary line — which is why `attempts` is in the
report and why everything the run could not reach is listed beside it with a
reason.

It is **not** a proof about every tenant, every object, or the identities you
did not test with. Two identities were kept apart in this run.

## Refusals that count as refusals

`401`, `403`, `404`, `405` and `410`. A 404 counts: hiding the existence of
another tenant's object is a legitimate and common way to deny, and reporting
it as a leak would make the probe unusable against services doing the right
thing.

[api1]: https://owasp.org/API-Security/editions/2023/en/0xa1-broken-object-level-authorization/
[api5]: https://owasp.org/API-Security/editions/2023/en/0xa5-broken-function-level-authorization/
