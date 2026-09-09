"""Canonicalization: equal contracts must compare equal.

The differ compares `allOf` branches positionally -- it zips the two lists, and
only when their lengths match. So a schema written as `allOf: [Base, {extra}]`
and the same schema written inline were completely different documents to it,
reordering branches renumbered every nested comparison, and two `allOf` lists
of different lengths were skipped *silently*, hiding every change inside the
branches that remained.

That last one is the reason this is not cosmetic. A reviewer reading a clean
diff would have concluded nothing changed.

The other half of these tests is what canonicalization refuses to do. Merging
is only safe where nothing has to be decided; branches that disagree are left
composed and reported, because turning an unsatisfiable contract into a
plausible-looking one is worse than reporting noise.
"""

from __future__ import annotations

from typing import Any

import pytest

from apiverity.core.canonical import canonicalize_schema, canonicalize_service
from apiverity.core.model import (
    Operation,
    OperationKind,
    Protocol,
    RequestBody,
    SchemaNode,
    Service,
)
from apiverity.diff.engine import diff_services


def _canon(schema: SchemaNode) -> tuple[SchemaNode, list[Any]]:
    findings: list[Any] = []
    return canonicalize_schema(schema, findings, "x"), findings


def _service(schema: SchemaNode, *, title: str = "svc") -> Service:
    return Service(
        title=title,
        version="1.0.0",
        protocol=Protocol.OPENAPI,
        operations=[
            Operation(
                kind=OperationKind.HTTP,
                method="POST",
                path="/things",
                request_body=RequestBody(required=True, content={"application/json": schema}),
            )
        ],
    )


# ------------------------------------------------------------ the main point


def test_an_allof_composition_equals_its_inline_form() -> None:
    """Refactoring a spec without changing its meaning must not read as a rewrite."""
    composed = SchemaNode(
        type="object",
        all_of=[
            SchemaNode(
                type="object", required=["id"], properties={"id": SchemaNode(type="string")}
            ),
            SchemaNode(
                type="object", required=["name"], properties={"name": SchemaNode(type="string")}
            ),
        ],
    )
    inline = SchemaNode(
        type="object",
        required=["name", "id"],
        properties={"id": SchemaNode(type="string"), "name": SchemaNode(type="string")},
    )
    assert diff_services(_service(composed), _service(inline)) == []


def test_reordering_allof_branches_changes_nothing() -> None:
    """`allOf` is a conjunction; order carries no meaning."""
    a = SchemaNode(type="object", properties={"a": SchemaNode(type="string")})
    b = SchemaNode(type="object", properties={"b": SchemaNode(type="integer")})
    first = SchemaNode(type="object", all_of=[a, b])
    second = SchemaNode(type="object", all_of=[b, a])
    assert diff_services(_service(first), _service(second)) == []


def test_a_change_inside_an_allof_of_a_different_length_is_no_longer_hidden() -> None:
    """The dangerous one.

    Positional zipping skipped mismatched lengths entirely, so adding a branch
    concealed every change inside the branches that remained. A reviewer read a
    clean diff and concluded nothing had changed.
    """
    old = SchemaNode(
        type="object",
        all_of=[
            SchemaNode(
                type="object", required=["id"], properties={"id": SchemaNode(type="string")}
            ),
        ],
    )
    new = SchemaNode(
        type="object",
        all_of=[
            # `id` quietly became an integer...
            SchemaNode(
                type="object", required=["id"], properties={"id": SchemaNode(type="integer")}
            ),
            # ...while a second branch was added, which used to hide it.
            SchemaNode(type="object", properties={"extra": SchemaNode(type="string")}),
        ],
    )
    changes = diff_services(_service(old), _service(new))
    described = " ".join(c.description for c in changes)
    assert "id" in described, f"the type change is still hidden: {described}"


def test_property_order_does_not_produce_changes() -> None:
    left = SchemaNode(
        type="object",
        properties={"z": SchemaNode(type="string"), "a": SchemaNode(type="string")},
    )
    right = SchemaNode(
        type="object",
        properties={"a": SchemaNode(type="string"), "z": SchemaNode(type="string")},
    )
    assert diff_services(_service(left), _service(right)) == []


def test_enum_order_and_duplicates_do_not_produce_changes() -> None:
    """An enum is a set written as a list."""
    left = SchemaNode(type="string", enum=["b", "a", "b"])
    right = SchemaNode(type="string", enum=["a", "b"])
    assert diff_services(_service(left), _service(right)) == []


def test_required_order_does_not_produce_changes() -> None:
    left = SchemaNode(type="object", required=["b", "a"])
    right = SchemaNode(type="object", required=["a", "b"])
    assert diff_services(_service(left), _service(right)) == []


# ------------------------------------------------------- conjunction rules


def test_constraints_merge_to_the_tightest_value() -> None:
    """`allOf` means a value must satisfy every branch."""
    node, _ = _canon(
        SchemaNode(
            type="integer",
            all_of=[
                SchemaNode(type="integer", minimum=1, maximum=100),
                SchemaNode(type="integer", minimum=10, maximum=50),
            ],
        )
    )
    assert node.minimum == 10  # the largest minimum
    assert node.maximum == 50  # the smallest maximum


def test_enums_intersect_rather_than_union() -> None:
    """A value must be in both branches, so the effective set is the overlap."""
    node, _ = _canon(
        SchemaNode(
            type="string",
            all_of=[
                SchemaNode(type="string", enum=["a", "b", "c"]),
                SchemaNode(type="string", enum=["b", "c", "d"]),
            ],
        )
    )
    assert node.enum == ["b", "c"]


def test_required_unions_across_branches() -> None:
    node, _ = _canon(
        SchemaNode(
            type="object",
            all_of=[
                SchemaNode(type="object", required=["a"]),
                SchemaNode(type="object", required=["b"]),
            ],
        )
    )
    assert node.required == ["a", "b"]


# ------------------------------------------------- what it refuses to merge


def test_branches_that_disagree_about_type_are_left_composed_and_reported() -> None:
    """An unsatisfiable contract must not be turned into a plausible one."""
    node, findings = _canon(
        SchemaNode(
            all_of=[SchemaNode(type="string"), SchemaNode(type="integer")],
        )
    )
    assert node.all_of is not None, "a conflicting composition was silently merged"
    assert "SPEC-ALLOF-CONFLICT" in {f.rule_id for f in findings}


def test_a_conflicting_property_type_is_reported() -> None:
    node, findings = _canon(
        SchemaNode(
            type="object",
            all_of=[
                SchemaNode(type="object", properties={"x": SchemaNode(type="string")}),
                SchemaNode(type="object", properties={"x": SchemaNode(type="integer")}),
            ],
        )
    )
    assert node.all_of is not None
    assert "SPEC-ALLOF-CONFLICT" in {f.rule_id for f in findings}


@pytest.mark.parametrize("attr", ["one_of", "any_of"])
def test_disjunctions_are_never_flattened(attr: str) -> None:
    """`oneOf` and `anyOf` mean "any of these"; merging them changes the contract."""
    schema = SchemaNode(**{attr: [SchemaNode(type="string"), SchemaNode(type="integer")]})
    node, _ = _canon(schema)
    variants = getattr(node, attr)
    assert variants is not None and len(variants) == 2


# ------------------------------------------------------------- boundaries


def test_a_real_change_still_reports() -> None:
    """The floor: canonicalization must not silence genuine differences."""
    old = SchemaNode(type="object", properties={"a": SchemaNode(type="string")})
    new = SchemaNode(type="object", properties={"a": SchemaNode(type="integer")})
    assert diff_services(_service(old), _service(new)) != []


def test_canonicalization_does_not_mutate_the_input() -> None:
    """A caller holding the parsed contract for provenance keeps what it parsed."""
    original = _service(
        SchemaNode(type="object", all_of=[SchemaNode(type="object", required=["id"])])
    )
    before = original.model_dump_json()
    canonicalize_service(original)
    assert original.model_dump_json() == before


def test_it_can_be_switched_off() -> None:
    """Sometimes the question really is about the document rather than the API."""
    composed = SchemaNode(
        type="object",
        all_of=[SchemaNode(type="object", properties={"a": SchemaNode(type="string")})],
    )
    inline = SchemaNode(type="object", properties={"a": SchemaNode(type="string")})
    assert diff_services(_service(composed), _service(inline)) == []
    assert diff_services(_service(composed), _service(inline), canonical=False) != []


def test_a_mixed_type_enum_is_not_refused() -> None:
    """Unusual, but legal; raising on it would reject a valid contract."""
    node, _ = _canon(SchemaNode(enum=[1, "a", True]))
    assert node.enum is not None and len(node.enum) == 3
