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


def spec_for(rule_id: str) -> CheckRuleSpec | None:
    """One rule, from any family -- not only the security one.

    A caller looking up `LIFECYCLE-SUNSET-PASSED` here does not care which
    module defines it, and answering "no such rule" because it belongs to a
    different table would be the defect this catalogue was built to fix.
    """
    from apiverity.rules.check_catalog import catalog

    return catalog().get(rule_id)


__all__ = ["SECURITY_CATALOG", "SecurityRuleSpec", "spec_for"]
