"""The federation rules, for `explain` and the generated catalogue.

Every one is about the supergraph rather than the subgraph, which is the whole
reason they are not `BRK-*`: an SDL diff of the subgraph reports nothing for
most of them.
"""

from __future__ import annotations

from apiverity.core.model import Severity
from apiverity.rules.check_catalog import CheckRuleSpec
from apiverity.rules.check_catalog import spec as _spec

_FAMILY = "GraphQL federation"
_BY = "federation"

FEDERATION_CATALOG: dict[str, CheckRuleSpec] = dict(
    [
        _spec(
            "FED-KEY-REMOVED",
            Severity.ERROR,
            "a type stopped being an entity",
            "restore the @key, or move every field that depends on it in the same change. "
            "Without a key no other subgraph can resolve a reference to the type, so "
            "every cross-subgraph join through it stops working",
            _BY,
            _FAMILY,
        ),
        _spec(
            "FED-KEY-CHANGED",
            Severity.ERROR,
            "a @key an entity used to declare is gone",
            "keep the old key alongside the new one until every subgraph has moved. A "
            "subgraph resolving references by the dropped key cannot do so any more, and "
            "it will not be the subgraph that changed",
            _BY,
            _FAMILY,
        ),
        _spec(
            "FED-INACCESSIBLE-ADDED",
            Severity.ERROR,
            "a field became @inaccessible, so it left the supergraph without leaving the subgraph",
            "deprecate it in the supergraph first, then make it inaccessible. This is the "
            "change an SDL diff cannot see: the field is unchanged in the document, same "
            "name and same type, and every client loses it",
            _BY,
            _FAMILY,
        ),
        _spec(
            "FED-SHAREABLE-REMOVED",
            Severity.ERROR,
            "a field is no longer @shareable",
            "remove the field from the other subgraph in the same release, or keep "
            "@shareable. If anything else resolves it, composition now rejects the graph",
            _BY,
            _FAMILY,
        ),
        _spec(
            "FED-EXTERNAL-ADDED",
            Severity.WARN,
            "a field became @external: declared here, owned elsewhere",
            "confirm another subgraph resolves it. @external says this subgraph names the "
            "field without providing it, which is correct for a key field and a mistake "
            "for anything the subgraph used to own",
            _BY,
            _FAMILY,
        ),
        _spec(
            "FED-OWNERSHIP-MOVED",
            Severity.WARN,
            "an @override changed which subgraph resolves a field",
            "deploy both subgraphs together. The order decides whether there is a window "
            "in which neither resolves it, and nothing in either subgraph's own SDL says "
            "the other one moved",
            _BY,
            _FAMILY,
        ),
        _spec(
            "FED-UNSHAREABLE-DUPLICATE",
            Severity.ERROR,
            "two subgraphs resolve one field and it is not @shareable in all of them",
            "mark it @shareable everywhere it is resolved, or remove it from all but one "
            "subgraph. Key fields are exempt: they are implicitly shareable and every "
            "subgraph keying the entity is required to declare them",
            _BY,
            _FAMILY,
        ),
        _spec(
            "FED-KEY-INCONSISTENT",
            Severity.ERROR,
            "a type is an entity in one subgraph and not in another",
            "add the same @key to the subgraphs that lack it. A subgraph cannot contribute "
            "fields to an entity it does not key",
            _BY,
            _FAMILY,
        ),
        _spec(
            "FED-EXTERNAL-DANGLING",
            Severity.ERROR,
            "an @external field no subgraph in this run resolves",
            "pass every subgraph, or remove the @external declaration. This one is worth "
            "reading twice: a subgraph missing from the run is the likelier cause, which "
            "is why the finding says so rather than asserting the field is unresolvable",
            _BY,
            _FAMILY,
        ),
        _spec(
            "FED-REQUIRES-UNKNOWN-FIELD",
            Severity.WARN,
            "a @requires names a field no subgraph in this run defines on that type",
            "pass every subgraph, or correct the selection. WARN rather than ERROR for the "
            "same reason as FED-EXTERNAL-DANGLING: an incomplete run and a broken "
            "selection look identical from here",
            _BY,
            _FAMILY,
        ),
    ]
)

__all__ = ["FEDERATION_CATALOG"]
