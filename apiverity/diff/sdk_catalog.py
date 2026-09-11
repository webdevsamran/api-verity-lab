"""The SDK-surface rules, for `explain` and the generated catalogue.

Each entry names the generator convention the rule depends on, because that is
the first question a reader has: *does this apply to my generator?* The rules
themselves carry the same assumption on every finding, in `metadata`.
"""

from __future__ import annotations

from apiverity.core.model import Severity
from apiverity.rules.check_catalog import CheckRuleSpec
from apiverity.rules.check_catalog import spec as _spec

_FAMILY = "Generated SDKs"
_BY = "breaking --sdk"

SDK_CATALOG: dict[str, CheckRuleSpec] = dict(
    [
        _spec(
            "SDK-OPERATION-ID-CHANGED",
            Severity.WARN,
            "an operation kept its method and path and renamed its operationId",
            "keep the old operationId and change the summary instead, or ship the "
            "rename as a major version of the generated SDK. Nothing about the "
            "request or the response moved, so no wire-level rule reports it and "
            "`diff` shows no change at all -- while every generated client's call "
            "site for the old name stops compiling",
            _BY,
            _FAMILY,
        ),
        _spec(
            "SDK-OPERATION-ID-REMOVED",
            Severity.WARN,
            "an operation dropped its operationId",
            "restore it. Generators fall back to a name derived from the method and "
            "path, so the method is not removed -- it is renamed to something the "
            "contract no longer states",
            _BY,
            _FAMILY,
        ),
        _spec(
            "SDK-OPERATION-ID-ADDED",
            Severity.INFO,
            "an operation gained an operationId it did not have",
            "nothing, if this is a deliberate move to declared operationIds. Clients "
            "generated before it used a name derived from the method and path, and "
            "that name is replaced, so it belongs in a major SDK version",
            _BY,
            _FAMILY,
        ),
        _spec(
            "SDK-TAG-NAMESPACE-CHANGED",
            Severity.WARN,
            "an operation's first tag changed",
            "add the new tag alongside the old one rather than replacing it. Where a "
            "generator groups operations into a class per tag, this moves the method "
            "to a different client object",
            _BY,
            _FAMILY,
        ),
        _spec(
            "SDK-MODEL-NAME-CHANGED",
            Severity.INFO,
            "a response schema's title changed while its shape did not",
            "keep the title and put the new wording in the description. Where model "
            "class names come from the title, the shape is identical and the class "
            "is renamed",
            _BY,
            _FAMILY,
        ),
        _spec(
            "SDK-ENUM-VALUE-ADDED",
            Severity.WARN,
            "a response enum gained a value",
            "roll it out behind a version, or stop declaring the field as a closed "
            "enum. Adding a value a client may receive is safe on the wire and "
            "unsafe in a generated closed type: a deserialization failure, or a "
            "match that is no longer exhaustive",
            _BY,
            _FAMILY,
        ),
        _spec(
            "SDK-PARAMETER-ORDER-CHANGED",
            Severity.WARN,
            "the required parameters of an operation were reordered",
            "restore the declaration order -- nothing about the request depends on "
            "it. Where a generator emits required parameters positionally, existing "
            "call sites keep compiling and start passing the arguments the other way "
            "round, which is the one finding in this family that is silent at "
            "build time",
            _BY,
            _FAMILY,
        ),
    ]
)

__all__ = ["SDK_CATALOG"]
