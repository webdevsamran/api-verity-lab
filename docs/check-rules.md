# Check rules

Every rule this tool emits that is not a breaking-change rule. Most are static
checks over a normalized contract, run by `apiverity validate`; the few that
need a live service say so in their own row.

Each is addressable: `apiverity explain SEC-APIKEY-IN-QUERY` prints what it
means, what to ship instead, and the exact `--severity-override` to change it.

This file is generated from the catalogues under `apiverity/rules/` and
`apiverity/security/`. A test fails when a check emits an id no catalogue
carries, and when a catalogue carries an id nothing emits -- the first is a
rule that cannot be explained, the second is a rule that is published and
dead.

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
| `SEC-UNAUTH-WRITE` | WARN | `validate` | A mutating operation has no authentication declaration. | Same edit as SEC-AUTH-MISSING, and more urgent: a POST or DELETE that a reader cannot tell is protected is one nobody will audit. |

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
| `SEC-ABUSE-UNBOUNDED-PAGE-SIZE` | WARN | `validate` | A page-size query parameter declares no `maximum`. | Declare `maximum` on the parameter. If the server already caps it, the contract still says otherwise, and a client written against the contract will ask for the number it says is allowed. |
| `SEC-ARRAY-UNBOUNDED` | WARN | `validate` | A request accepts an array with no `maxItems`. | Declare a ceiling. The cost is not the array, it is the work done per element; if the server already enforces a limit, say so in the description so a caller can find it. |
| `SEC-COLLECTION-UNPAGINATED` | WARN | `validate` | A read returns an array and declares no pagination parameter. | Add `limit` and a cursor. Response size then follows something the caller asked for, instead of following how much data happens to exist. |
| `SEC-RATE-LIMIT-LEGACY-FIELDS` | INFO | `validate` | The contract declares the three-field `RateLimit-Limit`/`-Remaining`/`-Reset` set. | Nothing, deliberately. Later revisions of the same draft replaced it with the two-field `RateLimit` / `RateLimit-Policy` pair, and the replacement is still a draft -- recommending a move to an unstable target is how a linter gets switched off. Recorded so the choice is a choice. |
| `SEC-RATE-LIMIT-METADATA` | INFO | `validate` | No rate-limit metadata is declared anywhere in the contract. | Declare the `RateLimit` headers you return, or describe the limits in the description. An undocumented limit is one every client discovers in production. |
| `SEC-RATE-LIMIT-NO-429` | WARN | `validate` | An operation declares no 429, in a contract where other operations do. | Declare 429 here too, or say in the description that this operation is not limited. A caller cannot tell an operation with no limit from one whose limit nobody wrote down. |
| `SEC-RATE-LIMIT-NO-RETRY-AFTER` | WARN | `validate` | A declared 429 or 503 carries no `Retry-After`. | Declare `Retry-After` on the response (RFC 9110 section 10.2.3), as a delay in seconds or an HTTP-date. A client that cannot compute a backoff retries immediately, which turns a rate limit into an outage. |
| `SEC-RATE-LIMIT-VENDOR-HEADERS` | INFO | `validate` | The contract declares `X-RateLimit-*` headers, which no specification defines. | Nothing. Recorded because the standardised spellings are different -- `RateLimit` and `RateLimit-Policy`, from draft-ietf-httpapi-ratelimit-headers-11 (2026-05-23) -- and that document is an active Internet-Draft rather than an RFC, so moving is a judgement call rather than a fix. |

## Shape and transport

| Rule | Severity | Produced by | Fires when | Instead |
|---|---|---|---|---|
| `SEC-ADDL-PROPERTIES` | WARN | `validate` | A schema accepts properties it does not declare. | Set `additionalProperties: false` where the shape is closed. An open object is where an unexpected field reaches code that was not written for it. |
| `SEC-CORS-WILDCARD` | WARN | `validate` | A wildcard CORS origin is declared. | Name the origins. `*` cannot be combined with credentials, and where it is combined anyway the browser is the only thing enforcing the difference. |
| `SEC-HTTPS-POLICY` | WARN | `validate` | A server URL uses plain HTTP. | Use HTTPS. A localhost URL is exempt; anything else puts the credential and the payload on the wire in the clear. |

## Behaviour

Behaviour that changed while the contract stayed valid. Every case here is schema-legal -- an optional field that stopped being populated, an enum value that stopped appearing, a null rate that jumped -- which is exactly why no other check reports it. None is a defect on its own, so each finding carries the sample sizes behind it and the comparison declines to speak when they are too small.

| Rule | Severity | Produced by | Fires when | Instead |
|---|---|---|---|---|
| `SEMANTIC-FIELD-ABANDONED` | ERROR | `drift --corpus --against-corpus` | An optional field was populated in almost every response and is now populated in none. | Find out whether the service stopped setting it or the data went away. The schema still declares it, so nothing else reports this -- and every consumer reading it now gets nothing. If it is deliberate, remove it from the contract so the removal is a breaking change somebody reviews. |
| `SEMANTIC-FIELD-APPEARED` | INFO | `drift --corpus --against-corpus` | A field that was never present is now present in almost every response. | Nothing, unless the contract does not declare it -- in which case declare it. Additive, and recorded because an undeclared field consumers start relying on is the next breaking change. |
| `SEMANTIC-FIELD-INTERMITTENT` | WARN | `drift --corpus --against-corpus` | A field that was almost always present is now present much less often. | Check whether it is now conditional on something. A consumer that treated it as always-there is reading it sometimes, and will not notice until the branch that needed it runs. |
| `SEMANTIC-NULL-RATE-ROSE` | WARN | `drift --corpus --against-corpus` | A field is null far more often than it used to be. | Find out what stopped populating it. Nullable is nullable, so no schema check objects -- and the meaning of the response changed anyway. |
| `SEMANTIC-VALUE-GONE` | WARN | `drift --corpus --against-corpus` | A value the field used to return no longer appears. | Check whether that state is still reachable. The schema still permits the value, so a consumer with a branch for it has dead code and no way to find out; if the state is gone for good, narrow the enum so the removal is reviewed. |
| `SEMANTIC-VALUE-NEW` | WARN | `drift --corpus --against-corpus` | A field started returning a value it never returned before. | Check the contract declares it. A consumer that switched exhaustively on the old set now falls through, and a value absent from the enum is a contract violation nobody is validating. |

## Lifecycle

Deprecation with a date attached, or without one. `deprecated: true` is the whole of what OpenAPI says about retiring an operation -- no date, no migration target, no obligation -- so a contract can be deprecating something for six years and look identical on the day it is switched off. Dates and header shapes are checked against [RFC 9745](https://www.rfc-editor.org/rfc/rfc9745.html) (`Deprecation`, Standards Track, March 2025) and [RFC 8594](https://www.rfc-editor.org/rfc/rfc8594.html) (`Sunset`, Informational, May 2019), which use different date formats -- which is itself one of the checks.

| Rule | Severity | Produced by | Fires when | Instead |
|---|---|---|---|---|
| `LIFECYCLE-DEPRECATED-NO-GUIDANCE` | INFO | `validate` | A deprecated operation points nowhere. | Say what to call instead, in the description or through the `deprecation` link relation RFC 9745 defines. A caller who reads the flag still has to work out the replacement, and will guess. |
| `LIFECYCLE-DEPRECATED-NO-SUNSET` | WARN | `validate` | An operation is deprecated and names no retirement date. | Declare a `Sunset` response header (RFC 8594) or an `x-sunset` date. `deprecated: true` carries no date, so a caller cannot tell a deprecation that ends next quarter from one that has been open for six years. |
| `LIFECYCLE-HEADER-SHAPE` | WARN | `validate` | A `Sunset` or `Deprecation` header is declared in a shape its RFC does not define. | `Sunset` is an HTTP-date (`Sat, 31 Dec 2018 23:59:59 GMT`, RFC 8594); `Deprecation` is a structured-field Date (`@1688169599`, RFC 9745). Neither is `format: date-time`, and a client generated from that parses a shape the server does not send. |
| `LIFECYCLE-SUNSET-BEFORE-DEPRECATION` | ERROR | `validate` | The retirement date is earlier than the deprecation date. | Fix the dates. RFC 9745 states a `Sunset` timestamp MUST NOT be earlier than the `Deprecation` one: a resource cannot be withdrawn before it was deprecated. |
| `LIFECYCLE-SUNSET-PASSED` | ERROR | `validate` | A declared sunset date has passed and the operation is still here. | Remove the operation, or move the date to one the team still means. A retirement date nobody enforces teaches callers to ignore the next one. |
| `LIFECYCLE-SUNSET-WITHOUT-DEPRECATION` | WARN | `validate` | An operation declares a retirement date and is not marked deprecated. | Mark it `deprecated: true`. The contract is currently retiring something it never told anyone to stop using. |

## Authorization, between identities

| Rule | Severity | Produced by | Fires when | Instead |
|---|---|---|---|---|
| `AUTHZ-BFLA` | ERROR | `test --authz` | An operation answered for a caller the contract says lacks its scope. | Either the handler does not check the scope, or the profile is wrong about what that identity holds. Both are worth knowing and only one of them is a defect in the service, so check the profile before filing a bug. |
| `AUTHZ-BOLA-DELETE` | ERROR | `test --authz` | One identity deleted an object another identity created. | The same fix. Reported separately from the read because stopping at the first finding would hide this one, and they are not equally bad. |
| `AUTHZ-BOLA-READ` | ERROR | `test --authz` | One identity read an object another identity created. | Resolve the object against the caller's tenant, not against the id alone. This is OWASP API1: the request is well-formed, the schema is satisfied, the status is 200, and the data belongs to somebody else -- which is why no schema check and no single-identity run can see it. |
| `AUTHZ-BOLA-WRITE` | ERROR | `test --authz` | One identity updated an object another identity created. | The same fix as the read, and worse if only this one fires: a service that hides another tenant's object from a GET and accepts a PATCH on it is checking visibility somewhere that is not the write path. |
| `AUTHZ-SCOPES-UNDECLARED` | INFO | `test --authz` | An identity states no scopes, so nothing checked what it may call. | Add `scopes: []` to the profile if it genuinely holds none. An unstated list is not a basis for a finding -- assuming an identity holds nothing would report every operation it can reach as a defect. |

## Generated SDKs

| Rule | Severity | Produced by | Fires when | Instead |
|---|---|---|---|---|
| `SDK-ENUM-VALUE-ADDED` | WARN | `breaking --sdk` | a response enum gained a value | roll it out behind a version, or stop declaring the field as a closed enum. Adding a value a client may receive is safe on the wire and unsafe in a generated closed type: a deserialization failure, or a match that is no longer exhaustive |
| `SDK-MODEL-NAME-CHANGED` | INFO | `breaking --sdk` | a response schema's title changed while its shape did not | keep the title and put the new wording in the description. Where model class names come from the title, the shape is identical and the class is renamed |
| `SDK-OPERATION-ID-ADDED` | INFO | `breaking --sdk` | an operation gained an operationId it did not have | nothing, if this is a deliberate move to declared operationIds. Clients generated before it used a name derived from the method and path, and that name is replaced, so it belongs in a major SDK version |
| `SDK-OPERATION-ID-CHANGED` | WARN | `breaking --sdk` | an operation kept its method and path and renamed its operationId | keep the old operationId and change the summary instead, or ship the rename as a major version of the generated SDK. Nothing about the request or the response moved, so no wire-level rule reports it and `diff` shows no change at all -- while every generated client's call site for the old name stops compiling |
| `SDK-OPERATION-ID-REMOVED` | WARN | `breaking --sdk` | an operation dropped its operationId | restore it. Generators fall back to a name derived from the method and path, so the method is not removed -- it is renamed to something the contract no longer states |
| `SDK-PARAMETER-ORDER-CHANGED` | WARN | `breaking --sdk` | the required parameters of an operation were reordered | restore the declaration order -- nothing about the request depends on it. Where a generator emits required parameters positionally, existing call sites keep compiling and start passing the arguments the other way round, which is the one finding in this family that is silent at build time |
| `SDK-TAG-NAMESPACE-CHANGED` | WARN | `breaking --sdk` | an operation's first tag changed | add the new tag alongside the old one rather than replacing it. Where a generator groups operations into a class per tag, this moves the method to a different client object |

## Governance

| Rule | Severity | Produced by | Fires when | Instead |
|---|---|---|---|---|
| `GOV-MISSING-OPERATION-ID` | INFO | `validate` | An operation has no `operationId`. | Give it one, unique across the document. Generated SDKs name methods from it, and without one the name is derived from the path -- so it changes whenever the path does. |
| `GOV-UNUSED-SECURITY-SCHEME` | INFO | `validate` | A security scheme is declared and required by no operation. | Remove it, or require it where it applies. A scheme in the document that nothing uses tells a reader the API supports an authentication method it does not, and that reader is often the one writing a client. |

## GraphQL federation

| Rule | Severity | Produced by | Fires when | Instead |
|---|---|---|---|---|
| `FED-EXTERNAL-ADDED` | WARN | `federation` | a field became @external: declared here, owned elsewhere | confirm another subgraph resolves it. @external says this subgraph names the field without providing it, which is correct for a key field and a mistake for anything the subgraph used to own |
| `FED-EXTERNAL-DANGLING` | ERROR | `federation` | an @external field no subgraph in this run resolves | pass every subgraph, or remove the @external declaration. This one is worth reading twice: a subgraph missing from the run is the likelier cause, which is why the finding says so rather than asserting the field is unresolvable |
| `FED-INACCESSIBLE-ADDED` | ERROR | `federation` | a field became @inaccessible, so it left the supergraph without leaving the subgraph | deprecate it in the supergraph first, then make it inaccessible. This is the change an SDL diff cannot see: the field is unchanged in the document, same name and same type, and every client loses it |
| `FED-KEY-CHANGED` | ERROR | `federation` | a @key an entity used to declare is gone | keep the old key alongside the new one until every subgraph has moved. A subgraph resolving references by the dropped key cannot do so any more, and it will not be the subgraph that changed |
| `FED-KEY-INCONSISTENT` | ERROR | `federation` | a type is an entity in one subgraph and not in another | add the same @key to the subgraphs that lack it. A subgraph cannot contribute fields to an entity it does not key |
| `FED-KEY-REMOVED` | ERROR | `federation` | a type stopped being an entity | restore the @key, or move every field that depends on it in the same change. Without a key no other subgraph can resolve a reference to the type, so every cross-subgraph join through it stops working |
| `FED-OWNERSHIP-MOVED` | WARN | `federation` | an @override changed which subgraph resolves a field | deploy both subgraphs together. The order decides whether there is a window in which neither resolves it, and nothing in either subgraph's own SDL says the other one moved |
| `FED-REQUIRES-UNKNOWN-FIELD` | WARN | `federation` | a @requires names a field no subgraph in this run defines on that type | pass every subgraph, or correct the selection. WARN rather than ERROR for the same reason as FED-EXTERNAL-DANGLING: an incomplete run and a broken selection look identical from here |
| `FED-SHAREABLE-REMOVED` | ERROR | `federation` | a field is no longer @shareable | remove the field from the other subgraph in the same release, or keep @shareable. If anything else resolves it, composition now rejects the graph |
| `FED-UNSHAREABLE-DUPLICATE` | ERROR | `federation` | two subgraphs resolve one field and it is not @shareable in all of them | mark it @shareable everywhere it is resolved, or remove it from all but one subgraph. Key fields are exempt: they are implicitly shareable and every subgraph keying the entity is required to declare them |

## Lint

| Rule | Severity | Produced by | Fires when | Instead |
|---|---|---|---|---|
| `LINT-AMBIGUOUS-COMPOSITION` | WARN | `validate` | A composition lists several branches with nothing to tell them apart. | Give the branches titles, or a discriminator. A reader -- and a code generator -- has to name these somehow, and without a hint the names come out as `Variant1`, `Variant2`. |
| `LINT-CONTRADICTORY-REQUIRED` | ERROR | `validate` | A schema requires a property it does not declare. | Declare the property, or drop it from `required`. As written the schema cannot be satisfied by any document, and a validator will reject every payload including the service's own. |
| `LINT-EMPTY-RESPONSE` | INFO | `validate` | A 2xx response declares neither content nor headers. | Nothing, if the operation really returns an empty body -- a 204 usually does. Otherwise describe what comes back: a consumer reading the contract sees an endpoint that returns nothing. |
| `LINT-INVALID-EXAMPLE` | WARN | `validate` | An example does not validate against the schema it illustrates. | Fix the example, or the schema -- one of them is wrong. An example is the part of a contract people copy, so a wrong one is a wrong request in somebody's client. |

## Objectives

| Rule | Severity | Produced by | Fires when | Instead |
|---|---|---|---|---|
| `SLO-MALFORMED` | WARN | `validate` | A declared objective is not a number, so nothing can be compared against it. | Write it as a bare number: `p95_ms: 250`, not `p95_ms: 250ms`. This is worse than a missing objective, because it looks declared and reads as declared in a review. |
| `SLO-NOT-MEASURABLE` | INFO | `validate` | An objective is understood and deliberately not evaluated by any run. | Nothing. `availability` and `uptime_pct` are promises over a window, and a run measures the requests it made and cannot see the ones it did not -- a figure computed here would be a fabrication with a decimal point on it. Reported so silence about it is not mistaken for a pass. |
| `SLO-NOT-MEASURED` | WARN | `regression` | An operation declares an objective and the run measured nothing for it. | Check the operation is reachable at the target. A declared objective with no measurement beside it reads as a pass, and a p95 of a connection timeout is not a latency. |
| `SLO-RUN-EXCEEDS-OBJECTIVE` | ERROR | `regression` | This run measured a value past the objective the contract declares. | Look at the operation -- and read the sample count first. An objective is a promise over a window and a run is a sample of it, so this is a reason to investigate rather than a judgement that the objective was missed. |
| `SLO-UNDECLARED` | INFO | `validate` | An operation states no objective, in a contract where others do. | Nothing, unless you meant to. An operation with no stated objective is not a defect -- it is an operation nobody promised anything about. |
| `SLO-UNKNOWN-OBJECTIVE` | WARN | `validate` | An operation declares an objective this tool does not measure. | Rename it to one of the measured objectives, or accept that nothing checks it. An objective nothing compares against is a promise nobody checks. |

## Outbound guardrails

| Rule | Severity | Produced by | Fires when | Instead |
|---|---|---|---|---|
| `GUARD-PAYLOAD-CREDENTIAL` | ERROR | `test` | a generated payload carried something credential-shaped, and was not sent | check the contract first: the value came from an example, a default or an enum member, and `apiverity validate` reports committed secrets in examples. If the field is a token field and the example is not a real credential, pass --allow-credential-payloads. The check runs before the request rather than after it, because a finding about a credential this process already posted is a finding about something nobody can take back |
| `GUARD-PAYLOAD-SIZE` | WARN | `test` | a generated payload was larger than the outbound guardrail, and was not sent | raise it with --max-payload-bytes if the target is meant to take a body that size. `maxLength: 10000000` is a legal schema and a boundary case asking for the largest valid value produces exactly that, which is a denial of service somebody wrote by running a test suite. The payload is refused rather than truncated: a shortened case is a case that did not test what it says it tested |

## Project configuration

`.apiverity.yaml`, checked by `apiverity config validate` and on every run that reads it. An ERROR here stops the run: a setting nobody reads is a setting the reader believes is active.

| Rule | Severity | Produced by | Fires when | Instead |
|---|---|---|---|---|
| `CONFIG-FAIL-ON-INVALID` | ERROR | `config validate` | `fail_on` is not one of error, warn or never. | Use one of the three. There is no `off`: a gate that never fails is `never`, which reports everything and is how you adopt the gate on an API that already has history. |
| `CONFIG-PROFILE-INVALID` | ERROR | `config validate` | `profile` names a severity profile that does not exist. | Use strict, balanced or advisory. `profile` was checked for type and not for value, so `profile: strikt` validated clean and then failed the run later with `internal error: unknown severity profile`. |
| `CONFIG-RULE-UNKNOWN` | WARN | `config validate` | A severity override names a rule id that is not in the catalogue. | Check the id against `apiverity rules`. A typo here is silent by nature: the override applies to nothing and the rule keeps its shipped severity. |
| `CONFIG-SEVERITY-INVALID` | ERROR | `config validate` | A severity override names something that is not a severity. | Use ERROR, WARN or INFO. There is no `OFF`: a rule you do not want is a suppression with an owner and an expiry, not a severity nobody defined. |
| `CONFIG-TYPE` | ERROR | `config validate` | A config key holds the wrong kind of value. | Give the key the shape the message names -- `severity_overrides` is a mapping of rule id to severity, not a list. |
| `CONFIG-UNKNOWN-KEY` | ERROR | `config validate` | `.apiverity.yaml` contains a key this build does not read. | Fix the spelling the message suggests, or delete the key. It is an error rather than a warning because `severity_overides` (one 'r') is a typo somebody will make, and a tool that ignored it would report that nothing is wrong while the override the reader believes is active does nothing. |
| `CONFIG-VALUE-INVALID` | ERROR | `config validate` | A config key holds a value outside the range it accepts. | Use a value in range -- `suppression_max_days` is a count of days and must be at least 1, since a maximum of zero would mean no suppression could ever be written. |
| `CONFIG-VERSION-MISSING` | ERROR | `config validate` | `.apiverity.yaml` declares no `version`. | Add `version: 1`. The version is what lets a later build tell a file written for an older format from one with a mistake in it. |
| `CONFIG-VERSION-UNSUPPORTED` | ERROR | `config validate` | The config's `version` is not one this build understands. | Upgrade apiverity, or write the version this build supports. Reading a future config on a guess would apply settings whose meaning has changed. |

## Supply chain

| Rule | Severity | Produced by | Fires when | Instead |
|---|---|---|---|---|
| `SEC-DEP-OUTSIDE-TREE` | INFO | `validate` | A `$ref` climbs out of the entry document's directory. | Nothing inside a monorepo, where it is the normal shape. It becomes a defect the moment the document is published on its own, because the reader gets a `$ref` to nothing -- `apiverity export` bundles the tree, which is the portable form. |
| `SEC-DEP-REMOTE` | WARN | `validate` | A `$ref` names a URL, so part of the schema comes from another host. | Nothing, if that is the arrangement -- shared schemas are often published this way. Vendor the file into the contract's own tree if a third party deciding what your gate validates against is not acceptable. The report has to carry it either way: the verdict depended on a response nobody in the repository controls. |
| `SEC-DEP-UNPINNED` | WARN | `validate` | A remote `$ref` names no version, tag or commit. | Pin it -- a path carrying a semantic version, a `v2`, a commit or a dated iteration is one anybody can re-fetch. Without that, the same contract validated tomorrow may be validated against something else, and the diff between the two runs will blame your API. |

## The gate's escape hatch

The suppressions file, talking about itself. An entry that is not justified and bounded does not suppress -- it fails closed, the finding it named stays in the run, and `SUPPRESSION-INCOMPLETE` says which field is missing. A gate that could be quietened by an unsigned one-line entry is a gate that is already off.

| Rule | Severity | Produced by | Fires when | Instead |
|---|---|---|---|---|
| `SUPPRESSION-EXPIRED` | WARN | `breaking` | A suppression's expiry date has passed; it no longer silences anything. | Fix the finding, or write a new entry with a fresh `expires` date and a reason that says what changed. An expiry is the mechanism that makes somebody look again -- extending it without a new reason is the same as never having set one. |
| `SUPPRESSION-INCOMPLETE` | WARN | `breaking` | A suppression is missing a field it needs, so it suppressed nothing. | Add the fields the message names: `owner`, `reason`, and an `expires` date within the project's maximum. The entry fails closed, so the finding it named is still in the run -- this is not a second failure, it is the reason the first one is still there. |
| `SUPPRESSION-UNSCOPED` | INFO | `breaking` | A suppression silences its rule across every operation. | Nothing, if that is what you meant -- an API with no pagination does not need the pagination rule on forty operations. Add an `operation_key` if it is not: a rule silenced contract-wide will not fire on the operation added next month either. |

_90 check rules._
