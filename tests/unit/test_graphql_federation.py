"""A subgraph change judged against the graph clients actually query.

The case this exists for is one line of SDL: add `@inaccessible` to a field and
the field is still there, same name, same type, same subgraph — and gone from
the supergraph. An SDL diff reports no removal. Every client loses it.
"""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
from typing import Any

import pytest

from apiverity.cli.commands.common import EXIT_FINDINGS, EXIT_OK, EXIT_USAGE
from apiverity.cli.main import main
from apiverity.rules.check_catalog import catalog
from apiverity.specs.graphql.federation import check_composition, diff_subgraph, read
from apiverity.specs.graphql.federation_catalog import FEDERATION_CATALOG

_ROOT = Path(__file__).resolve().parents[2]
_DIR = _ROOT / "fixtures/apis/federation"


def _sg(name: str) -> Any:
    return read((_DIR / f"{name}.graphql").read_text(encoding="utf-8"), name)


def _ids(findings: list[Any]) -> set[str]:
    return {f.rule_id for f in findings}


def _run(argv: list[str]) -> tuple[int, dict[str, Any], str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    text = out.getvalue()
    return code, (json.loads(text) if text.strip().startswith("{") else {}), err.getvalue()


# ------------------------------------------------------------- the point


def test_inaccessible_is_invisible_to_an_sdl_diff_and_removes_the_field() -> None:
    before, after = _sg("products"), _sg("products-v2")
    # The field is textually unchanged apart from the directive: same name,
    # same type, same subgraph.
    assert before.types["Product"].field_types["price"] == "Int"
    assert after.types["Product"].field_types["price"] == "Int"
    assert "FED-INACCESSIBLE-ADDED" in _ids(diff_subgraph(before, after))


def test_removing_shareable_is_reported() -> None:
    assert "FED-SHAREABLE-REMOVED" in _ids(diff_subgraph(_sg("products"), _sg("products-v2")))


def test_a_subgraph_compared_with_itself_reports_nothing() -> None:
    assert diff_subgraph(_sg("products"), _sg("products")) == []


def test_losing_a_key_stops_a_type_being_an_entity(tmp_path: Path) -> None:
    before = read('type Product @key(fields: "id") { id: ID! }', "a")
    after = read("type Product { id: ID! }", "a")
    assert _ids(diff_subgraph(before, after)) == {"FED-KEY-REMOVED"}


def test_dropping_one_of_several_keys_is_reported_separately() -> None:
    before = read(
        'type Product @key(fields: "id") @key(fields: "sku") { id: ID! sku: String! }', "a"
    )
    after = read('type Product @key(fields: "id") { id: ID! sku: String! }', "a")
    assert _ids(diff_subgraph(before, after)) == {"FED-KEY-CHANGED"}


def test_ownership_moving_between_subgraphs_is_reported() -> None:
    before = read('type Product @key(fields: "id") { id: ID! name: String }', "a")
    after = read(
        'type Product @key(fields: "id") { id: ID! name: String @override(from: "legacy") }', "a"
    )
    finding = next(f for f in diff_subgraph(before, after) if f.rule_id == "FED-OWNERSHIP-MOVED")
    assert "legacy" in finding.message


def test_a_field_becoming_external_is_reported() -> None:
    before = read('type Product @key(fields: "id") { id: ID! name: String }', "a")
    after = read('type Product @key(fields: "id") { id: ID! name: String @external }', "a")
    assert "FED-EXTERNAL-ADDED" in _ids(diff_subgraph(before, after))


def test_a_removed_type_is_left_to_the_sdl_diff() -> None:
    """Already the loudest finding there is; a second one adds noise."""
    before = read('type Product @key(fields: "id") { id: ID! }', "a")
    after = read("type Query { ok: Boolean }", "a")
    assert diff_subgraph(before, after) == []


# ------------------------------------------------------ composition checks


def test_a_correctly_federated_pair_is_clean() -> None:
    """The rule that had to be fixed: key fields are implicitly shareable.

    The first version reported `Product.id` on every correctly federated graph
    there is, which is how a rule gets switched off before anybody reads its
    second finding.
    """
    assert check_composition([_sg("products"), _sg("reviews")]) == []


def test_two_subgraphs_resolving_one_field_without_shareable_is_rejected() -> None:
    findings = check_composition([_sg("products-v2"), _sg("reviews")])
    assert _ids(findings) == {"FED-UNSHAREABLE-DUPLICATE"}
    assert "Product.name" in findings[0].message


def test_a_key_field_is_never_a_duplicate() -> None:
    a = read('type P @key(fields: "id") { id: ID! }', "a")
    b = read('type P @key(fields: "id") { id: ID! }', "b")
    assert check_composition([a, b]) == []


def test_a_compound_key_exempts_every_field_it_names() -> None:
    a = read('type P @key(fields: "id sku") { id: ID! sku: String! }', "a")
    b = read('type P @key(fields: "id sku") { id: ID! sku: String! }', "b")
    assert check_composition([a, b]) == []


def test_an_entity_in_one_subgraph_and_not_another_is_rejected() -> None:
    a = read('type P @key(fields: "id") { id: ID! }', "a")
    b = read("type P { id: ID! other: String }", "b")
    findings = check_composition([a, b])
    assert "FED-KEY-INCONSISTENT" in _ids(findings)


def test_a_root_type_shared_across_subgraphs_is_not_an_entity_problem() -> None:
    """Every subgraph has a Query, and none of them keys it."""
    a = read("type Query { a: String }", "a")
    b = read("type Query { b: String }", "b")
    assert "FED-KEY-INCONSISTENT" not in _ids(check_composition([a, b]))


def test_an_external_field_nobody_resolves_is_reported_with_the_caveat() -> None:
    """An incomplete run is the likelier cause, so the finding says so rather
    than asserting the field is unresolvable."""
    a = read('type P @key(fields: "id") { id: ID! price: Int @external }', "a")
    finding = next(f for f in check_composition([a, a]) if f.rule_id == "FED-EXTERNAL-DANGLING")
    assert "missing from this run" in (finding.hint or "")


def test_an_external_field_another_subgraph_owns_is_fine() -> None:
    a = read('type P @key(fields: "id") { id: ID! price: Int @external }', "a")
    b = read('type P @key(fields: "id") { id: ID! price: Int }', "b")
    assert "FED-EXTERNAL-DANGLING" not in _ids(check_composition([a, b]))


def test_external_does_not_count_as_resolving_a_field() -> None:
    """Two subgraphs declaring it @external and neither owning it is dangling,
    not a shareable duplicate."""
    a = read('type P @key(fields: "id") { id: ID! price: Int @external }', "a")
    b = read('type P @key(fields: "id") { id: ID! price: Int @external }', "b")
    assert _ids(check_composition([a, b])) == {"FED-EXTERNAL-DANGLING"}


def test_a_requires_naming_an_unknown_field_is_a_warning() -> None:
    a = read('type P @key(fields: "id") { id: ID! total: Int @requires(fields: "missing") }', "a")
    b = read('type P @key(fields: "id") { id: ID! }', "b")
    finding = next(
        f for f in check_composition([a, b]) if f.rule_id == "FED-REQUIRES-UNKNOWN-FIELD"
    )
    assert finding.severity.value == "WARN"


def test_a_nested_selection_only_names_its_top_level() -> None:
    """`price { amount }` names `price` here and `amount` on another type, and
    following the second would mean resolving types this does not do."""
    a = read(
        'type P @key(fields: "id") { id: ID! t: Int @requires(fields: "price { amount }") }', "a"
    )
    b = read('type P @key(fields: "id") { id: ID! price: Money } type Money { amount: Int }', "b")
    assert "FED-REQUIRES-UNKNOWN-FIELD" not in _ids(check_composition([a, b]))


def test_one_subgraph_alone_is_not_a_composition() -> None:
    assert check_composition([_sg("products")]) == []


# ------------------------------------------------------------ the catalogue


def test_every_rule_this_emits_can_be_explained() -> None:
    known = set(catalog())
    assert set(FEDERATION_CATALOG) <= known


def test_no_catalogued_rule_is_dead() -> None:
    """A published rule no input can produce is a defect this project has found
    four separate times."""
    fired = _ids(diff_subgraph(_sg("products"), _sg("products-v2")))
    fired |= _ids(check_composition([_sg("products-v2"), _sg("reviews")]))
    for extra in (
        diff_subgraph(
            read('type P @key(fields: "id") { id: ID! }', "a"), read("type P { id: ID! }", "a")
        ),
        diff_subgraph(
            read('type P @key(fields: "id") @key(fields: "s") { id: ID! s: String! }', "a"),
            read('type P @key(fields: "id") { id: ID! s: String! }', "a"),
        ),
        diff_subgraph(
            read('type P @key(fields: "id") { id: ID! n: String }', "a"),
            read('type P @key(fields: "id") { id: ID! n: String @external }', "a"),
        ),
        diff_subgraph(
            read('type P @key(fields: "id") { id: ID! n: String }', "a"),
            read('type P @key(fields: "id") { id: ID! n: String @override(from: "x") }', "a"),
        ),
        check_composition(
            [
                read('type P @key(fields: "id") { id: ID! }', "a"),
                read("type P { id: ID! o: String }", "b"),
            ]
        ),
        check_composition(
            [read('type P @key(fields: "id") { id: ID! x: Int @external }', "a")] * 2
        ),
        check_composition(
            [
                read('type P @key(fields: "id") { id: ID! t: Int @requires(fields: "gone") }', "a"),
                read('type P @key(fields: "id") { id: ID! }', "b"),
            ]
        ),
    ):
        fired |= _ids(extra)
    assert set(FEDERATION_CATALOG) - fired == set()


# ------------------------------------------------------------- the command


def test_the_command_reports_what_the_sdl_diff_cannot() -> None:
    code, payload, _ = _run(
        [
            "federation",
            "--subgraph",
            str(_DIR / "products-v2.graphql"),
            "--against",
            str(_DIR / "products.graphql"),
            "--json",
        ]
    )
    assert code == EXIT_FINDINGS
    assert "FED-INACCESSIBLE-ADDED" in {f["rule_id"] for f in payload["findings"]}


def test_the_output_says_it_is_not_a_composition() -> None:
    """A clean run read as "this composes" is the misreading that matters."""
    code, payload, _ = _run(
        [
            "federation",
            "--subgraph",
            str(_DIR / "products.graphql"),
            "--subgraph",
            str(_DIR / "reviews.graphql"),
            "--json",
        ]
    )
    assert code == EXIT_OK
    assert payload["findings"] == []
    assert "not a composition" in payload["note"]
    assert "rover compose" in payload["note"]


def test_against_needs_exactly_one_subgraph() -> None:
    code, _, err = _run(
        [
            "federation",
            "--subgraph",
            str(_DIR / "products.graphql"),
            "--subgraph",
            str(_DIR / "reviews.graphql"),
            "--against",
            str(_DIR / "products-v2.graphql"),
        ]
    )
    assert code == EXIT_USAGE
    assert "exactly one --subgraph" in err


def test_a_file_that_will_not_parse_is_a_usage_error(tmp_path: Path) -> None:
    bad = tmp_path / "bad.graphql"
    bad.write_text("type {{{ nope", encoding="utf-8")
    code, _, err = _run(["federation", "--subgraph", str(bad)])
    assert code == EXIT_USAGE
    assert "could not parse" in err or "error:" in err


@pytest.mark.parametrize("name", ["products", "reviews", "products-v2"])
def test_the_fixtures_parse(name: str) -> None:
    assert _sg(name).types
