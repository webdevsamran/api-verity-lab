"""Canonicalize a contract so that equal contracts compare equal.

The diff engine compares `allOf` branches *positionally*: it zips the two lists
and only when their lengths match. Three consequences, all of them noise that
lands in someone's pull request:

* a schema written as `allOf: [Base, {extra}]` and the same schema written
  inline are completely different documents to the differ, so refactoring a
  spec without changing its meaning reports as a rewrite;
* reordering `allOf` branches -- which changes nothing, the composition is a
  conjunction -- renumbers every nested comparison;
* two `allOf` lists of *different* lengths are skipped entirely and silently,
  so adding a branch hides every change inside the ones that remain.

This module runs between the adapters and the engines. Every format compiles
into `Service` first, so canonicalizing `Service` covers OpenAPI, Swagger,
AsyncAPI, GraphQL, gRPC and MCP at once.

What it will not do
-------------------
It collapses only what it can collapse *without deciding anything*. Two
branches that disagree about `type`, or about a shared property's type, are
left alone and reported: an `allOf` of `{type: string}` and `{type: integer}`
is unsatisfiable, and silently picking one would turn a broken contract into a
plausible-looking one. `oneOf` and `anyOf` are never merged at all -- they are
disjunctions, and flattening a disjunction changes what the document means.

Constraints merge to the *tightest* value, because `allOf` is a conjunction: a
value must satisfy every branch, so the effective minimum is the largest
minimum and the effective maximum is the smallest.
"""

from __future__ import annotations

from typing import Any

from apiverity.core.model import (
    Finding,
    Operation,
    Response,
    SchemaNode,
    Service,
    Severity,
)

#: Constraint attributes where a conjunction takes the larger value.
_TIGHTEN_MAX = (
    "minimum",
    "exclusive_minimum",
    "min_length",
    "min_items",
    "min_properties",
)

#: Constraint attributes where a conjunction takes the smaller value.
_TIGHTEN_MIN = (
    "maximum",
    "exclusive_maximum",
    "max_length",
    "max_items",
    "max_properties",
)


def canonicalize_service(service: Service) -> tuple[Service, list[Finding]]:
    """Return a canonical copy of `service`, plus anything it could not resolve.

    Copies rather than mutating: a caller holding the parsed contract for
    provenance should not find it silently rewritten underneath.
    """
    findings: list[Finding] = []
    canonical = service.model_copy(deep=True)
    canonical.operations = [_canonical_operation(op, findings) for op in canonical.operations]
    return canonical, findings


def _canonical_operation(op: Operation, findings: list[Finding]) -> Operation:
    if op.request_body is not None:
        op.request_body.content = {
            media: canonicalize_schema(schema, findings, f"{op.key} request {media}")
            for media, schema in sorted(op.request_body.content.items())
        }
    op.responses = [_canonical_response(r, op.key, findings) for r in op.responses]
    for parameter in op.parameters:
        if parameter.schema_node is not None:
            parameter.schema_node = canonicalize_schema(
                parameter.schema_node, findings, f"{op.key} parameter {parameter.name}"
            )
    return op


def _canonical_response(response: Response, key: str, findings: list[Finding]) -> Response:
    response.content = {
        media: canonicalize_schema(schema, findings, f"{key} response {response.status} {media}")
        for media, schema in sorted(response.content.items())
    }
    return response


def canonicalize_schema(schema: SchemaNode, findings: list[Finding], where: str) -> SchemaNode:
    """Collapse `allOf`, normalize enums, and order everything deterministically."""
    node = schema.model_copy(deep=True)

    node.properties = {
        name: canonicalize_schema(child, findings, f"{where}.{name}")
        for name, child in sorted(node.properties.items())
    }
    if node.items is not None:
        node.items = canonicalize_schema(node.items, findings, f"{where}[]")
    if isinstance(node.additional_properties, SchemaNode):
        node.additional_properties = canonicalize_schema(
            node.additional_properties, findings, f"{where}.*"
        )
    for attr in ("one_of", "any_of"):
        variants = getattr(node, attr)
        if variants:
            setattr(
                node,
                attr,
                [
                    canonicalize_schema(v, findings, f"{where}/{attr}[{i}]")
                    for i, v in enumerate(variants)
                ],
            )

    node = _canonicalize_2020_12(node, findings, where)

    if node.all_of:
        node = _collapse_all_of(node, findings, where)

    # Enums are sets written as lists. Deduplicated and ordered so that two
    # documents listing the same values differently stop diffing.
    if node.enum is not None:
        node.enum = _stable_unique(node.enum)
    node.required = sorted(set(node.required))
    return node


def _canonicalize_2020_12(node: SchemaNode, findings: list[Finding], where: str) -> SchemaNode:
    """Recurse into the 2020-12 sub-schemas, and order what is unordered.

    Without this, canonicalization is partial: an `allOf` inside a
    `patternProperties` branch stays uncollapsed and an enum inside a
    `prefixItems` position stays unsorted, so two documents that mean the same
    thing keep diffing -- in exactly the places nobody looks.
    """
    if node.prefix_items:
        node.prefix_items = [
            canonicalize_schema(item, findings, f"{where}[{index}]")
            for index, item in enumerate(node.prefix_items)
        ]
    if node.contains is not None:
        node.contains = canonicalize_schema(node.contains, findings, f"{where}/contains")
    if node.property_names is not None:
        node.property_names = canonicalize_schema(
            node.property_names, findings, f"{where}/propertyNames"
        )
    if node.pattern_properties:
        node.pattern_properties = {
            expression: canonicalize_schema(child, findings, f"{where}/~{expression}")
            for expression, child in sorted(node.pattern_properties.items())
        }
    if node.dependent_schemas:
        node.dependent_schemas = {
            name: canonicalize_schema(child, findings, f"{where}?{name}")
            for name, child in sorted(node.dependent_schemas.items())
        }
    if node.dependent_required:
        # A dependency list is a set written as a list, same as `required`.
        node.dependent_required = {
            name: sorted(set(names)) for name, names in sorted(node.dependent_required.items())
        }
    for attr, keyword in (
        ("if_schema", "if"),
        ("then_schema", "then"),
        ("else_schema", "else"),
    ):
        branch = getattr(node, attr)
        if branch is not None:
            setattr(node, attr, canonicalize_schema(branch, findings, f"{where}/{keyword}"))
    return node


def _collapse_all_of(node: SchemaNode, findings: list[Finding], where: str) -> SchemaNode:
    """Merge `allOf` branches into the parent where it is unambiguous."""
    branches = [canonicalize_schema(b, findings, f"{where}/allOf") for b in node.all_of or []]
    merged = node.model_copy(deep=True)
    merged.all_of = None

    conflicts: list[str] = []
    for branch in branches:
        _merge_into(merged, branch, where, conflicts)

    if conflicts:
        # Leave the composition intact and say why. A contract whose branches
        # disagree is broken, and quietly picking a winner would present it as
        # working.
        findings.append(
            Finding(
                rule_id="SPEC-ALLOF-CONFLICT",
                severity=Severity.WARN,
                message=(
                    f"allOf at {where} was not collapsed because its branches disagree: "
                    f"{'; '.join(sorted(set(conflicts)))}. The composition is compared "
                    "branch by branch instead, which is noisier but does not invent a merge"
                ),
            )
        )
        node.all_of = branches
        return node
    return merged


def _merge_into(target: SchemaNode, branch: SchemaNode, where: str, conflicts: list[str]) -> None:
    if branch.type is not None:
        if target.type is None:
            target.type = branch.type
        elif target.type != branch.type:
            conflicts.append(f"type {target.type!r} vs {branch.type!r}")
            return

    for name, child in branch.properties.items():
        existing = target.properties.get(name)
        if existing is None:
            target.properties[name] = child
        elif existing.type and child.type and existing.type != child.type:
            conflicts.append(f"property {name!r} typed {existing.type!r} and {child.type!r}")
        else:
            _merge_into(existing, child, f"{where}.{name}", conflicts)

    target.required = sorted(set(target.required) | set(branch.required))

    if branch.enum is not None:
        # A conjunction of enums is their intersection: a value must be in both.
        target.enum = (
            _stable_unique([v for v in target.enum if v in branch.enum])
            if target.enum is not None
            else _stable_unique(branch.enum)
        )

    for attr in _TIGHTEN_MAX:
        _tighten(target, branch, attr, larger=True)
    for attr in _TIGHTEN_MIN:
        _tighten(target, branch, attr, larger=False)

    for attr in ("format", "pattern", "const", "default", "example", "title", "description"):
        if getattr(target, attr) is None and getattr(branch, attr) is not None:
            setattr(target, attr, getattr(branch, attr))

    if branch.items is not None and target.items is None:
        target.items = branch.items

    # A 2020-12 keyword on a branch is a rule the conjunction has to keep.
    # Merging them properly means intersecting conditionals, which has no
    # unambiguous answer, so a branch carrying one is reported as a conflict
    # and the composition is left standing. Dropping it would be the one
    # outcome worse than a noisy diff: a constraint silently deleted.
    for attr, keyword in (
        ("dependent_required", "dependentRequired"),
        ("dependent_schemas", "dependentSchemas"),
        ("pattern_properties", "patternProperties"),
        ("prefix_items", "prefixItems"),
        ("if_schema", "if"),
        ("contains", "contains"),
        ("property_names", "propertyNames"),
    ):
        if getattr(branch, attr):
            conflicts.append(f"a branch carries `{keyword}`, which cannot be merged unambiguously")
    if branch.nullable:
        # Only a branch that *permits* null widens the parent; conjunction
        # cannot make a non-nullable schema nullable, but every branch agreeing
        # it is nullable does.
        target.nullable = target.nullable or all(b.nullable for b in [branch])


def _tighten(target: SchemaNode, branch: SchemaNode, attr: str, *, larger: bool) -> None:
    theirs = getattr(branch, attr)
    if theirs is None:
        return
    ours = getattr(target, attr)
    if ours is None:
        setattr(target, attr, theirs)
        return
    setattr(target, attr, max(ours, theirs) if larger else min(ours, theirs))


def _stable_unique(values: list[Any]) -> list[Any]:
    """Deduplicate, then order deterministically.

    Deduplication keys on `(type name, value)` rather than on the value alone,
    because Python considers `True == 1` and `False == 0`. A plain `in` check
    drops one of them, and an enum declaring both `1` and `true` -- which JSON
    Schema treats as different values -- would silently lose a member. Narrowing
    an enum is a breaking change; doing it by accident inside the tool that
    detects breaking changes is worse.

    Sorted where the values are mutually comparable, insertion-ordered where
    they are not: a mixed-type enum is unusual but legal, and refusing one would
    reject a contract the specification allows.
    """
    seen: list[Any] = []
    keys: set[tuple[str, str]] = set()
    for value in values:
        key = (type(value).__name__, repr(value))
        if key not in keys:
            keys.add(key)
            seen.append(value)
    try:
        return sorted(seen, key=lambda v: (type(v).__name__, v))
    except TypeError:
        return seen


__all__ = ["canonicalize_schema", "canonicalize_service"]
