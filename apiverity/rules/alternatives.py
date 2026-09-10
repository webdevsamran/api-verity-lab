"""What to ship instead, for every rule that objects to something.

A gate that only says no gets switched off. The finding "a response field was
removed; readers of it break" is correct and leaves the reader exactly where
they started: they still want the field gone, and nothing here has told them
how to get there without breaking anyone.

Almost every breaking change has a non-breaking route to the same destination,
and it is nearly always the same shape -- keep the old thing working while the
new one lands, and remove it in a version that says it removed things. Writing
that route down per rule turns an objection into a plan.

Three kinds of entry, and the distinction is deliberate
------------------------------------------------------
Most rules get an **alternative**: a concrete way to make the change additive.

Some rules describe something that is already safe -- `BRK-OP-ADDED`,
`BRK-ENUM-WIDENED` -- and get a sentence saying so rather than a fabricated
suggestion. Advice attached to a non-problem trains a reader to skim.

A few describe a situation with no smaller version of itself.
`BRK-MCP-MANIFEST-TRUNCATED` means the comparison is unsound; the answer is to
capture the whole manifest, which is not an alternative to the change, it is a
correction to the run. Those say what to do about the *report*.

Every rule in the catalogue has an entry. A test enforces it, because the value
of this table is that a reader can rely on it being there -- a rule with no
guidance, in a list where every other rule has some, reads as a rule nobody
thought about.
"""

from __future__ import annotations

from typing import Any

#: Rule id -> the non-breaking route to the same destination.
#:
#: Phrased as an instruction, not a description. "Keep returning the field" is
#: something a reader can do; "consumers may depend on the field" is something
#: they already knew.
ALTERNATIVES: dict[str, str] = {
    # --- operations ------------------------------------------------------
    "BRK-OP-REMOVED": (
        "Keep the operation and mark it deprecated, with a `Sunset` header giving the date it "
        "goes away (RFC 8594). Remove it in the next major. Callers get a warning window "
        "instead of a 404."
    ),
    "BRK-RPC-REMOVED": (
        "Keep the RPC and have it return an explicit error naming its replacement. A removed "
        "RPC is an UNIMPLEMENTED status with no explanation in it."
    ),
    "BRK-OP-ADDED": "Nothing to do: adding an operation cannot break an existing caller.",
    "BRK-RPC-ADDED": "Nothing to do: adding an RPC cannot break an existing caller.",
    "BRK-RPC-STREAMING-CHANGED": (
        "Add a new RPC with the new cardinality and deprecate the old one. Generated clients "
        "bind the streaming shape at compile time, so there is no in-place version of this."
    ),
    # --- protobuf --------------------------------------------------------
    "BRK-FIELD-NUMBER-REUSED": (
        "Use the next unused field number and add the old one to `reserved`. Stored messages "
        "written before this change decode the old number into the new field."
    ),
    "BRK-FIELD-NUMBER-UNRESERVED": (
        'Add `reserved <number>;` and `reserved "<name>";` in the same commit that removes '
        "the field. It costs one line and stops the number being handed out again."
    ),
    "BRK-FIELD-PRESENCE-LOST": (
        "Keep the field `optional` (proto3 explicit presence) so an unset value stays "
        "distinguishable from a zero. Removing presence silently merges the two for every "
        "reader."
    ),
    "BRK-ONEOF-NARROWED": (
        "Add a new field to the oneof rather than moving an existing one in. Moving one in "
        "makes it mutually exclusive with fields senders already set together."
    ),
    "BRK-ONEOF-WIDENED": "Nothing to do: no existing sender can observe the difference.",
    "BRK-RESERVATION-REMOVED": (
        "Put the reservation back. It exists to stop a retired number being reused, and "
        "removing it re-opens exactly that."
    ),
    # --- parameters ------------------------------------------------------
    "BRK-PARAM-REMOVED": (
        "Keep accepting the parameter and ignore it, or map it onto its replacement. Removing "
        "it turns an existing request into a rejected one, or worse, a silently different one."
    ),
    "BRK-PARAM-ADDED-REQUIRED": (
        "Add it optional with a server-side default, and make it required in the next major. "
        "Existing callers keep working while new ones start sending it."
    ),
    "BRK-PARAM-REQUIRED": (
        "Keep it optional and default it server-side. If the default is genuinely impossible "
        "to choose, that is a new operation rather than a stricter version of this one."
    ),
    "BRK-PARAM-ADDED-OPTIONAL": "Nothing to do: an optional parameter is additive.",
    "BRK-PARAM-OPTIONALIZED": "Nothing to do: senders that still supply it are unaffected.",
    "BRK-PARAM-TYPE-CHANGED": (
        "Add a new parameter with the new type and accept both for one release, preferring the "
        "new one when both arrive. A type change in place has no compatible form."
    ),
    # --- constraints and enums -------------------------------------------
    "BRK-CONSTRAINT-TIGHTENED": (
        "Tighten in two steps: keep accepting the out-of-range value and log or warn on it "
        "first, then reject in the next major. Alternatively, keep the declared bound and "
        "enforce the tighter one behind a feature flag until callers have moved."
    ),
    "BRK-CONSTRAINT-LOOSENED": "Nothing to do: inputs that were valid before are still valid.",
    "BRK-RESP-CONSTRAINT-TIGHTENED": (
        "Leave the declared bound alone unless you are certain no consumer validates the "
        "response against it. Narrowing what you promise to return breaks a strict client "
        "without breaking a request."
    ),
    "BRK-ENUM-NARROWED-REQUEST": (
        "Keep accepting the removed value and map it internally to its replacement. Drop it "
        "from the declared enum in the next major, once no caller is sending it."
    ),
    "BRK-ENUM-NARROWED-RESPONSE": (
        "Keep emitting the value until consumers stop reading it. A narrowed response enum "
        "breaks an exhaustive switch on the other side, which fails at the point of parse "
        "rather than at the point of use."
    ),
    "BRK-RESP-CONSTRAINT-LOOSENED": (
        "Keep the bound, or widen it in a release consumers are told about. A caller that "
        "validated the old bound -- or sized a column to it -- now receives values it "
        "rejects, and nothing in the response says the rule changed."
    ),
    "BRK-ENUM-WIDENED": (
        "Nothing to do for senders. Worth telling consumers, because a new response value "
        "reaches a client that was written when the set was closed."
    ),
    # --- request bodies ---------------------------------------------------
    "BRK-REQ-FIELD-REMOVED": (
        "Keep accepting the field and ignore it. Removing it from the schema turns a request "
        "that used to work into one that fails validation."
    ),
    "BRK-REQ-FIELD-ADDED-REQUIRED": (
        "Add it optional with a default, then require it in the next major."
    ),
    "BRK-REQ-FIELD-BECAME-REQUIRED": (
        "Default it server-side instead. If there is no sensible default, the operation is "
        "doing something new and deserves a new version rather than a stricter schema."
    ),
    "BRK-REQ-FIELD-OPTIONALIZED": "Nothing to do: senders that still supply it are unaffected.",
    "BRK-REQ-FIELD-ADDED-OPTIONAL": "Nothing to do: an optional request field is additive.",
    "BRK-REQ-BODY-REMOVED": (
        "Keep accepting a body and ignore it, so existing callers are not rejected for sending one."
    ),
    "BRK-REQ-BODY-ADDED-REQUIRED": (
        "Accept an empty body and apply defaults, then require it in the next major."
    ),
    "BRK-REQ-BODY-ADDED-OPTIONAL": "Nothing to do: an optional body is additive.",
    "BRK-REQ-BODY-REQUIRED": (
        "Accept an empty body and default its contents. A caller that sends none today gets a "
        "400 the moment this ships."
    ),
    # --- responses --------------------------------------------------------
    "BRK-RESP-FIELD-REMOVED": (
        "Keep returning the field until consumers stop reading it -- empty, null or a frozen "
        "value -- and mark it deprecated in the schema. Then remove it in the next major."
    ),
    "BRK-RESP-FIELD-OPTIONALIZED": (
        "Keep returning it unconditionally. Consumers written against a guarantee do not check "
        "for absence, so the first missing value is a crash rather than a fallback."
    ),
    "BRK-RESP-FIELD-ADDED": "Nothing to do: consumers ignore fields they do not know.",
    "BRK-RESP-FIELD-GUARANTEED": (
        "Nothing to undo -- a promise was strengthened, not withdrawn. Worth checking "
        "the server really does populate it in every path that returns this response, "
        "because the contract now says it does."
    ),
    "BRK-RESP-TYPE-CHANGED": (
        "Add a new field with the new type and keep the old one for a release. Changing a "
        "type in place misparses on every strongly-typed client."
    ),
    "BRK-RESP-STATUS-REMOVED": (
        "Keep declaring the status while the service can still return it. Removing it from the "
        "contract does not stop it happening; it stops clients being told it can."
    ),
    "BRK-RESP-STATUS-ADDED": (
        "Nothing to do, though a client with an exhaustive status handler will meet the new "
        "one before it has a branch for it."
    ),
    "BRK-HEADER-REMOVED": (
        "Keep sending the header until consumers stop reading it. A missing header is usually "
        "an empty string on the other side, which is a bug that looks like data."
    ),
    "BRK-HEADER-ADDED": "Nothing to do: a new response header is additive.",
    # --- JSON Schema 2020-12 ----------------------------------------------
    "BRK-DEPENDENT-REQUIRED-ADDED": (
        "Default the newly-required field server-side when its trigger is present, and make "
        "the dependency explicit in the next major. A caller that sets one field and not the "
        "other is sending a request that used to be valid."
    ),
    "BRK-DEPENDENT-REQUIRED-REMOVED": (
        "Harmless in a request. In a response, keep emitting the dependent field until "
        "consumers stop reading it: they were told it would always accompany the trigger."
    ),
    "BRK-DEPENDENT-SCHEMA-CHANGED": (
        "Keep accepting both shapes for one release. A conditional schema is the hardest kind "
        "of change for a caller to discover, because the failure only appears when a "
        "particular field is present."
    ),
    "BRK-TUPLE-SHAPE-CHANGED": (
        "Append rather than insert, and never change a position's type in place. Tuple members "
        "are read by index, so anything else shifts every reader after that point."
    ),
    "BRK-PATTERN-PROPERTIES-CHANGED": (
        "Widen the pattern rather than narrowing it, or add a second pattern beside the first. "
        "Narrowing one changes a whole family of fields at once, which is a large blast radius "
        "for a one-line edit."
    ),
    "BRK-PROPERTY-NAMES-CHANGED": (
        "Keep accepting the old key shape and normalise it internally. A constraint on names "
        "rejects the whole object rather than one field, so the error a caller sees points at "
        "the wrong place."
    ),
    "BRK-CONTAINS-CHANGED": (
        "Relax rather than tighten, or validate the new requirement at the edge and leave the "
        "declared one alone until callers have moved."
    ),
    "BRK-CONDITIONAL-SCHEMA-CHANGED": (
        "Review it by hand: `if`/`then`/`else` is the one construct whose severity cannot be "
        "read off the diff, because whether it tightens or relaxes depends on the condition. "
        "Where it tightens, the two-step route applies -- warn first, reject in the next major."
    ),
    # --- security and lifecycle -------------------------------------------
    "BRK-SECURITY-CHANGED": (
        "Accept both the old and the new scheme for one release, then drop the old one. An "
        "authentication change is the one break a client cannot retry its way out of."
    ),
    "BRK-DEPRECATION-ADDED": (
        "Nothing to fix -- this is the recommended path. Add a `Sunset` header with the "
        "removal date (RFC 8594) so the deprecation carries a deadline rather than a mood."
    ),
    "BRK-DEPRECATION-REMOVED": (
        "Nothing to do, but say so: consumers who started migrating on the deprecation should "
        "be told it was withdrawn."
    ),
    "BRK-MEDIA-TYPE-CHANGED": (
        "Keep serving the old media type behind content negotiation and add the new one "
        "alongside it. A client sending the old `Content-Type` gets a 415 otherwise."
    ),
    # --- MCP tool manifests -----------------------------------------------
    "BRK-MCP-TOOL-DESCRIPTION-CHANGED": (
        "If the wording changed, ship it. If the *behaviour* changed, rename the tool instead: "
        "an agent routes on the description, so an edited description silently changes what "
        "every existing plan does, with no version anywhere to pin against."
    ),
    "BRK-SOAP-ACTION-CHANGED": (
        "Keep the old soapAction on the existing operation and put the new one on a new "
        "operation in the same portType. The header is what a gateway routes on, so "
        "changing it retires the endpoint without saying so."
    ),
    "BRK-SOAP-STYLE-CHANGED": (
        "Add a second binding and a second port in the new style, and leave the old "
        "binding in place. A WSDL may declare as many ports as you like, so a style "
        "migration does not have to be a cutover."
    ),
    "BRK-SOAP-VERSION-CHANGED": (
        "Add a SOAP 1.2 port alongside the 1.1 one rather than replacing it. Both can "
        "point at the same portType and the same address, and clients move when they "
        "are rebuilt instead of when you deploy."
    ),
    "BRK-MCP-OUTPUT-SCHEMA-REMOVED": (
        "Keep declaring the outputSchema. A consumer parsing `structuredContent` was written "
        "against that guarantee, and withdrawing it does not change what the tool returns -- "
        "only what a caller is allowed to assume."
    ),
    "BRK-MCP-OUTPUT-SCHEMA-ADDED": (
        "Nothing to undo, but check the tool's own results conform to it from now on: "
        "declaring a schema makes every future result answerable to it."
    ),
    "BRK-MCP-READONLY-HINT-CLEARED": (
        "If the tool now writes, the rename is the honest change -- a host that auto-approved "
        "it as read-only will keep calling it without asking. If it does not write, put the "
        "hint back."
    ),
    "BRK-MCP-READONLY-HINT-SET": (
        "Only claim it if the tool truly performs no writes. Hosts stop asking for "
        "confirmation on this claim, and nothing verifies it."
    ),
    "BRK-MCP-DESTRUCTIVE-HINT-SET": (
        "Nothing to undo: declaring destructiveness is the safe direction. Tell hosts, because "
        "some will begin gating the call."
    ),
    "BRK-MCP-DESTRUCTIVE-HINT-CLEARED": (
        "Put it back unless the tool genuinely stopped performing irreversible updates. "
        "Clearing it removes a gate on the host side that nobody re-verified."
    ),
    "BRK-MCP-IDEMPOTENT-HINT-CLEARED": (
        "Nothing to undo if the tool really is not retry-safe -- this is the honest direction. "
        "Hosts that were retrying will stop."
    ),
    "BRK-MCP-IDEMPOTENT-HINT-SET": (
        "Only claim it if a repeated call with the same arguments has the same effect. Hosts "
        "retry on this claim, and a duplicated write is the failure mode."
    ),
    "BRK-MCP-OPENWORLD-HINT-CHANGED": (
        "Nothing to do: openWorldHint describes the domain a tool reaches into and constrains "
        "no caller."
    ),
    "BRK-MCP-ANNOTATION-DECLARATION-CHANGED": (
        "Nothing to do: the assertion did not change, only whether it was written down. "
        "Declaring it explicitly is the better form."
    ),
    "BRK-MCP-TOOL-RENAME-SUSPECTED": (
        "If this was a rename, keep the old name as an alias for one release: a manifest "
        "carries no identity but the name, so an agent holding a plan against the old one has "
        "nothing to fall back to."
    ),
    "BRK-MCP-MANIFEST-TRUNCATED": (
        "Nothing about the change: fix the *capture*. Follow `nextCursor` to the end of "
        "tools/list and compare complete manifests, because every tool past the page boundary "
        "currently reads as removed."
    ),
    # --- semver -----------------------------------------------------------
    "SEMVER-MAJOR-REQUIRED": (
        "Release it as a major, or make the change additive using the alternatives listed "
        "against the findings above."
    ),
    "SEMVER-MINOR-REQUIRED": "Release it as a minor. The change is additive, and additions are minors.",
    "SEMVER-NO-BUMP": (
        "Bump the version. A contract that changed under an unchanged version is one a "
        "consumer cannot detect having changed."
    ),
    "SEMVER-DECREASE": (
        "Fix the version. A version that goes backwards makes ordering meaningless for every "
        "tool that resolves by range."
    ),
    "SEMVER-UNPARSEABLE": (
        "Nothing about the change: use a version this tool can order. Without one, the bump "
        "can be classified but the number it lands on cannot."
    ),
}


def alternative_for(rule_id: str) -> str | None:
    """The published alternative for a rule, or None if the rule is unknown."""
    return ALTERNATIVES.get(rule_id)


def contextual(rule_id: str, change: Any = None) -> str | None:
    """The alternative, with the change's own specifics where they help.

    Only two families gain from being made concrete, and both are cases where
    the generic sentence leaves the reader hunting for the value: a narrowed
    enum, where the removed member is the thing to keep accepting, and a
    tightened constraint, where the old bound is the thing to keep declaring.
    Everywhere else the general sentence is already the whole instruction, and
    interpolating for its own sake would make it worse.
    """
    base = ALTERNATIVES.get(rule_id)
    if base is None or change is None:
        return base

    old_value = getattr(change, "old_value", None)
    new_value = getattr(change, "new_value", None)

    if rule_id in ("BRK-ENUM-NARROWED-REQUEST", "BRK-ENUM-NARROWED-RESPONSE"):
        if isinstance(old_value, list) and isinstance(new_value, list):
            removed = [v for v in old_value if v not in new_value]
            if removed:
                values = ", ".join(repr(v) for v in removed[:5])
                return f"{base} The value(s) to keep handling: {values}."
    elif (
        rule_id in ("BRK-CONSTRAINT-TIGHTENED", "BRK-RESP-CONSTRAINT-TIGHTENED")
        and old_value is not None
        and new_value is not None
    ):
        return f"{base} The bound moved {old_value!r} -> {new_value!r}."
    return base


__all__ = ["ALTERNATIVES", "alternative_for", "contextual"]
