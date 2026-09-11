"""Catalogue entries for the cross-version compatibility rules.

`apiverity explain BRK-RESP-FIELD-REMOVED` has always worked, because the
breaking rules have had a catalogue since the beginning. The rules in
`diff/compat.py`, `diff/protocol_compat.py`, the protobuf parser and the
GraphQL introspection check had none — so a reader who received
`COMPAT-MEDIA-REMOVED` or `PROTO-WIRE-TYPE-CHANGED` and looked it up was told
*"no rule with id ..."*, and reasonably concluded the catalogue was incomplete
rather than that the rule was.

This closes that for the diff lane. It was found by
`scripts/generate_landing_pages.py`, which lists the rules observed firing for
each protocol and had six of them with nothing to say.

## Why these are here and not in `rules/breaking.py`'s CATALOG

That catalogue is also the allow-list `core/config.py` validates
`severity_overrides` against, and `analyze_compat` does not apply overrides.
Adding these there would let a project write an override that passes validation
and changes nothing — a silently ignored setting, which is worse than a
rejected one.

The check catalogue documents without promising that, which is exactly the
claim available here.

## Severities that depend on the finding

Several of these are decided per finding: `COMPAT-STATUS-REMOVED` is a WARN for
a 2xx and INFO otherwise; `COMPAT-SERVER-REMOVED` is a WARN only for a local
server. The catalogue holds one value each, and it is the **worst** the rule
can produce, because a reader deciding whether to gate on a rule needs to know
what it can do rather than what it usually does.
"""

from __future__ import annotations

from apiverity.core.model import Severity
from apiverity.rules.check_catalog import CheckRuleSpec, spec

_HTTP = "Cross-version compatibility"
_GRAPHQL = "GraphQL compatibility"
_PROTO = "Protobuf compatibility"

COMPAT_CATALOG: dict[str, CheckRuleSpec] = dict(
    [
        spec(
            "COMPAT-STATUS-REMOVED",
            # WARN for a 2xx, INFO otherwise. The worse of the two is recorded.
            Severity.WARN,
            "An operation no longer documents a status code it used to.",
            "Keep documenting it while any client still handles it, or state the removal in "
            "a migration note; a client branching on that status now has a branch nothing "
            "describes.",
            produced_by="breaking",
            family=_HTTP,
        ),
        spec(
            "COMPAT-STATUS-ADDED",
            Severity.INFO,
            "An operation documents a status code it did not before.",
            "Nothing, this is a note. A client with an exhaustive match on status codes may "
            "still want to know.",
            produced_by="breaking",
            family=_HTTP,
        ),
        spec(
            "COMPAT-MEDIA-REMOVED",
            Severity.WARN,
            "An operation dropped a media type it used to accept or return.",
            "Keep accepting it, or version the operation. A client sending the old "
            "`Content-Type` gets a 415 and a client expecting the old `Accept` gets "
            "something it cannot parse.",
            produced_by="breaking",
            family=_HTTP,
        ),
        spec(
            "COMPAT-MEDIA-ADDED",
            Severity.INFO,
            "An operation gained a media type.",
            "Nothing, this is a note.",
            produced_by="breaking",
            family=_HTTP,
        ),
        spec(
            "COMPAT-HEADER-REMOVED",
            Severity.WARN,
            "An operation removed a request header it used to declare.",
            "If the service still reads it, declare it; if it does not, say so in a "
            "migration note. A header that silently stops mattering is one clients keep "
            "sending forever.",
            produced_by="breaking",
            family=_HTTP,
        ),
        spec(
            "COMPAT-HEADER-REQUIRED",
            Severity.ERROR,
            "An operation now requires a request header it did not require before.",
            "Accept the request without it for a deprecation window, defaulting the value, "
            "and require it in the next major version.",
            produced_by="breaking",
            family=_HTTP,
        ),
        spec(
            "COMPAT-SECURITY-SCHEME-REMOVED",
            Severity.ERROR,
            "A security scheme was removed; clients authenticating with it cannot.",
            "Keep the scheme until every consumer has migrated. Removing the way somebody "
            "authenticates is removing their access.",
            produced_by="breaking",
            family=_HTTP,
        ),
        spec(
            "COMPAT-SECURITY-TYPE-CHANGED",
            Severity.ERROR,
            "A security scheme changed type, so credentials of the old kind no longer fit.",
            "Add the new scheme alongside the old one and retire the old one on a stated "
            "date, rather than changing what an existing scheme name means.",
            produced_by="breaking",
            family=_HTTP,
        ),
        spec(
            "COMPAT-SERVER-ADDED",
            Severity.INFO,
            "A server URL was added to the contract.",
            "Nothing, this is a note.",
            produced_by="breaking",
            family=_HTTP,
        ),
        spec(
            "COMPAT-SERVER-REMOVED",
            # WARN when the removed server is local, INFO otherwise.
            Severity.WARN,
            "A server URL was removed from the contract.",
            "Check who was pointed at it. A removed localhost entry is usually housekeeping; "
            "a removed environment is somebody's base URL.",
            produced_by="breaking",
            family=_HTTP,
        ),
        spec(
            "COMPAT-IDEMPOTENCY-REVOKED",
            Severity.WARN,
            "An operation declared itself idempotent before and no longer does.",
            "Say whether the behaviour changed or only the documentation. Clients build "
            "retry policies on this, and a retry against a no-longer-idempotent operation "
            "is a duplicate write.",
            produced_by="breaking",
            family=_HTTP,
        ),
        spec(
            "COMPAT-PAGINATION-CHANGED",
            Severity.WARN,
            "An operation's pagination parameters changed shape.",
            "Keep the old parameters working alongside the new ones for a deprecation "
            "window. A client paging with a cursor against an offset API silently reads "
            "the first page forever.",
            produced_by="breaking",
            family=_HTTP,
        ),
    ]
)

GRAPHQL_COMPAT_CATALOG: dict[str, CheckRuleSpec] = dict(
    [
        spec(
            "GQL-FIELD-REMOVED",
            Severity.ERROR,
            "A field was removed; queries selecting it fail validation.",
            "Deprecate it with `@deprecated(reason:)` and remove it after clients have "
            "stopped selecting it -- which persisted operations or query logs can tell you.",
            produced_by="breaking",
            family=_GRAPHQL,
        ),
        spec(
            "GQL-DANGEROUS-FIELD-ADDED",
            Severity.WARN,
            "A field was added; clients that build selections from introspection change "
            "behaviour without changing code.",
            "Nothing, if your clients use explicit selection sets. This is a note for the "
            "ones that do not.",
            produced_by="breaking",
            family=_GRAPHQL,
        ),
        spec(
            "GQL-ARGUMENT-REMOVED",
            Severity.ERROR,
            "A field no longer accepts an argument; callers passing it fail validation.",
            "Keep accepting and ignoring it for a deprecation window, then remove it.",
            produced_by="breaking",
            family=_GRAPHQL,
        ),
        spec(
            "GQL-REQUIRED-ARGUMENT-ADDED",
            Severity.ERROR,
            "A field gained a required argument; every existing query omitting it fails.",
            "Add it as nullable with a server-side default, and make it required in a later "
            "version.",
            produced_by="breaking",
            family=_GRAPHQL,
        ),
        spec(
            "GQL-DANGEROUS-OPTIONAL-ARGUMENT-ADDED",
            Severity.WARN,
            "A field gained an optional argument.",
            "Nothing, this is a note -- but check the default, because the behaviour clients "
            "get without passing it is now a decision somebody made.",
            produced_by="breaking",
            family=_GRAPHQL,
        ),
        spec(
            "GQL-DANGEROUS-ARGUMENT-RELAXED",
            Severity.WARN,
            "An argument changed from required to nullable, so the server now has to handle "
            "its absence.",
            "Confirm the resolver has a defined behaviour for null. Relaxing the schema "
            "without relaxing the resolver moves the failure from validation to runtime.",
            produced_by="breaking",
            family=_GRAPHQL,
        ),
        spec(
            "GQL-ARGUMENT-NULLABILITY-TIGHTENED",
            Severity.ERROR,
            "An argument became non-null; callers omitting it or passing null fail.",
            "Keep it nullable and reject null in the resolver with a clear error, until "
            "callers have stopped sending it.",
            produced_by="breaking",
            family=_GRAPHQL,
        ),
        spec(
            "GQL-RETURN-TYPE-CHANGED",
            Severity.ERROR,
            "A field's return type changed; selections written against the old type fail.",
            "Add a new field with the new type and deprecate the old one. A type change in "
            "place has no migration window.",
            produced_by="breaking",
            family=_GRAPHQL,
        ),
        spec(
            "GQL-DANGEROUS-RETURN-RELAXED",
            Severity.WARN,
            "A field's return became nullable, so clients that assumed a value must now "
            "handle its absence.",
            "Announce it. A generated client typed against the old schema will have "
            "non-optional types where the server can now send null.",
            produced_by="breaking",
            family=_GRAPHQL,
        ),
        spec(
            "GQL-RETURN-NONNULL-TIGHTENED",
            Severity.ERROR,
            "A field's return became non-null, so a resolver returning null now errors the "
            "whole selection.",
            "Keep it nullable unless every resolver path provably returns a value; in "
            "GraphQL a null in a non-null position nulls out the parent as well.",
            produced_by="breaking",
            family=_GRAPHQL,
        ),
        spec(
            "GQL-DRIFT-UNDECLARED-TYPE",
            Severity.WARN,
            "The endpoint serves a type the schema does not declare.",
            "Add it to the committed schema, or find out why the running server has it. "
            "Either way the schema and the service disagree about what exists.",
            produced_by="drift",
            family=_GRAPHQL,
        ),
        spec(
            "GQL-DRIFT-MISSING-TYPE",
            Severity.ERROR,
            "The schema declares a type the endpoint does not serve.",
            "A client querying it gets a validation error against a schema you published. "
            "Deploy the type or remove it from the schema.",
            produced_by="drift",
            family=_GRAPHQL,
        ),
        spec(
            "GQL-DRIFT-UNDECLARED-FIELD",
            Severity.WARN,
            "The endpoint serves a field the schema does not declare.",
            "Add it to the committed schema, or remove it from the server. An undeclared "
            "field is one nobody reviewed and everybody can query.",
            produced_by="drift",
            family=_GRAPHQL,
        ),
        spec(
            "GQL-DRIFT-MISSING-FIELD",
            Severity.ERROR,
            "The schema declares a field the endpoint does not serve.",
            "This is the published contract being wrong about the running service. Deploy "
            "the field or take it out of the schema.",
            produced_by="drift",
            family=_GRAPHQL,
        ),
    ]
)

PROTO_CATALOG: dict[str, CheckRuleSpec] = dict(
    [
        spec(
            "PROTO-RPC-REMOVED",
            Severity.ERROR,
            "An RPC was removed; existing stubs fail at runtime rather than at compile time.",
            "Keep the method and return `UNIMPLEMENTED`, or reserve it, until callers have "
            "been rebuilt.",
            produced_by="breaking",
            family=_PROTO,
        ),
        spec(
            "PROTO-MESSAGE-TYPE-CHANGED",
            Severity.ERROR,
            "An RPC's request or response message type changed, so the wire format changed "
            "under a name that did not.",
            "Add a new RPC taking the new message and deprecate the old one.",
            produced_by="breaking",
            family=_PROTO,
        ),
        spec(
            "PROTO-WIRE-TYPE-CHANGED",
            Severity.ERROR,
            "A field changed wire type; old and new peers misdecode each other's bytes.",
            "Use a new field number for the new type and reserve the old one. A wire type "
            "change is not a schema change, it is a different message.",
            produced_by="breaking",
            family=_PROTO,
        ),
        spec(
            "PROTO-WIRE-WIDTH-CHANGED",
            Severity.WARN,
            "An integer field changed width, which is wire-compatible and truncates.",
            "Check the range actually in use. A 64-bit value read into a 32-bit field is "
            "silently wrong rather than an error.",
            produced_by="breaking",
            family=_PROTO,
        ),
        spec(
            "PROTO-ENUM-VALUE-REMOVED",
            Severity.ERROR,
            "An enum value was removed; a peer still sending it produces an unknown value.",
            "Reserve the number and the name instead of deleting them, and keep handling "
            "the value until senders have stopped.",
            produced_by="breaking",
            family=_PROTO,
        ),
        spec(
            "PROTO-FIELD-REMOVED",
            Severity.WARN,
            "A message field was removed.",
            "Reserve the number and the name. Removing without reserving lets a future "
            "field take the number, and stored data then decodes into the wrong field.",
            produced_by="breaking",
            family=_PROTO,
        ),
        spec(
            "PROTO-RESERVED-NUMBER-USED",
            Severity.ERROR,
            "A field uses a number the message reserved.",
            "Pick an unreserved number. The reservation exists because that number meant "
            "something else to data already written.",
            produced_by="validate",
            family=_PROTO,
        ),
        spec(
            "PROTO-RESERVED-NAME-USED",
            Severity.ERROR,
            "A field uses a name the message reserved.",
            "Pick another name. Reserved names keep JSON and text-format encodings from "
            "resurrecting a removed field.",
            produced_by="validate",
            family=_PROTO,
        ),
        spec(
            "PROTO-FIELD-NUMBER-REUSE",
            Severity.ERROR,
            "Two fields in one message claim the same number.",
            "Give each field its own number. This does not compile with `protoc` either; "
            "it is reported here because a descriptor set can carry it.",
            produced_by="validate",
            family=_PROTO,
        ),
        spec(
            "PROTO-RPC-DUPLICATE",
            Severity.ERROR,
            "A service declares the same RPC name twice.",
            "Rename or remove one. Which of the two a generated stub binds to is the "
            "generator's choice, not yours.",
            produced_by="validate",
            family=_PROTO,
        ),
        spec(
            "PROTO-PARSE-EMPTY",
            Severity.ERROR,
            "The file parsed and declared no services and no messages.",
            "Check the path and the syntax. An empty parse compared against anything "
            "reports every operation as removed, which is a very loud way to find a typo.",
            produced_by="validate",
            family=_PROTO,
        ),
    ]
)

__all__ = ["COMPAT_CATALOG", "GRAPHQL_COMPAT_CATALOG", "PROTO_CATALOG"]
