---
description: >-
  api-verity-lab is local-first: nothing leaves your machine unless you pass a URL. What is redacted, when, and what never reaches disk.
---

# Privacy & Redaction

api-verity-lab is local-first: nothing leaves your machine unless you send it
somewhere explicitly.

## What is redacted, always
- Headers: `Authorization`, `Cookie`, `Set-Cookie`, `Proxy-Authorization`,
  `X-Api-Key`, `X-Auth-Token`, `X-Csrf-Token`.
- Query fields: `api_key`, `apikey`, `token`, `access_token`, `secret`, `password`.
- Body fields: `password`, `secret`, `token` (recursive).
- Pattern-based scrubbing: `Bearer …`, `sk-…` keys, `token=/api_key=/secret=…`
  assignments — applied to any string value.

## Configuration
```python
from apiverity.traffic.redact import RedactionConfig
cfg = RedactionConfig(
    sensitive_headers={"x-my-secret"},
    sensitive_body_fields={"ssn", "iban"},
    patterns=[r"(?i)internal-\d+"],
)
```

## Guarantees
- HAR import (`apiverity.traffic.redact.import_har`) redacts before anything
  is stored; response bodies are never persisted by default.
- Result bundles (`.apiverity`) contain sanitized failing cases only.
- Auth profiles reference environment variables or file paths; secret values
  are resolved at request time and never written to artifacts.
- Synthetic-secret tests in the suite assert `Bearer`, `sk-…`, passwords,
  tokens and api keys never survive redaction.
- Credential scanning of responses (`apiverity.security.leakage`) reports the
  *kind* of secret, the JSON pointer it sits at and its length. The value is
  never in the finding and never reaches an artifact: a scanner that quotes the
  token it found to prove it found one has copied a live credential into a
  file, a log and a CI annotation. Read it at the source, rotate it there.