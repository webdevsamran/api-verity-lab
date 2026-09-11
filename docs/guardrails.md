# Outbound payload guardrails

Two checks that run **before** a generated request goes out.

```bash
apiverity test api.yaml --base-url https://staging
apiverity test api.yaml --base-url https://staging --max-payload-bytes 1048576
apiverity test api.yaml --base-url https://staging --allow-credential-payloads
```

## The leak the tool would perform

[`SEC-RESPONSE-CREDENTIAL`](check-rules.md) reads what comes *back* from a
service. This is the other direction, and it is the one nobody checks because
synthetic data feels safe by construction.

It is not. A generated payload is built from the contract, and a contract is a
document somebody wrote: an `example`, a `default`, an `enum` member.
`apiverity validate` reports committed secrets in examples precisely because
they happen. When one does, a fuzz run reads it out of the repository and posts
it to whatever `--base-url` names.

That is not a leak the tool found. It is one the tool performed.

So `GUARD-PAYLOAD-CREDENTIAL` runs before the request. A payload carrying
something credential-shaped is **not sent** — reported, counted as a failure of
that case, and the run continues with the rest. A WARN beside a request that
already went out is a finding about something nobody can take back.

```
error  POST /keys  not sent: the generated payload carries AWS access key id
                   at api_key, which this run would have posted to the target
```

The finding names the **kind** and the **pointer**, never the value. A guardrail
that printed the credential to prove it stopped it has copied it into a log, a
CI annotation and a result artifact — the same rule
[`security/leakage.py`](check-rules.md) follows.

`--allow-credential-payloads` sends it anyway, and still reports it at WARN. A
contract may legitimately declare a token field with a realistic-looking
example, and a team testing their own staging environment may know that. It is
an explicit choice with a name, for the same reason `replay` needs one to touch
production.

## The denial of service you wrote by running a test suite

`maxLength: 10000000` is a legal schema. A boundary generator asked for the
largest valid string produces ten megabytes, and sends it.

`GUARD-PAYLOAD-SIZE` refuses a body over 256 kB — far above any hand-written
example, far below the size at which a request becomes an attack. Raise it with
`--max-payload-bytes` when the target is meant to take one.

Refused, not truncated. A payload silently shrunk is a case that did not test
what it says it tested, and a green result for it is worse than a missing one.

## What is deliberately not guarded

**Injection payloads.** A generated value that looks like SQL or a shell
fragment came out of the contract's own `pattern` or `enum`, so refusing to send
it would refuse to test what the contract says the operation accepts — and a
service that mishandles it has a bug this run exists to find.

The guardrail is about what this tool must not **do**, not about what the target
must not receive.

## What a refused case tells you about the service

Nothing. A payload that was not sent established nothing about the target, and
the result is `error` rather than `fail` for that reason: the case did not run.
