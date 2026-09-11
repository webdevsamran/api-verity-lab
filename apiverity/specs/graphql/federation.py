"""Subgraph changes, judged against what they do to the composed graph.

A GraphQL SDL diff compares two documents. In a federated graph that is the
wrong unit: a subgraph is one contributor to a schema clients actually query,
and the interesting changes are the ones that are invisible in the subgraph and
decisive in the supergraph.

The clearest is `@inaccessible`. Add it to a field and the field is still
there, in the same subgraph, with the same type — and it is gone from the
supergraph. A plain SDL diff reports no removal. Every client loses the field.

## What this is not

**A composition engine.** Composing a supergraph is what `rover` and
`@apollo/composition` do, they do it properly, and a second implementation
whose output looked like theirs and was computed differently is exactly what
this project refuses to build for Spectral's rules.

So this checks the *preconditions*: the conditions under which composition
fails or silently changes what clients see. `apiverity federation --subgraph a
--subgraph b` reports those. It does not produce a supergraph, does not claim
composition succeeds, and says so in its own output.

The distinction matters because the alternative is a tool that reports "no
findings" and is read as "this composes".

## Federation v2 directives read here

`@key`, `@shareable`, `@external`, `@requires`, `@provides`, `@override`,
`@inaccessible`, `@tag`. Read from the parsed AST, so a subgraph that does not
declare them in an `@link` is still understood — the directives are what the
document writes, and requiring the import to read them would miss every
subgraph that forgot it, which is the population most likely to have a problem.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from apiverity.core.model import Finding, Severity

#: The v2 directives this reads. Anything else on a field is left alone: a
#: custom directive is somebody's own, and objecting to it would be objecting
#: to the parts of GraphQL this does not govern.
FEDERATION_DIRECTIVES = (
    "key",
    "shareable",
    "external",
    "requires",
    "provides",
    "override",
    "inaccessible",
    "tag",
)


@dataclass(frozen=True)
class Directive:
    name: str
    #: Argument name -> literal value, for the string arguments that matter
    #: (`fields`, `from`). Non-literal arguments are recorded as None.
    args: tuple[tuple[str, str | None], ...] = ()

    def arg(self, name: str) -> str | None:
        for key, value in self.args:
            if key == name:
                return value
        return None


@dataclass
class TypeInfo:
    name: str
    kind: str
    directives: list[Directive] = field(default_factory=list)
    #: field name -> its directives.
    fields: dict[str, list[Directive]] = field(default_factory=dict)
    #: field name -> its type, as written.
    field_types: dict[str, str] = field(default_factory=dict)
    #: True for `extend type X`, which claims nothing about ownership on its own.
    extension: bool = False

    def has(self, name: str) -> bool:
        return any(d.name == name for d in self.directives)

    def key_selections(self) -> list[str]:
        """The `fields:` selection of every `@key` on this type.

        Not `keys()`. A method of that name on something which is not a mapping
        reads as `dict.keys` to a linter and to the next person, and both are
        wrong about what it returns.
        """
        return [d.arg("fields") or "" for d in self.directives if d.name == "key"]


@dataclass
class Subgraph:
    """One subgraph's federation surface."""

    name: str
    types: dict[str, TypeInfo] = field(default_factory=dict)

    def field_directives(self, type_name: str, field_name: str) -> list[Directive]:
        info = self.types.get(type_name)
        return list(info.fields.get(field_name, [])) if info else []

    def has_field_directive(self, type_name: str, field_name: str, directive: str) -> bool:
        return any(d.name == directive for d in self.field_directives(type_name, field_name))


def _directives(node: Any) -> list[Directive]:
    out: list[Directive] = []
    for directive in getattr(node, "directives", []) or []:
        name = directive.name.value
        if name not in FEDERATION_DIRECTIVES:
            continue
        args: list[tuple[str, str | None]] = []
        for argument in directive.arguments or []:
            args.append((argument.name.value, getattr(argument.value, "value", None)))
        out.append(Directive(name=name, args=tuple(args)))
    return out


def _type_name(node: Any) -> str:
    """`[Review!]!` -> the text as written, so a change in nullability shows."""
    kind = getattr(node, "kind", "")
    if kind == "non_null_type":
        return f"{_type_name(node.type)}!"
    if kind == "list_type":
        return f"[{_type_name(node.type)}]"
    return str(getattr(getattr(node, "name", None), "value", "?"))


def read(sdl: str, name: str) -> Subgraph:
    """Parse one subgraph's federation surface out of its SDL."""
    from graphql import parse

    subgraph = Subgraph(name=name)
    document = parse(sdl)
    for definition in document.definitions:
        kind = str(getattr(definition, "kind", ""))
        if "object_type" not in kind and "interface_type" not in kind:
            continue
        named = getattr(definition, "name", None)
        if named is None:
            continue
        type_name = str(named.value)
        info = subgraph.types.setdefault(
            type_name,
            TypeInfo(name=type_name, kind="interface" if "interface" in kind else "object"),
        )
        info.extension = info.extension or kind.endswith("extension")
        info.directives.extend(_directives(definition))
        for member in getattr(definition, "fields", None) or []:
            field_name = member.name.value
            info.fields[field_name] = _directives(member)
            info.field_types[field_name] = _type_name(member.type)
    return subgraph


# ------------------------------------------------------------------ one pair


def diff_subgraph(before: Subgraph, after: Subgraph) -> list[Finding]:
    """What changed in one subgraph that the supergraph will feel."""
    out: list[Finding] = []

    for type_name, old in before.types.items():
        new = after.types.get(type_name)
        if new is None:
            continue  # a removed type is already the loudest SDL finding there is

        old_keys, new_keys = set(old.key_selections()), set(new.key_selections())
        if old_keys and not new_keys:
            out.append(
                Finding(
                    rule_id="FED-KEY-REMOVED",
                    severity=Severity.ERROR,
                    message=(
                        f"type '{type_name}' lost its @key. It is no longer an entity, so no "
                        "other subgraph can resolve a reference to it"
                    ),
                    operation_key=type_name,
                    hint="restore the @key, or move the fields that depend on it in the same change",
                )
            )
        elif old_keys - new_keys:
            out.append(
                Finding(
                    rule_id="FED-KEY-CHANGED",
                    severity=Severity.ERROR,
                    message=(
                        f"type '{type_name}' dropped the @key {sorted(old_keys - new_keys)}. A "
                        "subgraph resolving references by that key can no longer do so"
                    ),
                    operation_key=type_name,
                    hint="keep the old key alongside the new one until every subgraph has moved",
                )
            )

        for field_name, old_directives in old.fields.items():
            if field_name not in new.fields:
                continue
            names = {d.name for d in old_directives}
            new_names = {d.name for d in new.fields[field_name]}

            if "inaccessible" in new_names - names:
                # The flagship case. The field is still here, same type, same
                # everything -- and it is gone from the graph clients query.
                out.append(
                    Finding(
                        rule_id="FED-INACCESSIBLE-ADDED",
                        severity=Severity.ERROR,
                        message=(
                            f"'{type_name}.{field_name}' became @inaccessible. The field is "
                            "unchanged in this subgraph and removed from the supergraph, so an "
                            "SDL diff reports nothing and every client loses it"
                        ),
                        operation_key=f"{type_name}.{field_name}",
                        hint="deprecate it in the supergraph first, then make it inaccessible",
                    )
                )
            if "shareable" in names - new_names:
                out.append(
                    Finding(
                        rule_id="FED-SHAREABLE-REMOVED",
                        severity=Severity.ERROR,
                        message=(
                            f"'{type_name}.{field_name}' is no longer @shareable. If another "
                            "subgraph resolves it, composition now fails"
                        ),
                        operation_key=f"{type_name}.{field_name}",
                        hint="remove the field from the other subgraph in the same release, or keep @shareable",
                    )
                )
            if "external" in new_names - names:
                out.append(
                    Finding(
                        rule_id="FED-EXTERNAL-ADDED",
                        severity=Severity.WARN,
                        message=(
                            f"'{type_name}.{field_name}' became @external: this subgraph now "
                            "declares the field without owning it, so something else must resolve it"
                        ),
                        operation_key=f"{type_name}.{field_name}",
                    )
                )

            old_override = next((d for d in old_directives if d.name == "override"), None)
            new_override = next((d for d in new.fields[field_name] if d.name == "override"), None)
            if (old_override is None) != (new_override is None) or (
                old_override
                and new_override
                and old_override.arg("from") != new_override.arg("from")
            ):
                moved = (new_override.arg("from") if new_override else None) or (
                    old_override.arg("from") if old_override else None
                )
                out.append(
                    Finding(
                        rule_id="FED-OWNERSHIP-MOVED",
                        severity=Severity.WARN,
                        message=(
                            f"'{type_name}.{field_name}' changed its @override, so which subgraph "
                            f"resolves it has moved (from '{moved}')"
                        ),
                        operation_key=f"{type_name}.{field_name}",
                        hint="both subgraphs must be deployed together; the order decides whether there is a gap",
                    )
                )
    return out


# ------------------------------------------------------------- a whole set


def check_composition(subgraphs: list[Subgraph]) -> list[Finding]:
    """Conditions under which composing these would fail or surprise.

    Not a composition. See the module docstring: this reports preconditions,
    and the caller is told in its own output that a clean result is not a
    claim that composition succeeds.
    """
    out: list[Finding] = []

    owners: dict[tuple[str, str], list[str]] = {}
    for subgraph in subgraphs:
        for type_name, info in subgraph.types.items():
            for field_name, directives in info.fields.items():
                names = {d.name for d in directives}
                if "external" in names:
                    # Declared, not owned. It does not count as a definition.
                    continue
                owners.setdefault((type_name, field_name), []).append(subgraph.name)

    for (type_name, field_name), providers in sorted(owners.items()):
        if len(providers) < 2:
            continue
        if field_name in _key_fields(subgraphs, type_name):
            # A key field is implicitly shareable in Federation v2, and every
            # subgraph that keys the entity is *required* to declare it. The
            # first version of this rule reported `Product.id` on every
            # correctly federated graph there is, which is how a rule gets
            # switched off before anybody reads its second finding.
            continue
        unshared = [
            s.name
            for s in subgraphs
            if s.name in providers and not s.has_field_directive(type_name, field_name, "shareable")
        ]
        if unshared:
            out.append(
                Finding(
                    rule_id="FED-UNSHAREABLE-DUPLICATE",
                    severity=Severity.ERROR,
                    message=(
                        f"'{type_name}.{field_name}' is resolved by {sorted(providers)} and is not "
                        f"@shareable in {sorted(unshared)}. Composition rejects that"
                    ),
                    operation_key=f"{type_name}.{field_name}",
                    hint="mark it @shareable in every subgraph that resolves it, or remove it from all but one",
                )
            )

    # Types shared across subgraphs must agree they are entities.
    by_type: dict[str, list[Subgraph]] = {}
    for subgraph in subgraphs:
        for type_name in subgraph.types:
            by_type.setdefault(type_name, []).append(subgraph)
    for type_name, holders in sorted(by_type.items()):
        if len(holders) < 2 or type_name in ("Query", "Mutation", "Subscription"):
            continue
        keyed = {s.name for s in holders if s.types[type_name].key_selections()}
        if keyed and len(keyed) != len(holders):
            missing = sorted({s.name for s in holders} - keyed)
            out.append(
                Finding(
                    rule_id="FED-KEY-INCONSISTENT",
                    severity=Severity.ERROR,
                    message=(
                        f"type '{type_name}' is an entity in {sorted(keyed)} and has no @key in "
                        f"{missing}. A subgraph cannot contribute fields to an entity it does not key"
                    ),
                    operation_key=type_name,
                    hint=f"add the same @key to {missing}",
                )
            )

    # An `@external` field nothing else defines is a reference to nowhere.
    for subgraph in subgraphs:
        for type_name, info in subgraph.types.items():
            for field_name, directives in info.fields.items():
                if not any(d.name == "external" for d in directives):
                    continue
                if (type_name, field_name) in owners:
                    continue
                out.append(
                    Finding(
                        rule_id="FED-EXTERNAL-DANGLING",
                        severity=Severity.ERROR,
                        message=(
                            f"'{subgraph.name}' declares '{type_name}.{field_name}' @external and "
                            "no subgraph here resolves it"
                        ),
                        operation_key=f"{type_name}.{field_name}",
                        hint=(
                            "a subgraph missing from this run may own it -- pass every subgraph, "
                            "or remove the @external declaration"
                        ),
                    )
                )

    # `@requires` and `@provides` name fields; a name that resolves to nothing
    # here is worth saying, with the same caveat about a missing subgraph.
    for subgraph in subgraphs:
        for type_name, info in subgraph.types.items():
            for field_name, directives in info.fields.items():
                for directive in directives:
                    if directive.name not in ("requires", "provides"):
                        continue
                    selection = directive.arg("fields") or ""
                    for named in _field_names(selection):
                        target = type_name if directive.name == "requires" else None
                        if target and (target, named) not in owners:
                            out.append(
                                Finding(
                                    rule_id="FED-REQUIRES-UNKNOWN-FIELD",
                                    severity=Severity.WARN,
                                    message=(
                                        f"'{type_name}.{field_name}' @requires '{named}', which no "
                                        "subgraph in this run defines on that type"
                                    ),
                                    operation_key=f"{type_name}.{field_name}",
                                    hint="pass every subgraph, or correct the field selection",
                                )
                            )
    return out


def _key_fields(subgraphs: list[Subgraph], type_name: str) -> set[str]:
    """Every field named in any `@key` on this type, across the set.

    Implicitly shareable, and required in every subgraph that keys the entity
    -- so they are not duplicates, they are the mechanism.
    """
    out: set[str] = set()
    for subgraph in subgraphs:
        info = subgraph.types.get(type_name)
        if info is None:
            continue
        for selection in info.key_selections():
            out.update(_field_names(selection))
    return out


def _field_names(selection: str) -> list[str]:
    """The top-level field names in a `fields:` selection.

    Deliberately shallow. `@requires(fields: "price { amount }")` names `price`
    on this type and `amount` on another, and following the second would mean
    resolving types this is explicitly not doing.
    """
    out: list[str] = []
    depth = 0
    for token in selection.replace("{", " { ").replace("}", " } ").split():
        if token == "{":
            depth += 1
        elif token == "}":
            depth = max(0, depth - 1)
        elif depth == 0:
            out.append(token)
    return out


__all__ = [
    "FEDERATION_DIRECTIVES",
    "Directive",
    "Subgraph",
    "TypeInfo",
    "check_composition",
    "diff_subgraph",
    "read",
]
