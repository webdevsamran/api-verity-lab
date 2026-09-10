# Security rules

Static checks over a normalized contract, run by `apiverity validate`. Every one
is addressable: `apiverity explain SEC-APIKEY-IN-QUERY` prints what it means,
what to ship instead, and the exact `--severity-override` to change it.

This file is generated from `apiverity/security/catalog.py`. A test fails when
a check emits an id the catalogue does not carry, and when the catalogue
carries an id nothing emits -- the first is a rule that cannot be explained,
the second is a rule that is published and dead.

These rules are **not** covered by the severity profiles in
[the rule catalogue](rule-catalog.md#severity-profiles), which act on the
breaking-change catalogue only. Use `--severity-override` or the config's
`severity_overrides` for these.


## Authentication

What the document says about who may call an operation. Three of these are INFO because they record a fact rather than a fault: an explicit `security: []`, a format with nowhere to declare authentication, and a format this tool does not read it from. The last one matters most -- a clean security report from an adapter that never looked is not a clean bill of health.

| Rule | Severity | Produced by | Fires when | Instead |
|---|---|---|---|---|
| `SEC-AUTH-ANONYMOUS` | INFO | `validate` | An operation explicitly declares anonymous access with `security: []`. | Nothing. This is the document saying what it means, which is the outcome SEC-AUTH-MISSING asks for. Recorded so an audit can see the choice was made. |
| `SEC-AUTH-MISSING` | WARN | `validate` | An operation declares no authentication, and neither does the contract. | Declare the scheme the operation actually requires. If it really is open, write `security: []` on it -- that is the documented way to say so, and it is the difference between a decision and an omission. |
| `SEC-AUTH-NOT-EXPRESSIBLE` | INFO | `validate` | This contract format has nowhere to declare authentication. | Nothing in the file. Record the requirement outside the contract -- and note that this is a limit of the format, not a gap in the API. |
| `SEC-AUTH-NOT-READ` | INFO | `validate` | This format can express authentication, and this adapter does not read it. | Nothing in the file. Reported so a clean security report is not mistaken for a verified one: the absence of findings here is the absence of a check. |
| `SEC-NO-AUTH-DECLARED` | WARN | `validate` | The contract declares no security schemes at all. | Declare the schemes the service uses under `components.securitySchemes`, even if a gateway enforces them -- a consumer generating a client reads this file, not your gateway. |
| `SEC-SCHEME-INCONSISTENT` | WARN | `validate` | Operations of similar kinds require different schemes without an evident reason. | Make the inconsistency deliberate and visible, or align them. An inconsistent surface is where the one unprotected endpoint hides. |
| `SEC-SCHEME-UNKNOWN` | ERROR | `validate` | An operation requires a security scheme the contract never declares. | Declare the scheme, or fix the name in the requirement. A generated client cannot authenticate against a scheme that does not exist. |

## Authorization scope

Whether the scopes an operation requires narrow anything.

| Rule | Severity | Produced by | Fires when | Instead |
|---|---|---|---|---|
| `SEC-SCOPE-BROAD` | WARN | `validate` | A required scope grants everything. | Split it. One token that opens the whole surface is the same authorization model as no scopes at all, with more configuration. |
| `SEC-SCOPE-UNSCOPED` | WARN | `validate` | An OAuth requirement names no scope, on a scheme that declares some. | Name the scope the operation needs. Without one, any valid token opens it, whatever it was issued for -- which makes the scheme's scope list decorative. |

## Credentials

Where credentials are carried, and where they end up. A finding here never records the value -- the kind, the pointer and the length are enough to triage, and an artifact that quoted the secret would be a second copy of it.

| Rule | Severity | Produced by | Fires when | Instead |
|---|---|---|---|---|
| `SEC-APIKEY-IN-QUERY` | ERROR | `validate` | A security scheme carries the API key in the query string. | Move it to a header. URLs reach access logs, proxy logs, browser history and `Referer` headers by default, so a key in one is a key in a dozen places nobody is guarding. |
| `SEC-BASIC-AUTH` | WARN | `validate` | A security scheme is HTTP Basic. | Prefer a bearer token or OAuth 2.0. Basic sends a reusable password on every request, and it cannot be scoped, rotated per client, or revoked for one caller without changing it for all of them. |
| `SEC-RESPONSE-CREDENTIAL` | ERROR | `drift, replay` | A response body carried something shaped like a credential. | Stop returning it. The finding records the kind, the JSON pointer and the length -- never the value -- so this can be triaged without the artifact becoming a second copy of the secret. |
| `SEC-SECRET-IN-CONTRACT` | ERROR | `validate` | A literal credential appears in the contract document. | Remove it and rotate it. A contract is committed, published and copied; treat anything that has been in one as disclosed. |
| `SEC-SENSITIVE-FIELD` | INFO | `validate` | A field name suggests it carries personal or secret data. | Check it is meant to cross this boundary, and that the redaction rules in `traffic/redact.py` cover it before any traffic capture touches disk. |
| `SEC-SENSITIVE-HEADER` | INFO | `validate` | A response declares a header that carries session or credential material. | Nothing, usually: `Set-Cookie` on a login route is the point. Recorded so a reviewer can see which routes hand out session state. |

## Resource consumption

Limits the contract does not declare. Unbounded *strings* are deliberately not checked: most strings should have no `maxLength`, and a check that fires hundreds of times per contract gets switched off, taking the useful ones with it.

| Rule | Severity | Produced by | Fires when | Instead |
|---|---|---|---|---|
| `SEC-ARRAY-UNBOUNDED` | WARN | `validate` | A request accepts an array with no `maxItems`. | Declare a ceiling. The cost is not the array, it is the work done per element; if the server already enforces a limit, say so in the description so a caller can find it. |
| `SEC-COLLECTION-UNPAGINATED` | WARN | `validate` | A read returns an array and declares no pagination parameter. | Add `limit` and a cursor. Response size then follows something the caller asked for, instead of following how much data happens to exist. |
| `SEC-RATE-LIMIT-METADATA` | INFO | `validate` | No rate-limit metadata is declared anywhere in the contract. | Declare the `RateLimit` headers you return, or describe the limits in the description. An undocumented limit is one every client discovers in production. |

## Shape and transport

| Rule | Severity | Produced by | Fires when | Instead |
|---|---|---|---|---|
| `SEC-ADDL-PROPERTIES` | WARN | `validate` | A schema accepts properties it does not declare. | Set `additionalProperties: false` where the shape is closed. An open object is where an unexpected field reaches code that was not written for it. |
| `SEC-CORS-WILDCARD` | WARN | `validate` | A wildcard CORS origin is declared. | Name the origins. `*` cannot be combined with credentials, and where it is combined anyway the browser is the only thing enforcing the difference. |
| `SEC-HTTPS-POLICY` | WARN | `validate` | A server URL uses plain HTTP. | Use HTTPS. A localhost URL is exempt; anything else puts the credential and the payload on the wire in the clear. |

## Other

| Rule | Severity | Produced by | Fires when | Instead |
|---|---|---|---|---|
| `SEC-UNAUTH-WRITE` | WARN | `validate` | A mutating operation has no authentication declaration. | Same edit as SEC-AUTH-MISSING, and more urgent: a POST or DELETE that a reader cannot tell is protected is one nobody will audit. |

_22 security rules._
