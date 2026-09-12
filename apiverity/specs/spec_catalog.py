"""Catalogue entries for the rules the parsers emit.

These are the first findings anybody sees. A document that will not resolve a
`$ref`, a Swagger 2.0 file whose OAuth metadata cannot survive the conversion, a
WSDL construct the model does not carry — every one of them is reported, and
none of them could be looked up: `apiverity explain SPEC-REF-UNRESOLVED` said
*"no rule with id ..."* about a rule the loader emits on a bad first run.

That is the worst place in the tool to have that gap. A reader whose very first
command produced a finding they could not explain has no reason to run a second
one.

## `SPEC-` is three families under one prefix

Reference resolution (`SPEC-REF-*`), OpenAPI structure (`SPEC-OP-*`,
`SPEC-PARAM-*`, `SPEC-VERSION-*`, `SPEC-TAG-*`, …), and WSDL (`SPEC-WSDL-*`).
They share a prefix because they share a cause — the document, rather than the
change — and they are given separate `family` values so
`docs/check-rules.md` does not put twenty-four unrelated rules under one
heading.

## Several of these are notes, and say so

`SWAGGER2-SERVER-SYNTHESIZED` and `SPEC-FORMAT-OVERRIDDEN` report a decision the
loader made, not a problem. Their remediation is "nothing, this is a note" —
written out rather than left blank, because a blank remediation reads as one
nobody got round to.
"""

from __future__ import annotations

from apiverity.core.model import Severity
from apiverity.rules.check_catalog import CheckRuleSpec, spec

_REFS = "Reference resolution"
_OPENAPI = "Document structure"
_WSDL = "WSDL and SOAP documents"

SPEC_CATALOG: dict[str, CheckRuleSpec] = dict(
    [
        # -- references ---------------------------------------------------
        spec(
            "SPEC-REF-UNRESOLVED",
            Severity.ERROR,
            "A `$ref` points at something this document does not contain.",
            "Fix the pointer, or add the component it names. Everything downstream treats "
            "the referenced schema as absent, so an unresolved ref quietly shrinks what the "
            "rules can see.",
            family=_REFS,
        ),
        spec(
            "SPEC-REF-CYCLE",
            Severity.ERROR,
            "A chain of `$ref`s returns to where it started.",
            "Break the cycle, usually by making one side a named component that stops at a "
            "primitive. A self-referential schema has no finite expansion to compare.",
            family=_REFS,
        ),
        spec(
            "SPEC-REF-DEEP",
            Severity.ERROR,
            "A `$ref` chain is longer than the resolver will follow.",
            "Flatten it. A chain this long is usually an accident -- a component referencing "
            "a component referencing an alias -- and the depth limit exists so a malicious "
            "document cannot make the loader run forever.",
            family=_REFS,
        ),
        spec(
            "SPEC-REF-UNREADABLE",
            Severity.ERROR,
            "A referenced document could not be read or is not a JSON or YAML mapping.",
            "Check the path and the file. A multi-file contract is only as loadable as its "
            "least available file.",
            family=_REFS,
        ),
        spec(
            "SPEC-REF-BUNDLE-CAPPED",
            Severity.WARN,
            "Bundling stopped at a limit -- on files, remote fetches or depth -- so some "
            "references were not followed.",
            "Raise the relevant limit if the contract is genuinely that large, or check "
            "whether a cycle is generating the work. Anything past the cap is unresolved, "
            "and unresolved means invisible to every rule.",
            family=_REFS,
        ),
        spec(
            "SPEC-REF-REMOTE-REFUSED",
            Severity.WARN,
            "A reference names a URL, and remote fetching is off.",
            "Pass `--allow-remote-refs` if you mean to fetch it, or vendor the document. "
            "Off by default because a URL in a contract turns reading a file into a network "
            "call to somebody else's host.",
            family=_REFS,
        ),
        spec(
            "SPEC-REF-ABSOLUTE-REFUSED",
            Severity.WARN,
            "A reference names an absolute filesystem path, which was not followed.",
            "Use a path relative to the document. An absolute path resolves to a different "
            "file on every machine, which is the opposite of what a committed contract is "
            "for.",
            family=_REFS,
        ),
        # -- OpenAPI structure --------------------------------------------
        spec(
            "SPEC-VERSION-UNSUPPORTED",
            Severity.ERROR,
            "The document declares an OpenAPI version this parser does not read.",
            "Check the `openapi` field. 3.0, 3.1 and 3.2 are supported, and Swagger 2.0 is "
            "read through its own parser.",
            family=_OPENAPI,
        ),
        spec(
            "SPEC-SCHEMA-INVALID",
            Severity.ERROR,
            "A schema position holds something that is not an object.",
            "A schema has to be a mapping. A stray string or list here usually means an "
            "indentation slip in YAML.",
            family=_OPENAPI,
        ),
        spec(
            "SPEC-PARAM-LOCATION",
            Severity.ERROR,
            "A parameter declares an `in` value that is not a parameter location.",
            "Use `path`, `query`, `header`, `cookie` or 3.2's `querystring`. An unknown "
            "location means the parameter is not modelled at all, so no rule sees it.",
            family=_OPENAPI,
        ),
        spec(
            "SPEC-OP-DUPLICATE",
            Severity.ERROR,
            "Two operations claim the same method and path.",
            "Remove one. Which of them a client generator or a router picks is its choice, "
            "not yours.",
            family=_OPENAPI,
        ),
        spec(
            "SPEC-OPID-DUPLICATE",
            Severity.ERROR,
            "Two operations declare the same `operationId`.",
            "Make them unique. Generators name client methods after this field, so a "
            "duplicate silently drops one of the two operations from the generated client.",
            family=_OPENAPI,
        ),
        spec(
            "SPEC-RESPONSE-MISSING",
            Severity.WARN,
            "An operation declares no responses at all.",
            "Declare at least the success response. An operation with no declared response "
            "cannot be drift-checked, mocked or fuzzed against anything.",
            family=_OPENAPI,
        ),
        spec(
            "SPEC-OAUTH-FLOW-UNKNOWN",
            Severity.WARN,
            "A security scheme declares an OAuth flow this parser does not model.",
            "Check the flow name against the specification. The scheme is still carried; "
            "the flow's details are not, so scope-coverage reporting will be incomplete "
            "for it.",
            family=_OPENAPI,
        ),
        spec(
            "SPEC-TAG-PARENT-UNKNOWN",
            Severity.WARN,
            "A hierarchical tag names a parent tag the document does not declare.",
            "Declare the parent, or drop the `parent` field. A dangling parent leaves the "
            "tag orphaned in any navigation built from the hierarchy.",
            family=_OPENAPI,
        ),
        spec(
            "SPEC-ALLOF-CONFLICT",
            Severity.WARN,
            "An `allOf` could not be collapsed because its branches contradict each other.",
            "Reconcile the branches -- two `type`s, or two incompatible constraints on one "
            "property. Until then the schema is compared uncollapsed, which produces noisier "
            "diffs.",
            family=_OPENAPI,
        ),
        spec(
            "SPEC-FORMAT-OVERRIDDEN",
            Severity.WARN,
            "The document was loaded as the format named on the command line rather than the "
            "one detection would have chosen.",
            "Nothing, if that is what you meant -- the flag exists for a document detection "
            "gets wrong. Drop `--spec-format` to see what it would have picked.",
            family=_OPENAPI,
        ),
        spec(
            "SPEC-STREAM-ITEM-SCHEMA-MISSING",
            Severity.WARN,
            "A sequential media type -- SSE, JSON Lines, multipart -- declares no "
            "`itemSchema`, so nothing describes one item.",
            "Add `itemSchema` (OpenAPI 3.2). `schema` describes the whole body and a stream "
            "has no whole body, so without it every rule, mock and drift check sees nothing "
            "here at all.",
            family=_OPENAPI,
        ),
        spec(
            "SPEC-STREAM-ITEM-SCHEMA-UNUSED",
            Severity.WARN,
            "`itemSchema` is declared on a media type that is not sequential, so nothing reads it.",
            "Use `schema` for a single document, or change the media type to a sequential "
            "one such as `application/jsonl` or `text/event-stream`.",
            family=_OPENAPI,
        ),
        spec(
            "SPEC-SDL-INVALID",
            Severity.ERROR,
            "A GraphQL SDL document could not be parsed.",
            "The parser's own message names the position. Nothing downstream runs on an "
            "unparsed schema.",
            family=_OPENAPI,
        ),
        spec(
            "SPEC-SDL-BUILD",
            Severity.WARN,
            "GraphQL SDL parsed, and building a schema from it failed.",
            "Usually a type referenced and never defined. The operations that do resolve are "
            "still modelled, so this is a partial read rather than a failed one.",
            family=_OPENAPI,
        ),
        # -- WSDL ----------------------------------------------------------
        spec(
            "SPEC-WSDL-UNMODELLED",
            Severity.WARN,
            "A WSDL construct is not carried into the contract model.",
            "Nothing, if the construct does not matter to your consumers. It is reported by "
            "name so that what the model does *not* know about is visible rather than "
            "assumed absent.",
            family=_WSDL,
        ),
        spec(
            "SPEC-WSDL-UNRESOLVED",
            Severity.ERROR,
            "A port or binding names something this document does not define.",
            "Import the document that defines it, or fix the QName. An unresolved binding "
            "means the operations behind it are not modelled.",
            family=_WSDL,
        ),
        spec(
            "SPEC-WSDL-NO-SOAP-BINDING",
            Severity.WARN,
            "A port uses a binding that declares no `soap:binding`.",
            "If it is a SOAP service, declare the binding. Without it there is no SOAPAction "
            "or style to compare, so the `BRK-SOAP-*` rules cannot fire for it.",
            family=_WSDL,
        ),
        spec(
            "SPEC-WSDL-NO-SERVICE",
            Severity.WARN,
            "The document declares no `wsdl:service`, so no endpoint address is known.",
            "Add the service element, or treat this as an abstract WSDL. Nothing can be "
            "probed at runtime without an address.",
            family=_WSDL,
        ),
        spec(
            "SPEC-WSDL-PORTTYPE-UNBOUND",
            Severity.WARN,
            "A portType is reachable from no service port, so nothing exposes it.",
            "Bind it or remove it. An unbound portType is a set of operations no client can "
            "reach and every diff still compares.",
            family=_WSDL,
        ),
        spec(
            "SPEC-WSDL-PREFIX-REBOUND",
            Severity.WARN,
            "A namespace prefix is bound to more than one URI in the document.",
            "Rename one of the prefixes. References were resolved with the first binding, "
            "which may not be the one that was meant.",
            family=_WSDL,
        ),
        spec(
            "SPEC-WSDL-EXTERNAL-SCHEMA",
            Severity.WARN,
            "An imported or included schema was not followed.",
            "Inline it, or accept that the types it defines are unmodelled. A type nobody "
            "read is a type no rule can compare.",
            family=_WSDL,
        ),
        spec(
            "SPEC-WSDL-ENCODED",
            Severity.WARN,
            'An operation declares `use="encoded"`, the SOAP section-5 encoding.',
            "Move to document/literal if you can. Section-5 encoding puts an object graph on "
            "the wire that the schema does not describe, so what is validated and what is "
            "sent are different things.",
            family=_WSDL,
        ),
    ]
)

SWAGGER2_CATALOG: dict[str, CheckRuleSpec] = dict(
    [
        spec(
            "SWAGGER2-PARAM-IN",
            Severity.ERROR,
            "A Swagger 2.0 parameter declares an `in` value that is not a location.",
            "Use `path`, `query`, `header`, `formData` or `body`. An unknown location means "
            "the parameter is not modelled.",
            family="Swagger 2.0",
        ),
        spec(
            "SWAGGER2-OAUTH-FLOW-LOSSY",
            Severity.WARN,
            "OAuth flow metadata does not survive the conversion to the OpenAPI 3 model intact.",
            "Check the converted scheme if you gate on scopes. Swagger 2.0's flow names and "
            "URL fields do not map one-to-one onto 3.x's.",
            family="Swagger 2.0",
        ),
        spec(
            "SWAGGER2-SERVER-SYNTHESIZED",
            Severity.INFO,
            "`host`, `basePath` and `schemes` were combined into a server URL.",
            "Nothing, this is a note. It says where the base URL in the model came from, "
            "since Swagger 2.0 has no `servers` list to read it out of.",
            family="Swagger 2.0",
        ),
    ]
)

ASYNCAPI_CATALOG: dict[str, CheckRuleSpec] = dict(
    [
        spec(
            "ASYNCAPI-CHANNEL-NO-MESSAGE",
            Severity.WARN,
            "A channel operation declares no message, so there is no payload to compare.",
            "Declare the message, even as an empty schema. A channel with no payload is a "
            "channel every payload rule skips.",
            family="AsyncAPI",
        ),
        spec(
            "ASYNCAPI-OPERATION-BAD-ACTION",
            Severity.WARN,
            "An operation declares an action that is neither `send` nor `receive`.",
            "Use one of the two. Direction is what decides whether a payload change breaks "
            "you or breaks your subscribers, so an unknown action makes that call "
            "impossible.",
            family="AsyncAPI",
        ),
        spec(
            "ASYNCAPI-OPERATION-NO-CHANNEL",
            Severity.WARN,
            "An operation's `channel` reference does not resolve.",
            "Fix the `$ref`. An operation with no channel has no address and is not "
            "modelled as an operation at all.",
            family="AsyncAPI",
        ),
    ]
)

__all__ = ["ASYNCAPI_CATALOG", "SPEC_CATALOG", "SWAGGER2_CATALOG"]
