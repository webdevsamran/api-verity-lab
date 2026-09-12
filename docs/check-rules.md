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

## Agent call budgets

| Rule | Severity | Produced by | Fires when | Instead |
|---|---|---|---|---|
| `BUDGET-EXCEEDED` | ERROR | `budget` | An operation was called more times in the window than its budget allows. | Raise the limit if the traffic is expected, or find what is calling it. The single most-cited security worry about agent traffic is exactly this: too many calls, not wrong ones. |
| `BUDGET-FORBIDDEN` | ERROR | `budget` | An operation budgeted at zero calls was called. | A zero budget is a prohibition. Either the caller should not have it or the budget is wrong, and both are decisions rather than tuning. |
| `BUDGET-OPERATION-UNKNOWN` | ERROR | `budget` | The budget names an operation the contract does not declare. | Fix the key. A limit on an operation that does not exist constrains nothing and reads as though it does. |
| `BUDGET-UNBUDGETED` | ERROR | `budget` | An operation was called and no limit covers it. | Add a limit, or set the budget to allow uncovered operations. Whether this is an error depends on the budget's own mode -- an allow-list is only an allow-list if the gaps fail. |
| `BUDGET-UNDATED-CALLS` | WARN | `budget` | Some calls carried no timestamp, so they could not be placed in a window. | Capture timestamps. A per-minute limit checked against undated calls is arithmetic on an unknown denominator. |
| `BUDGET-UNUSED` | INFO | `budget` | A limit covered nothing in this traffic. | Nothing, unless the operation was expected to be called. A budget nothing exercised is a budget nothing has tested. |

## AsyncAPI

| Rule | Severity | Produced by | Fires when | Instead |
|---|---|---|---|---|
| `ASYNCAPI-CHANNEL-NO-MESSAGE` | WARN | `validate` | A channel operation declares no message, so there is no payload to compare. | Declare the message, even as an empty schema. A channel with no payload is a channel every payload rule skips. |
| `ASYNCAPI-OPERATION-BAD-ACTION` | WARN | `validate` | An operation declares an action that is neither `send` nor `receive`. | Use one of the two. Direction is what decides whether a payload change breaks you or breaks your subscribers, so an unknown action makes that call impossible. |
| `ASYNCAPI-OPERATION-NO-CHANNEL` | WARN | `validate` | An operation's `channel` reference does not resolve. | Fix the `$ref`. An operation with no channel has no address and is not modelled as an operation at all. |

## Authorization, between identities

| Rule | Severity | Produced by | Fires when | Instead |
|---|---|---|---|---|
| `AUTHZ-BFLA` | ERROR | `test --authz` | An operation answered for a caller the contract says lacks its scope. | Either the handler does not check the scope, or the profile is wrong about what that identity holds. Both are worth knowing and only one of them is a defect in the service, so check the profile before filing a bug. |
| `AUTHZ-BOLA-DELETE` | ERROR | `test --authz` | One identity deleted an object another identity created. | The same fix. Reported separately from the read because stopping at the first finding would hide this one, and they are not equally bad. |
| `AUTHZ-BOLA-READ` | ERROR | `test --authz` | One identity read an object another identity created. | Resolve the object against the caller's tenant, not against the id alone. This is OWASP API1: the request is well-formed, the schema is satisfied, the status is 200, and the data belongs to somebody else -- which is why no schema check and no single-identity run can see it. |
| `AUTHZ-BOLA-WRITE` | ERROR | `test --authz` | One identity updated an object another identity created. | The same fix as the read, and worse if only this one fires: a service that hides another tenant's object from a GET and accepts a PATCH on it is checking visibility somewhere that is not the write path. |
| `AUTHZ-SCOPES-UNDECLARED` | INFO | `test --authz` | An identity states no scopes, so nothing checked what it may call. | Add `scopes: []` to the profile if it genuinely holds none. An unstated list is not a basis for a finding -- assuming an identity holds nothing would report every operation it can reach as a defect. |

## Consumers

| Rule | Severity | Produced by | Fires when | Instead |
|---|---|---|---|---|
| `CONSUMER-UNKNOWN-OPERATION` | ERROR | `breaking` | A registered consumer declares it uses an operation the contract does not declare. | Fix the registry or the contract. Blast-radius reporting is only as good as the registry, and an operation key that matches nothing silently drops that consumer out of every impact answer. |

## Cross-version compatibility

| Rule | Severity | Produced by | Fires when | Instead |
|---|---|---|---|---|
| `COMPAT-HEADER-REMOVED` | WARN | `breaking` | An operation removed a request header it used to declare. | If the service still reads it, declare it; if it does not, say so in a migration note. A header that silently stops mattering is one clients keep sending forever. |
| `COMPAT-HEADER-REQUIRED` | ERROR | `breaking` | An operation now requires a request header it did not require before. | Accept the request without it for a deprecation window, defaulting the value, and require it in the next major version. |
| `COMPAT-IDEMPOTENCY-REVOKED` | WARN | `breaking` | An operation declared itself idempotent before and no longer does. | Say whether the behaviour changed or only the documentation. Clients build retry policies on this, and a retry against a no-longer-idempotent operation is a duplicate write. |
| `COMPAT-MEDIA-ADDED` | INFO | `breaking` | An operation gained a media type. | Nothing, this is a note. |
| `COMPAT-MEDIA-REMOVED` | WARN | `breaking` | An operation dropped a media type it used to accept or return. | Keep accepting it, or version the operation. A client sending the old `Content-Type` gets a 415 and a client expecting the old `Accept` gets something it cannot parse. |
| `COMPAT-PAGINATION-CHANGED` | WARN | `breaking` | An operation's pagination parameters changed shape. | Keep the old parameters working alongside the new ones for a deprecation window. A client paging with a cursor against an offset API silently reads the first page forever. |
| `COMPAT-SECURITY-SCHEME-REMOVED` | ERROR | `breaking` | A security scheme was removed; clients authenticating with it cannot. | Keep the scheme until every consumer has migrated. Removing the way somebody authenticates is removing their access. |
| `COMPAT-SECURITY-TYPE-CHANGED` | ERROR | `breaking` | A security scheme changed type, so credentials of the old kind no longer fit. | Add the new scheme alongside the old one and retire the old one on a stated date, rather than changing what an existing scheme name means. |
| `COMPAT-SERVER-ADDED` | INFO | `breaking` | A server URL was added to the contract. | Nothing, this is a note. |
| `COMPAT-SERVER-REMOVED` | WARN | `breaking` | A server URL was removed from the contract. | Check who was pointed at it. A removed localhost entry is usually housekeeping; a removed environment is somebody's base URL. |
| `COMPAT-STATUS-ADDED` | INFO | `breaking` | An operation documents a status code it did not before. | Nothing, this is a note. A client with an exhaustive match on status codes may still want to know. |
| `COMPAT-STATUS-REMOVED` | WARN | `breaking` | An operation no longer documents a status code it used to. | Keep documenting it while any client still handles it, or state the removal in a migration note; a client branching on that status now has a branch nothing describes. |

## Document structure

| Rule | Severity | Produced by | Fires when | Instead |
|---|---|---|---|---|
| `SPEC-ALLOF-CONFLICT` | WARN | `validate` | An `allOf` could not be collapsed because its branches contradict each other. | Reconcile the branches -- two `type`s, or two incompatible constraints on one property. Until then the schema is compared uncollapsed, which produces noisier diffs. |
| `SPEC-FORMAT-OVERRIDDEN` | WARN | `validate` | The document was loaded as the format named on the command line rather than the one detection would have chosen. | Nothing, if that is what you meant -- the flag exists for a document detection gets wrong. Drop `--spec-format` to see what it would have picked. |
| `SPEC-OAUTH-FLOW-UNKNOWN` | WARN | `validate` | A security scheme declares an OAuth flow this parser does not model. | Check the flow name against the specification. The scheme is still carried; the flow's details are not, so scope-coverage reporting will be incomplete for it. |
| `SPEC-OP-DUPLICATE` | ERROR | `validate` | Two operations claim the same method and path. | Remove one. Which of them a client generator or a router picks is its choice, not yours. |
| `SPEC-OPID-DUPLICATE` | ERROR | `validate` | Two operations declare the same `operationId`. | Make them unique. Generators name client methods after this field, so a duplicate silently drops one of the two operations from the generated client. |
| `SPEC-PARAM-LOCATION` | ERROR | `validate` | A parameter declares an `in` value that is not a parameter location. | Use `path`, `query`, `header`, `cookie` or 3.2's `querystring`. An unknown location means the parameter is not modelled at all, so no rule sees it. |
| `SPEC-RESPONSE-MISSING` | WARN | `validate` | An operation declares no responses at all. | Declare at least the success response. An operation with no declared response cannot be drift-checked, mocked or fuzzed against anything. |
| `SPEC-SCHEMA-INVALID` | ERROR | `validate` | A schema position holds something that is not an object. | A schema has to be a mapping. A stray string or list here usually means an indentation slip in YAML. |
| `SPEC-SDL-BUILD` | WARN | `validate` | GraphQL SDL parsed, and building a schema from it failed. | Usually a type referenced and never defined. The operations that do resolve are still modelled, so this is a partial read rather than a failed one. |
| `SPEC-SDL-INVALID` | ERROR | `validate` | A GraphQL SDL document could not be parsed. | The parser's own message names the position. Nothing downstream runs on an unparsed schema. |
| `SPEC-STREAM-ITEM-SCHEMA-MISSING` | WARN | `validate` | A sequential media type -- SSE, JSON Lines, multipart -- declares no `itemSchema`, so nothing describes one item. | Add `itemSchema` (OpenAPI 3.2). `schema` describes the whole body and a stream has no whole body, so without it every rule, mock and drift check sees nothing here at all. |
| `SPEC-STREAM-ITEM-SCHEMA-UNUSED` | WARN | `validate` | `itemSchema` is declared on a media type that is not sequential, so nothing reads it. | Use `schema` for a single document, or change the media type to a sequential one such as `application/jsonl` or `text/event-stream`. |
| `SPEC-TAG-PARENT-UNKNOWN` | WARN | `validate` | A hierarchical tag names a parent tag the document does not declare. | Declare the parent, or drop the `parent` field. A dangling parent leaves the tag orphaned in any navigation built from the hierarchy. |
| `SPEC-VERSION-UNSUPPORTED` | ERROR | `validate` | The document declares an OpenAPI version this parser does not read. | Check the `openapi` field. 3.0, 3.1 and 3.2 are supported, and Swagger 2.0 is read through its own parser. |

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

## Ghost routes

| Rule | Severity | Produced by | Fires when | Instead |
|---|---|---|---|---|
| `GHOST-GONE` | INFO | `ghosts` | A route that was removed from the contract is also gone from the deployment. | Nothing, this is the good outcome, and it is reported so that a clean run still shows what was checked. |
| `GHOST-NOT-PROBED` | INFO | `ghosts` | A candidate was skipped because its method writes. | Nothing automatic. A route auditor that issued a DELETE to find out whether a route still exists would find out, and so would the data. Check it by hand if it matters. |
| `GHOST-PATH-ALIVE` | WARN | `ghosts` | The path answers, for a method other than the one probed. | Check what is still mounted there. The route is alive even though the specific operation is not, which usually means a framework catch-all rather than a deliberate handler. |
| `GHOST-ROUTE` | ERROR | `ghosts` | A route answered and no contract declares it. | Remove the handler, or declare the route. An endpoint nobody documented is an endpoint nobody reviewed, versioned or rate-limited on purpose. |
| `GHOST-UNREACHABLE` | INFO | `ghosts` | A candidate could not be probed, so this run establishes nothing about it. | Check the base URL and the network, then re-run. Recorded rather than dropped because a route nobody could reach is not a route anybody confirmed gone. |

## Governance

| Rule | Severity | Produced by | Fires when | Instead |
|---|---|---|---|---|
| `GOV-MISSING-OPERATION-ID` | INFO | `validate` | An operation has no `operationId`. | Give it one, unique across the document. Generated SDKs name methods from it, and without one the name is derived from the path -- so it changes whenever the path does. |
| `GOV-UNUSED-SECURITY-SCHEME` | INFO | `validate` | A security scheme is declared and required by no operation. | Remove it, or require it where it applies. A scheme in the document that nothing uses tells a reader the API supports an authentication method it does not, and that reader is often the one writing a client. |
| `POLICY-RULE-CRASHED` | ERROR | `rules` | A policy rule raised while evaluating a contract. | Fix the rule. Reported rather than swallowed: a pack whose rule crashes is a gate a team believes is running, and silence would be the worst available answer. |

## GraphQL compatibility

| Rule | Severity | Produced by | Fires when | Instead |
|---|---|---|---|---|
| `GQL-ARGUMENT-NULLABILITY-TIGHTENED` | ERROR | `breaking` | An argument became non-null; callers omitting it or passing null fail. | Keep it nullable and reject null in the resolver with a clear error, until callers have stopped sending it. |
| `GQL-ARGUMENT-REMOVED` | ERROR | `breaking` | A field no longer accepts an argument; callers passing it fail validation. | Keep accepting and ignoring it for a deprecation window, then remove it. |
| `GQL-DANGEROUS-ARGUMENT-RELAXED` | WARN | `breaking` | An argument changed from required to nullable, so the server now has to handle its absence. | Confirm the resolver has a defined behaviour for null. Relaxing the schema without relaxing the resolver moves the failure from validation to runtime. |
| `GQL-DANGEROUS-FIELD-ADDED` | WARN | `breaking` | A field was added; clients that build selections from introspection change behaviour without changing code. | Nothing, if your clients use explicit selection sets. This is a note for the ones that do not. |
| `GQL-DANGEROUS-OPTIONAL-ARGUMENT-ADDED` | WARN | `breaking` | A field gained an optional argument. | Nothing, this is a note -- but check the default, because the behaviour clients get without passing it is now a decision somebody made. |
| `GQL-DANGEROUS-RETURN-RELAXED` | WARN | `breaking` | A field's return became nullable, so clients that assumed a value must now handle its absence. | Announce it. A generated client typed against the old schema will have non-optional types where the server can now send null. |
| `GQL-DRIFT-MISSING-FIELD` | ERROR | `drift` | The schema declares a field the endpoint does not serve. | This is the published contract being wrong about the running service. Deploy the field or take it out of the schema. |
| `GQL-DRIFT-MISSING-TYPE` | ERROR | `drift` | The schema declares a type the endpoint does not serve. | A client querying it gets a validation error against a schema you published. Deploy the type or remove it from the schema. |
| `GQL-DRIFT-UNDECLARED-FIELD` | WARN | `drift` | The endpoint serves a field the schema does not declare. | Add it to the committed schema, or remove it from the server. An undeclared field is one nobody reviewed and everybody can query. |
| `GQL-DRIFT-UNDECLARED-TYPE` | WARN | `drift` | The endpoint serves a type the schema does not declare. | Add it to the committed schema, or find out why the running server has it. Either way the schema and the service disagree about what exists. |
| `GQL-FIELD-REMOVED` | ERROR | `breaking` | A field was removed; queries selecting it fail validation. | Deprecate it with `@deprecated(reason:)` and remove it after clients have stopped selecting it -- which persisted operations or query logs can tell you. |
| `GQL-REQUIRED-ARGUMENT-ADDED` | ERROR | `breaking` | A field gained a required argument; every existing query omitting it fails. | Add it as nullable with a server-side default, and make it required in a later version. |
| `GQL-RETURN-NONNULL-TIGHTENED` | ERROR | `breaking` | A field's return became non-null, so a resolver returning null now errors the whole selection. | Keep it nullable unless every resolver path provably returns a value; in GraphQL a null in a non-null position nulls out the parent as well. |
| `GQL-RETURN-TYPE-CHANGED` | ERROR | `breaking` | A field's return type changed; selections written against the old type fail. | Add a new field with the new type and deprecate the old one. A type change in place has no migration window. |

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

## MCP authentication

| Rule | Severity | Produced by | Fires when | Instead |
|---|---|---|---|---|
| `MCP-AUTH-ANONYMOUS-LIST` | ERROR | `drift` | The server returned its whole tool list to a request carrying no credentials. | Require authentication on `tools/list`. The tool list is the map of what this server can be made to do, and roughly half of the internet-exposed MCP servers catalogued in 2026 handed it to anybody who asked. |
| `MCP-AUTH-ENFORCED` | INFO | `drift` | An unauthenticated `tools/list` was refused. | Nothing, this is the good outcome, and it is recorded so a clean run still shows what was established. |
| `MCP-AUTH-INDETERMINATE` | INFO | `drift` | The unauthenticated probe did not complete, so whether this server requires credentials was not established. | Re-run when the server is reachable. This is the absence of an answer, not an answer -- and reporting it as either would be a claim nobody measured. |
| `MCP-AUTH-NO-CHALLENGE` | WARN | `drift` | The refusal carried no `WWW-Authenticate` header. | Send one. Without it a client cannot tell what kind of credential to get, so it retries with whatever it already has. |
| `MCP-AUTH-PLAINTEXT-TRANSPORT` | WARN | `drift` | The endpoint is plain HTTP. | Use TLS. Every tool call, argument and result on this connection is readable by anything on the path, including the credentials that authorise them. |

## MCP inventory

| Rule | Severity | Produced by | Fires when | Instead |
|---|---|---|---|---|
| `MCP-INVENTORY-CONFIG-UNREADABLE` | WARN | `mcp-inventory` | A configuration file exists and could not be read, so the servers it configures were not inventoried. | Fix the permissions or the syntax. An unread config is a set of servers this run says nothing about, which is not the same as none. |
| `MCP-INVENTORY-UNCONFIGURED` | INFO | `mcp-inventory` | An approved server was not found in any configuration this run read. | Nothing, if it is meant to be available and unused. It is reported so the approved list does not quietly accumulate entries nobody has. |
| `MCP-INVENTORY-UNREADABLE` | ERROR | `mcp-inventory` | A source named on the command line could not be read. | Check the path. Named explicitly and missing is an error, where a config file this tool merely knows about is not. |
| `MCP-SHADOW-FETCHED-AT-LAUNCH` | WARN | `mcp-inventory` | A server is started by a command that fetches its code at launch. | Pin the version, or vendor the package. The code that starts tomorrow is whatever the registry serves tomorrow, which is the supply-chain shape behind OWASP MCP04. |
| `MCP-SHADOW-INLINE-CREDENTIAL` | ERROR | `mcp-inventory` | A server configuration carries a literal credential value. | Move it to the environment or a secret store and rotate it. A client config file is synced, backed up and frequently committed. |
| `MCP-SHADOW-PLAINTEXT-URL` | WARN | `mcp-inventory` | A server is configured over plain HTTP. | Use HTTPS. Every tool call to it, and every result from it, is readable on the path. |
| `MCP-SHADOW-SERVER` | ERROR | `mcp-inventory` | A configured server is not on the approved list. | Approve it or remove it. A server nobody approved is a set of tools nobody reviewed, reachable by every agent on this machine. |

## MCP lockfile

| Rule | Severity | Produced by | Fires when | Instead |
|---|---|---|---|---|
| `MCP-LOCK-SIGNATURE-INVALID` | ERROR | `mcp-lock` | The lockfile's signature does not match its contents. | Do not trust this lock. It was edited by something that did not have the key, which is the case the signature exists for. |
| `MCP-LOCK-SIGNATURE-UNVERIFIED` | WARN | `mcp-lock` | The lockfile is signed and the key is not available here, so the signature was not checked. | Set the key environment variable. An unverified signature offers exactly as much assurance as no signature, and looks like more. |
| `MCP-LOCK-TOOL-ADDED` | ERROR | `mcp-lock` | A served tool is not in the baseline lockfile. | Review the tool and re-lock. Adding a tool broadens what every agent using this server can be talked into doing, which is a change worth a review even when the tool is benign. |
| `MCP-LOCK-UNSIGNED` | INFO | `mcp-lock` | The lockfile carries no signature. | Sign it if the lock matters. Unsigned, an edit to it is indistinguishable from a legitimate re-lock -- which makes the baseline as trustworthy as the file permissions on it. |

## MCP manifests

| Rule | Severity | Produced by | Fires when | Instead |
|---|---|---|---|---|
| `MCP-INPUT-SCHEMA-MISSING` | ERROR | `validate` | A tool declares no `inputSchema`, which the specification makes mandatory. | Declare one, even `{"type": "object"}`. Without it there is nothing to validate a call against, and an agent constructs arguments from the description alone. |
| `MCP-INPUT-SCHEMA-NOT-OBJECT` | ERROR | `validate` | A tool's `inputSchema` declares a type other than `object`. | Make it an object schema. Tool arguments are named, so anything else cannot describe a call. |
| `MCP-LIST-RESULT-INCOMPLETE` | WARN | `validate` | The envelope carries `resultType` without both `ttlMs` and `cacheScope`. | Declare all three or none. A partial caching envelope leaves a client to guess how long the tool list is good for. |
| `MCP-MANIFEST-TRUNCATED` | WARN | `validate` | This is one page of a paginated `tools/list`: `nextCursor` is set. | Capture the remaining pages before diffing. Every tool past this page reads as removed, which is a very loud way to discover pagination. |
| `MCP-PROTOCOL-ERA-UNOBSERVED` | INFO | `validate` | Which protocol era this manifest came from was not established. | Nothing, unless era matters to you -- capture the manifest with the negotiated version recorded. A saved document carries no record of the handshake that produced it, and guessing would be inventing a fact. |
| `MCP-SCHEMA-KEYWORD-UNMODELED` | WARN | `validate` | A JSON Schema keyword in a tool's schema is not represented in the normalized model. | Nothing to fix in the manifest. It is reported so that what the rules cannot see is visible, rather than being assumed absent. |
| `MCP-TOOL-DUPLICATE` | ERROR | `validate` | A tool name is declared more than once. | Rename or remove one. `tools/call` dispatches on the name, so which of the two an agent reaches is the server's implementation detail rather than your decision. |
| `MCP-TOOL-INVALID` | ERROR | `validate` | An entry in the tools list is not an object. | Fix the document. A non-object entry is skipped entirely, which quietly shrinks the surface every other rule sees. |
| `MCP-TOOL-NAME-MISSING` | ERROR | `validate` | A tool in the manifest has no `name`, which the specification requires. | Give it one. `tools/call` dispatches on the name, so a nameless tool is one no agent can invoke and no diff can track. |

## MCP runtime and conformance

| Rule | Severity | Produced by | Fires when | Instead |
|---|---|---|---|---|
| `MCP-CALL-RESULT-CREDENTIAL` | ERROR | `drift` | A tool's result contains something shaped like a credential. | Rotate it if it is one, and stop returning it. A tool result goes into the model's context, which is the last place a secret should be. |
| `MCP-CONF-CALL-CONTENT-BLOCK-UNKNOWN` | WARN | `drift` | A tool result carried a content block of a type the specification does not define. | Use a defined block type. A client that does not recognise it will drop it, so the part of the answer it carries silently disappears. |
| `MCP-CONF-INPUT-SCHEMA-MISSING` | ERROR | `drift` | A served tool has no `inputSchema`, which the specification requires. | Fix the server. An agent with no schema builds arguments out of the description. |
| `MCP-CONF-INPUT-SCHEMA-NOT-OBJECT` | ERROR | `drift` | A served tool's `inputSchema` is not an object schema. | Fix the server. Tool arguments are named, so no other type can describe them. |
| `MCP-CONF-LIST-ORDER-NONDETERMINISTIC` | INFO | `drift` | `tools/list` returned the same tools in a different order across two calls. | Nothing is broken -- order is not specified. It is reported because a lockfile or a diff taken across two runs will show noise that is not change. |
| `MCP-CONF-LIST-RESULT-INCOMPLETE` | WARN | `drift` | A `tools/list` result omitted a key the specification requires on it. | Fix the server. A client written to the specification reads that key. |
| `MCP-CONF-LIST-UNSTABLE` | ERROR | `drift` | Two `tools/list` calls on separate connections returned different tool sets. | Make the tool set the same for every connection. The specification says it MUST NOT vary by connection, and an agent that saw one set and called from the other gets a tool that is not there. |
| `MCP-CONF-SCHEMA-DIALECT` | INFO | `drift` | A served tool declares a JSON Schema dialect other than the one MCP specifies. | Usually nothing -- it is reported because a validator honouring the declared dialect may accept or reject arguments differently from one assuming MCP's. |
| `MCP-CONF-TOOL-NAME-MISSING` | ERROR | `drift` | A served tool has no `name`, which the specification requires. | Fix the server. Nothing can call a tool that has no name. |
| `MCP-DRIFT-ANNOTATION` | WARN | `drift` | A served tool's annotation hint differs from the declared one. | Reconcile them. Annotations are what a client uses to decide whether to ask a human first. |
| `MCP-DRIFT-CALL-ERROR-SHAPE` | WARN | `drift` | `tools/call` returned a JSON-RPC error rather than a tool result. | Tool failures belong in the result with `isError`, not in the transport. A protocol-level error is for a call that could not be dispatched. |
| `MCP-DRIFT-CALL-NO-STRUCTURED-CONTENT` | WARN | `drift` | A tool declares an `outputSchema` and returned no `structuredContent`. | Return it, or drop the schema. A declared output shape that never arrives is a promise the client cannot use. |
| `MCP-DRIFT-CALL-OUTPUT-SCHEMA` | ERROR | `drift` | A tool's `structuredContent` violates the `outputSchema` it declares. | Fix the handler or the schema. An agent parsing the result against the declared shape gets something else. |
| `MCP-DRIFT-LEGACY-SERVER` | INFO | `drift` | The server negotiated a pre-2026-07-28 protocol version. | Nothing, if that is expected. It is reported because the older era has different requirements, and a rule written for the new one would be wrong about this server. |
| `MCP-DRIFT-PAGINATION-CAPPED` | WARN | `drift` | `tools/list` was still returning a cursor when the page limit was reached. | Raise `--max-pages`. Everything past the cap was not read, so tools there are neither confirmed present nor reported missing. |
| `MCP-DRIFT-PROTOCOL-UNSUPPORTED` | ERROR | `drift` | The server negotiated a protocol version this tool cannot speak. | Nothing was checked past the handshake. Upgrade one side, or capture a manifest and check that instead. |
| `MCP-DRIFT-SCHEMA` | ERROR | `drift` | A served tool's schema differs from the one the manifest declares. | The finding names the change. The manifest is what a reviewer approved and the server is what agents call. |
| `MCP-DRIFT-SCHEMA-COMPATIBLE` | WARN | `drift` | A served tool's schema differs from the declared one in a way no breaking rule objected to. | Update the manifest so it describes what is served. The difference breaks nobody today; the manifest being wrong about the server is the thing that compounds. |
| `MCP-DRIFT-TOOL-MISSING` | ERROR | `drift` | A tool declared in the manifest is not served by the running server. | Deploy it or take it out of the manifest. An agent planning against the manifest will call a tool that is not there. |
| `MCP-DRIFT-TOOL-UNDECLARED` | WARN | `drift` | A tool is served and is absent from the manifest. | Add it, or stop serving it. Agents will discover it from `tools/list` and use it, which means a capability reached production without review. |

## MCP tool poisoning

| Rule | Severity | Produced by | Fires when | Instead |
|---|---|---|---|---|
| `MCP-ANNOTATION-ABSENT` | INFO | `validate` | Some tools declare no annotations at all. | Declare them. The specification's default for an undeclared `destructiveHint` is true, so a client honouring defaults must treat every one of those tools as destructive. |
| `MCP-ANNOTATION-CONTRADICTORY` | WARN | `validate` | A tool declares `readOnlyHint` and `destructiveHint` both true. | Pick one. The specification defines `destructiveHint` only when `readOnlyHint` is false, so these say two incompatible things and a client believing either is guessing which. |
| `MCP-ANNOTATION-CONTRADICTS-NAME` | WARN | `validate` | A tool claims `readOnlyHint` while its name says otherwise. | Check which is true and fix the other. The specification says annotations are untrusted unless the server is, so this is reported for a human to decide -- no gate in this tool consults the hint either way. |
| `MCP-POISON-CREDENTIAL-PATH` | ERROR | `validate` | A tool description names a credential location in prose. | Declare what the tool reads in `inputSchema`, where a caller can see it. A tool that legitimately reads a credential says so in its schema; one that points the agent at a path in prose is asking for something nobody approved. |
| `MCP-POISON-CROSS-TOOL` | WARN | `validate` | A tool description names another tool alongside an instruction. | Keep each description about its own tool. A description that changes how a *different* tool is used is a change nobody reviewing that tool would see. |
| `MCP-POISON-DESCRIPTION-OUTSIZED` | INFO | `validate` | A tool description is far longer than the rest of the manifest's. | Nothing on its own -- length is not an attack. It is a place to look, because an injected payload has to go somewhere and a description is where it fits. |
| `MCP-POISON-HIDDEN-MARKUP` | WARN | `validate` | A tool description hides text inside markup -- an HTML comment, say. | Remove it. A client rendering the description as markdown shows nothing while the model reads all of it. |
| `MCP-POISON-INSTRUCTION` | WARN | `validate` | A tool description contains a sentence addressed to the agent rather than a description of the tool. | Rewrite it to describe what the tool does. In MCP the description is what the agent routes on, so a sentence aimed at the agent is executable text, not documentation. |
| `MCP-POISON-INVISIBLE-TEXT` | ERROR | `validate` | A tool description carries characters that reach the model and not the human reviewing the manifest -- zero-width spaces, direction overrides, unicode tag characters. | Remove them. There is no legitimate reason for text the reviewer cannot see and the model can, which is the only reason to put it there. |

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

## Protobuf compatibility

| Rule | Severity | Produced by | Fires when | Instead |
|---|---|---|---|---|
| `PROTO-ENUM-VALUE-REMOVED` | ERROR | `breaking` | An enum value was removed; a peer still sending it produces an unknown value. | Reserve the number and the name instead of deleting them, and keep handling the value until senders have stopped. |
| `PROTO-FIELD-NUMBER-REUSE` | ERROR | `validate` | Two fields in one message claim the same number. | Give each field its own number. This does not compile with `protoc` either; it is reported here because a descriptor set can carry it. |
| `PROTO-FIELD-REMOVED` | WARN | `breaking` | A message field was removed. | Reserve the number and the name. Removing without reserving lets a future field take the number, and stored data then decodes into the wrong field. |
| `PROTO-MESSAGE-TYPE-CHANGED` | ERROR | `breaking` | An RPC's request or response message type changed, so the wire format changed under a name that did not. | Add a new RPC taking the new message and deprecate the old one. |
| `PROTO-PARSE-EMPTY` | ERROR | `validate` | The file parsed and declared no services and no messages. | Check the path and the syntax. An empty parse compared against anything reports every operation as removed, which is a very loud way to find a typo. |
| `PROTO-RESERVED-NAME-USED` | ERROR | `validate` | A field uses a name the message reserved. | Pick another name. Reserved names keep JSON and text-format encodings from resurrecting a removed field. |
| `PROTO-RESERVED-NUMBER-USED` | ERROR | `validate` | A field uses a number the message reserved. | Pick an unreserved number. The reservation exists because that number meant something else to data already written. |
| `PROTO-RPC-DUPLICATE` | ERROR | `validate` | A service declares the same RPC name twice. | Rename or remove one. Which of the two a generated stub binds to is the generator's choice, not yours. |
| `PROTO-RPC-REMOVED` | ERROR | `breaking` | An RPC was removed; existing stubs fail at runtime rather than at compile time. | Keep the method and return `UNIMPLEMENTED`, or reserve it, until callers have been rebuilt. |
| `PROTO-WIRE-TYPE-CHANGED` | ERROR | `breaking` | A field changed wire type; old and new peers misdecode each other's bytes. | Use a new field number for the new type and reserve the old one. A wire type change is not a schema change, it is a different message. |
| `PROTO-WIRE-WIDTH-CHANGED` | WARN | `breaking` | An integer field changed width, which is wire-compatible and truncates. | Check the range actually in use. A 64-bit value read into a 32-bit field is silently wrong rather than an error. |

## Reference resolution

| Rule | Severity | Produced by | Fires when | Instead |
|---|---|---|---|---|
| `SPEC-REF-ABSOLUTE-REFUSED` | WARN | `validate` | A reference names an absolute filesystem path, which was not followed. | Use a path relative to the document. An absolute path resolves to a different file on every machine, which is the opposite of what a committed contract is for. |
| `SPEC-REF-BUNDLE-CAPPED` | WARN | `validate` | Bundling stopped at a limit -- on files, remote fetches or depth -- so some references were not followed. | Raise the relevant limit if the contract is genuinely that large, or check whether a cycle is generating the work. Anything past the cap is unresolved, and unresolved means invisible to every rule. |
| `SPEC-REF-CYCLE` | ERROR | `validate` | A chain of `$ref`s returns to where it started. | Break the cycle, usually by making one side a named component that stops at a primitive. A self-referential schema has no finite expansion to compare. |
| `SPEC-REF-DEEP` | ERROR | `validate` | A `$ref` chain is longer than the resolver will follow. | Flatten it. A chain this long is usually an accident -- a component referencing a component referencing an alias -- and the depth limit exists so a malicious document cannot make the loader run forever. |
| `SPEC-REF-REMOTE-REFUSED` | WARN | `validate` | A reference names a URL, and remote fetching is off. | Pass `--allow-remote-refs` if you mean to fetch it, or vendor the document. Off by default because a URL in a contract turns reading a file into a network call to somebody else's host. |
| `SPEC-REF-UNREADABLE` | ERROR | `validate` | A referenced document could not be read or is not a JSON or YAML mapping. | Check the path and the file. A multi-file contract is only as loadable as its least available file. |
| `SPEC-REF-UNRESOLVED` | ERROR | `validate` | A `$ref` points at something this document does not contain. | Fix the pointer, or add the component it names. Everything downstream treats the referenced schema as absent, so an unresolved ref quietly shrinks what the rules can see. |

## Runtime drift

| Rule | Severity | Produced by | Fires when | Instead |
|---|---|---|---|---|
| `DRIFT-CONTENT-TYPE` | ERROR | `drift` | The service returned a media type the contract does not declare. | Declare it, or fix the handler. A client that negotiated on the contract will parse this with the wrong reader. |
| `DRIFT-HEADER` | WARN | `drift` | A response header the contract declares was missing from a real response. | Send it, or remove it from the contract. Headers carry pagination cursors and rate-limit budgets, which clients read rather than guess. |
| `DRIFT-MISSING-FIELD` | ERROR | `drift` | A field the contract declares required was absent from a real response. | Return it, or stop declaring it required. A consumer generated from this contract has a non-optional type where the service sends nothing. |
| `DRIFT-RESPONSE-CREDENTIAL` | ERROR | `drift` | A response carried something shaped like a credential. | Rotate it if it is one, and stop returning it. This is the finding worth acting on before confirming, because the cost of being wrong is asymmetric. |
| `DRIFT-RESPONSE-PII` | WARN | `drift` | A response carried something shaped like personal data. | Confirm the field is meant to be there and is declared as such. A shape match is a reason to look, not a finding of fact. |
| `DRIFT-SCHEMA` | ERROR | `drift` | The response body does not satisfy the declared schema. | The message names the position. Either the schema is out of date or the handler is, and the contract is what consumers built against. |
| `DRIFT-STATUS` | ERROR | `drift` | The service returned a status code the contract does not declare for that operation. | Declare it, or stop returning it. A status nobody documented is one every client handles by accident. |
| `DRIFT-UNDECLARED-FIELD` | WARN | `drift` | A real response carried a field the contract does not declare. | Declare it, or stop sending it. An undeclared field is one nobody reviewed, which is how personal data reaches a payload without a decision. |
| `DRIFT-UNREACHABLE` | ERROR | `drift` | The probe did not complete, so nothing was observed for this operation. | Check the base URL, the network and the authentication. This is the absence of a measurement, not a fault in the service -- and not evidence the service is fine either. |

## Semantic versioning

| Rule | Severity | Produced by | Fires when | Instead |
|---|---|---|---|---|
| `SEMVER-DECREASE` | ERROR | `breaking` | The declared version went backwards. | Fix the version. A version that goes backwards makes ordering meaningless for every tool that resolves by range. |
| `SEMVER-MAJOR-REQUIRED` | ERROR | `breaking` | Breaking changes were found and the version did not move to a new major. | Release it as a major, or make the change additive using the alternatives listed against the findings above. |
| `SEMVER-MINOR-REQUIRED` | WARN | `breaking` | Risky but non-breaking changes were found without a minor bump. | Release it as a minor. The change is additive, and additions are minors. |
| `SEMVER-NO-BUMP` | WARN | `breaking` | The contract changed materially and the version did not change at all. | Bump the version. A contract that changed under an unchanged version is one a consumer cannot detect having changed. |
| `SEMVER-UNPARSEABLE` | WARN | `breaking` | A version is not semver, so no policy could be applied to it. | Nothing about the change: use a version this tool can order. Without one, the bump can be classified but the number it lands on cannot. |

## Supply chain

| Rule | Severity | Produced by | Fires when | Instead |
|---|---|---|---|---|
| `SEC-DEP-OUTSIDE-TREE` | INFO | `validate` | A `$ref` climbs out of the entry document's directory. | Nothing inside a monorepo, where it is the normal shape. It becomes a defect the moment the document is published on its own, because the reader gets a `$ref` to nothing -- `apiverity export` bundles the tree, which is the portable form. |
| `SEC-DEP-REMOTE` | WARN | `validate` | A `$ref` names a URL, so part of the schema comes from another host. | Nothing, if that is the arrangement -- shared schemas are often published this way. Vendor the file into the contract's own tree if a third party deciding what your gate validates against is not acceptable. The report has to carry it either way: the verdict depended on a response nobody in the repository controls. |
| `SEC-DEP-UNPINNED` | WARN | `validate` | A remote `$ref` names no version, tag or commit. | Pin it -- a path carrying a semantic version, a `v2`, a commit or a dated iteration is one anybody can re-fetch. Without that, the same contract validated tomorrow may be validated against something else, and the diff between the two runs will blame your API. |

## Swagger 2.0

| Rule | Severity | Produced by | Fires when | Instead |
|---|---|---|---|---|
| `SWAGGER2-OAUTH-FLOW-LOSSY` | WARN | `validate` | OAuth flow metadata does not survive the conversion to the OpenAPI 3 model intact. | Check the converted scheme if you gate on scopes. Swagger 2.0's flow names and URL fields do not map one-to-one onto 3.x's. |
| `SWAGGER2-PARAM-IN` | ERROR | `validate` | A Swagger 2.0 parameter declares an `in` value that is not a location. | Use `path`, `query`, `header`, `formData` or `body`. An unknown location means the parameter is not modelled. |
| `SWAGGER2-SERVER-SYNTHESIZED` | INFO | `validate` | `host`, `basePath` and `schemes` were combined into a server URL. | Nothing, this is a note. It says where the base URL in the model came from, since Swagger 2.0 has no `servers` list to read it out of. |

## The gate's escape hatch

The suppressions file, talking about itself. An entry that is not justified and bounded does not suppress -- it fails closed, the finding it named stays in the run, and `SUPPRESSION-INCOMPLETE` says which field is missing. A gate that could be quietened by an unsigned one-line entry is a gate that is already off.

| Rule | Severity | Produced by | Fires when | Instead |
|---|---|---|---|---|
| `SUPPRESSION-EXPIRED` | WARN | `breaking` | A suppression's expiry date has passed; it no longer silences anything. | Fix the finding, or write a new entry with a fresh `expires` date and a reason that says what changed. An expiry is the mechanism that makes somebody look again -- extending it without a new reason is the same as never having set one. |
| `SUPPRESSION-INCOMPLETE` | WARN | `breaking` | A suppression is missing a field it needs, so it suppressed nothing. | Add the fields the message names: `owner`, `reason`, and an `expires` date within the project's maximum. The entry fails closed, so the finding it named is still in the run -- this is not a second failure, it is the reason the first one is still there. |
| `SUPPRESSION-UNSCOPED` | INFO | `breaking` | A suppression silences its rule across every operation. | Nothing, if that is what you meant -- an API with no pagination does not need the pagination rule on forty operations. Add an `operation_key` if it is not: a rule silenced contract-wide will not fire on the operation added next month either. |

## WSDL and SOAP documents

| Rule | Severity | Produced by | Fires when | Instead |
|---|---|---|---|---|
| `SPEC-WSDL-ENCODED` | WARN | `validate` | An operation declares `use="encoded"`, the SOAP section-5 encoding. | Move to document/literal if you can. Section-5 encoding puts an object graph on the wire that the schema does not describe, so what is validated and what is sent are different things. |
| `SPEC-WSDL-EXTERNAL-SCHEMA` | WARN | `validate` | An imported or included schema was not followed. | Inline it, or accept that the types it defines are unmodelled. A type nobody read is a type no rule can compare. |
| `SPEC-WSDL-NO-SERVICE` | WARN | `validate` | The document declares no `wsdl:service`, so no endpoint address is known. | Add the service element, or treat this as an abstract WSDL. Nothing can be probed at runtime without an address. |
| `SPEC-WSDL-NO-SOAP-BINDING` | WARN | `validate` | A port uses a binding that declares no `soap:binding`. | If it is a SOAP service, declare the binding. Without it there is no SOAPAction or style to compare, so the `BRK-SOAP-*` rules cannot fire for it. |
| `SPEC-WSDL-PORTTYPE-UNBOUND` | WARN | `validate` | A portType is reachable from no service port, so nothing exposes it. | Bind it or remove it. An unbound portType is a set of operations no client can reach and every diff still compares. |
| `SPEC-WSDL-PREFIX-REBOUND` | WARN | `validate` | A namespace prefix is bound to more than one URI in the document. | Rename one of the prefixes. References were resolved with the first binding, which may not be the one that was meant. |
| `SPEC-WSDL-UNMODELLED` | WARN | `validate` | A WSDL construct is not carried into the contract model. | Nothing, if the construct does not matter to your consumers. It is reported by name so that what the model does *not* know about is visible rather than assumed absent. |
| `SPEC-WSDL-UNRESOLVED` | ERROR | `validate` | A port or binding names something this document does not define. | Import the document that defines it, or fix the QName. An unresolved binding means the operations behind it are not modelled. |

## Workflows

| Rule | Severity | Produced by | Fires when | Instead |
|---|---|---|---|---|
| `WF-CLEANUP-UNKNOWN-VAR` | ERROR | `workflow` | Cleanup deletes a variable no step defines. | Fix the name. Cleanup that names nothing deletes nothing, and the run looks tidy while the resources remain. |
| `WF-DUP-STEP` | ERROR | `workflow` | Two steps in a workflow share a name. | Rename one. Steps refer to each other's outputs by name, so a duplicate makes every later reference ambiguous. |
| `WF-INCOMPLETE-CLEANUP` | WARN | `workflow` | A resource a workflow creates is never deleted in cleanup. | Delete it, or say why not. A workflow run against a real environment that leaves resources behind gets run once. |
| `WF-MISSING-VAR` | ERROR | `workflow` | A step uses a variable no earlier step defines. | Define it, or fix the name. The step will run with an unsubstituted placeholder, which usually reaches the service as a literal. |

_247 check rules._
