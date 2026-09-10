# Auth profiles

Every command that takes `--base-url` takes `--auth-profiles FILE` and
`--auth-profile NAME`: `test`, `workflow`, `drift`, `mcp-lock`, `ghosts`,
`replay`, `baseline` and `regression`.

```yaml
# profiles.yaml
profiles:
  - name: staging
    kind: bearer
    token_env: STAGING_TOKEN

  - name: partner-api
    kind: api_key
    key_env: PARTNER_API_KEY
    header_name: X-Partner-Key

  - name: legacy-basic
    kind: basic
    username_env: LEGACY_USER
    password_env: LEGACY_PASSWORD

  - name: internal-mtls
    kind: mtls
    cert_file: /etc/apiverity/client.pem
    key_file: /etc/apiverity/client.key
```

```bash
export STAGING_TOKEN=...
apiverity drift openapi.yaml --base-url https://staging.example.com \
  --auth-profiles profiles.yaml --auth-profile staging
```

A file with one profile needs no `--auth-profile`. A file with several will not
pick one for you: guessing would authenticate as somebody the operator did not
name.

## Nothing in this file is a credential

Every value is a **reference** — the name of an environment variable, or a path
on disk. The value is read from the environment at the moment a request is
built and is never written down.

So a result bundle from that run records:

```json
{"name": "staging", "kind": "bearer", "token_env": "STAGING_TOKEN"}
```

and nothing that whoever finds the bundle could replay. Bundles get attached to
pull requests, uploaded as CI artifacts and mailed around; one that carried the
token would be a second copy of it in all of those places.

Pasting a token where a reference goes is an easy mistake — the field is a
string and a token is a string — so a value that is not a valid environment
variable name is refused when the file loads, before a run can put it in an
artifact.

## `--header` on top, not instead

```bash
apiverity test openapi.yaml --base-url https://staging.example.com \
  --auth-profiles profiles.yaml --auth-profile staging \
  --header 'X-Tenant=acme'
```

A profile carries the credential; a header carries the tenant id or the trace
header you need beside it. Making them exclusive would force a choice nobody
wants to make. Header values never reach the artifact either.

## What each kind sends

| `kind` | Sends |
|---|---|
| `bearer`, `oauth_token` | `Authorization: Bearer <$token_env>` |
| `api_key` | `<header_name>: <$key_env>`, default header `X-Api-Key` |
| `basic` | `Authorization: Basic <base64 of $username_env:$password_env>` |
| `mtls` | No header. A client certificate pair, as httpx's `cert=` |

An environment variable a profile names and nothing has set is a usage error,
not an empty header: `Authorization: Bearer ` would be answered with a 401 and
reported as a service rejecting valid requests.

## History

This module has held the whole mechanism since the beginning and no flag
reached it — a tool for checking APIs that could only check unauthenticated
ones is most of a tool. Two things had gone unnoticed for exactly that reason.

**`resolve_verify` named the wrong httpx parameter.** It returned
`(cert_file, key_file)` and called that "httpx `verify` material". `verify` is
the *server* certificate setting, typed `ssl.SSLContext | str | bool`; a client
certificate goes in `cert`. httpx does not reject the tuple at construction —
it stores it, so the SSL context *is* a tuple — and the client certificate is
never presented. The function is `resolve_client_cert` now.

**The redaction redacted references and printed references.**
`redacted_summary` is documented as "references only, no secret values", and it
blanked `password_env` and `key_file` while printing `token_env`, `key_env`,
`username_env` and `cert_file`. Those are all the same kind of thing. Redacting
the name of the variable holding a password while printing the name of the one
holding a bearer token protects nothing and costs the reader the one fact the
summary exists to give them: which variable to set.
