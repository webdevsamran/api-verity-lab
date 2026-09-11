"""Every `SEC-*` rule, in one place, so they can be looked up.

`apiverity explain BRK-RESP-FIELD-REMOVED` has worked since the breaking rules
got a catalogue. `apiverity explain SEC-CORS-WILDCARD` answered *"no rule with
id 'SEC-CORS-WILDCARD'"* -- about a rule the tool emits, in the command that
exists because a rule nobody understands gets suppressed rather than fixed.
Twenty-two security rules were in that state: reachable, documented nowhere,
and denied by the one command whose job is to explain them.

They live here rather than beside each check for the same reason `CATALOG`
lives in one module: a catalogue split across five files is a catalogue nobody
can enumerate, and `apiverity rules` needs to enumerate it.

`tests/unit/test_security_catalog.py` fails when a check emits an id this table
does not carry, or when this table carries one nothing emits. Both directions
matter: the first is a rule that cannot be explained, and the second is a rule
that is published and dead -- the defect this project has now found four times.
"""

from __future__ import annotations

from apiverity.core.model import Severity
from apiverity.rules.check_catalog import CheckRuleSpec
from apiverity.rules.check_catalog import spec as _spec

#: Kept as an alias so existing imports of `SecurityRuleSpec` keep working.
#: The shape moved to `rules/check_catalog.py` when the lifecycle checks needed
#: the same one: two catalogues with two generators and two documents would
#: drift, and having one is the entire point of having any.
SecurityRuleSpec = CheckRuleSpec


SECURITY_CATALOG: dict[str, CheckRuleSpec] = dict(
    [
        # --- authentication, as the document declares it ------------------
        _spec(
            "SEC-AUTH-MISSING",
            Severity.WARN,
            "An operation declares no authentication, and neither does the contract.",
            "Declare the scheme the operation actually requires. If it really is open, "
            "write `security: []` on it -- that is the documented way to say so, and it "
            "is the difference between a decision and an omission.",
        ),
        _spec(
            "SEC-UNAUTH-WRITE",
            Severity.WARN,
            "A mutating operation has no authentication declaration.",
            "Same edit as SEC-AUTH-MISSING, and more urgent: a POST or DELETE that a "
            "reader cannot tell is protected is one nobody will audit.",
        ),
        _spec(
            "SEC-AUTH-ANONYMOUS",
            Severity.INFO,
            "An operation explicitly declares anonymous access with `security: []`.",
            "Nothing. This is the document saying what it means, which is the outcome "
            "SEC-AUTH-MISSING asks for. Recorded so an audit can see the choice was made.",
        ),
        _spec(
            "SEC-AUTH-NOT-EXPRESSIBLE",
            Severity.INFO,
            "This contract format has nowhere to declare authentication.",
            "Nothing in the file. Record the requirement outside the contract -- and note "
            "that this is a limit of the format, not a gap in the API.",
        ),
        _spec(
            "SEC-AUTH-NOT-READ",
            Severity.INFO,
            "This format can express authentication, and this adapter does not read it.",
            "Nothing in the file. Reported so a clean security report is not mistaken for "
            "a verified one: the absence of findings here is the absence of a check.",
        ),
        _spec(
            "SEC-NO-AUTH-DECLARED",
            Severity.WARN,
            "The contract declares no security schemes at all.",
            "Declare the schemes the service uses under `components.securitySchemes`, even "
            "if a gateway enforces them -- a consumer generating a client reads this file, "
            "not your gateway.",
        ),
        _spec(
            "SEC-SCHEME-UNKNOWN",
            Severity.ERROR,
            "An operation requires a security scheme the contract never declares.",
            "Declare the scheme, or fix the name in the requirement. A generated client "
            "cannot authenticate against a scheme that does not exist.",
        ),
        _spec(
            "SEC-SCHEME-INCONSISTENT",
            Severity.WARN,
            "Operations of similar kinds require different schemes without an evident reason.",
            "Make the inconsistency deliberate and visible, or align them. An inconsistent "
            "surface is where the one unprotected endpoint hides.",
        ),
        # --- credentials, and where they are put --------------------------
        _spec(
            "SEC-APIKEY-IN-QUERY",
            Severity.ERROR,
            "A security scheme carries the API key in the query string.",
            "Move it to a header. URLs reach access logs, proxy logs, browser history and "
            "`Referer` headers by default, so a key in one is a key in a dozen places "
            "nobody is guarding.",
        ),
        _spec(
            "SEC-BASIC-AUTH",
            Severity.WARN,
            "A security scheme is HTTP Basic.",
            "Prefer a bearer token or OAuth 2.0. Basic sends a reusable password on every "
            "request, and it cannot be scoped, rotated per client, or revoked for one "
            "caller without changing it for all of them.",
        ),
        _spec(
            "SEC-SECRET-IN-CONTRACT",
            Severity.ERROR,
            "A literal credential appears in the contract document.",
            "Remove it and rotate it. A contract is committed, published and copied; "
            "treat anything that has been in one as disclosed.",
        ),
        _spec(
            "SEC-RESPONSE-CREDENTIAL",
            Severity.ERROR,
            "A response body carried something shaped like a credential.",
            "Stop returning it. The finding records the kind, the JSON pointer and the "
            "length -- never the value -- so this can be triaged without the artifact "
            "becoming a second copy of the secret.",
            produced_by="drift, replay",
        ),
        _spec(
            "SEC-SENSITIVE-HEADER",
            Severity.INFO,
            "A response declares a header that carries session or credential material.",
            "Nothing, usually: `Set-Cookie` on a login route is the point. Recorded so a "
            "reviewer can see which routes hand out session state.",
        ),
        _spec(
            "SEC-SENSITIVE-FIELD",
            Severity.INFO,
            "A field name suggests it carries personal or secret data.",
            "Check it is meant to cross this boundary, and that the redaction rules in "
            "`traffic/redact.py` cover it before any traffic capture touches disk.",
        ),
        # --- authorization scope ------------------------------------------
        _spec(
            "SEC-SCOPE-UNSCOPED",
            Severity.WARN,
            "An OAuth requirement names no scope, on a scheme that declares some.",
            "Name the scope the operation needs. Without one, any valid token opens it, "
            "whatever it was issued for -- which makes the scheme's scope list decorative.",
        ),
        _spec(
            "SEC-SCOPE-BROAD",
            Severity.WARN,
            "A required scope grants everything.",
            "Split it. One token that opens the whole surface is the same authorization "
            "model as no scopes at all, with more configuration.",
        ),
        # --- resource consumption -----------------------------------------
        _spec(
            "SEC-ARRAY-UNBOUNDED",
            Severity.WARN,
            "A request accepts an array with no `maxItems`.",
            "Declare a ceiling. The cost is not the array, it is the work done per "
            "element; if the server already enforces a limit, say so in the description "
            "so a caller can find it.",
        ),
        _spec(
            "SEC-COLLECTION-UNPAGINATED",
            Severity.WARN,
            "A read returns an array and declares no pagination parameter.",
            "Add `limit` and a cursor. Response size then follows something the caller "
            "asked for, instead of following how much data happens to exist.",
        ),
        _spec(
            "SEC-RATE-LIMIT-NO-429",
            Severity.WARN,
            "An operation declares no 429, in a contract where other operations do.",
            "Declare 429 here too, or say in the description that this operation is not "
            "limited. A caller cannot tell an operation with no limit from one whose "
            "limit nobody wrote down.",
        ),
        _spec(
            "SEC-RATE-LIMIT-NO-RETRY-AFTER",
            Severity.WARN,
            "A declared 429 or 503 carries no `Retry-After`.",
            "Declare `Retry-After` on the response (RFC 9110 section 10.2.3), as a delay "
            "in seconds or an HTTP-date. A client that cannot compute a backoff retries "
            "immediately, which turns a rate limit into an outage.",
        ),
        _spec(
            "SEC-RATE-LIMIT-VENDOR-HEADERS",
            Severity.INFO,
            "The contract declares `X-RateLimit-*` headers, which no specification defines.",
            "Nothing. Recorded because the standardised spellings are different -- "
            "`RateLimit` and `RateLimit-Policy`, from "
            "draft-ietf-httpapi-ratelimit-headers-11 (2026-05-23) -- and that document is "
            "an active Internet-Draft rather than an RFC, so moving is a judgement call "
            "rather than a fix.",
        ),
        _spec(
            "SEC-RATE-LIMIT-LEGACY-FIELDS",
            Severity.INFO,
            "The contract declares the three-field `RateLimit-Limit`/`-Remaining`/`-Reset` set.",
            "Nothing, deliberately. Later revisions of the same draft replaced it with the "
            "two-field `RateLimit` / `RateLimit-Policy` pair, and the replacement is still "
            "a draft -- recommending a move to an unstable target is how a linter gets "
            "switched off. Recorded so the choice is a choice.",
        ),
        _spec(
            "SEC-ABUSE-UNBOUNDED-PAGE-SIZE",
            Severity.WARN,
            "A page-size query parameter declares no `maximum`.",
            "Declare `maximum` on the parameter. If the server already caps it, the "
            "contract still says otherwise, and a client written against the contract will "
            "ask for the number it says is allowed.",
        ),
        _spec(
            "SEC-RATE-LIMIT-METADATA",
            Severity.INFO,
            "No rate-limit metadata is declared anywhere in the contract.",
            "Declare the `RateLimit` headers you return, or describe the limits in the "
            "description. An undocumented limit is one every client discovers in "
            "production.",
        ),
        # --- shape and transport ------------------------------------------
        _spec(
            "SEC-ADDL-PROPERTIES",
            Severity.WARN,
            "A schema accepts properties it does not declare.",
            "Set `additionalProperties: false` where the shape is closed. An open object "
            "is where an unexpected field reaches code that was not written for it.",
        ),
        _spec(
            "SEC-CORS-WILDCARD",
            Severity.WARN,
            "A wildcard CORS origin is declared.",
            "Name the origins. `*` cannot be combined with credentials, and where it is "
            "combined anyway the browser is the only thing enforcing the difference.",
        ),
        _spec(
            "SEC-HTTPS-POLICY",
            Severity.WARN,
            "A server URL uses plain HTTP.",
            "Use HTTPS. A localhost URL is exempt; anything else puts the credential and "
            "the payload on the wire in the clear.",
        ),
    ]
)


SECURITY_CATALOG.update(
    dict(
        [
            _spec(
                "SEC-DEP-REMOTE",
                Severity.WARN,
                "A `$ref` names a URL, so part of the schema comes from another host.",
                "Nothing, if that is the arrangement -- shared schemas are often "
                "published this way. Vendor the file into the contract's own tree if a "
                "third party deciding what your gate validates against is not "
                "acceptable. The report has to carry it either way: the verdict "
                "depended on a response nobody in the repository controls.",
                produced_by="validate",
                family="Supply chain",
            ),
            _spec(
                "SEC-DEP-UNPINNED",
                Severity.WARN,
                "A remote `$ref` names no version, tag or commit.",
                "Pin it -- a path carrying a semantic version, a `v2`, a commit or a "
                "dated iteration is one anybody can re-fetch. Without that, the same "
                "contract validated tomorrow may be validated against something else, "
                "and the diff between the two runs will blame your API.",
                produced_by="validate",
                family="Supply chain",
            ),
            _spec(
                "SEC-DEP-OUTSIDE-TREE",
                Severity.INFO,
                "A `$ref` climbs out of the entry document's directory.",
                "Nothing inside a monorepo, where it is the normal shape. It becomes a "
                "defect the moment the document is published on its own, because the "
                "reader gets a `$ref` to nothing -- `apiverity export` bundles the tree, "
                "which is the portable form.",
                produced_by="validate",
                family="Supply chain",
            ),
        ]
    )
)


def spec_for(rule_id: str) -> CheckRuleSpec | None:
    """One rule, from any family -- not only the security one.

    A caller looking up `LIFECYCLE-SUNSET-PASSED` here does not care which
    module defines it, and answering "no such rule" because it belongs to a
    different table would be the defect this catalogue was built to fix.
    """
    from apiverity.rules.check_catalog import catalog

    return catalog().get(rule_id)


__all__ = ["SECURITY_CATALOG", "SecurityRuleSpec", "spec_for"]
