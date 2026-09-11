"""If I edit `shared/money.yaml`, whose build goes red?

Forty services in a monorepo have forty contract gates and no answer to that.
The flat `Service.dependencies` list cannot produce one: it records every
location an entry document pulled and not one parent, so a graph built from it
draws a schema's schema as a child of the contract, at a path that does not
resolve from the contract's directory.
"""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
from typing import Any

from apiverity.cli.commands.common import EXIT_FINDINGS, EXIT_OK, EXIT_USAGE
from apiverity.cli.main import main
from apiverity.specs.graph import CONTRACT, REMOTE, SCHEMA, build, mermaid
from apiverity.specs.loader import detect_and_load

_ROOT = Path(__file__).resolve().parents[2]
_TREE = _ROOT / "fixtures/apis/graph"


def _run(argv: list[str]) -> tuple[int, dict[str, Any], str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    text = out.getvalue()
    return code, (json.loads(text) if text.strip().startswith("{") else {}), err.getvalue()


def _edge(source: str, target: str, **kw: Any) -> dict[str, Any]:
    return {"source": source, "target": target, "resolved": None, "refused": None, **kw}


# --------------------------------------------------- what the flat list cannot


def test_the_loader_now_records_which_file_carried_each_reference() -> None:
    """`dependencies` is flat; `dependency_edges` has the parent.

    The multi-file fixture proves why it matters: `./order.yaml` is a reference
    made *by* `schemas/order.yaml`, and read as a child of the entry document
    it names a file that does not exist.
    """
    service, _, _ = detect_and_load(str(_ROOT / "fixtures/apis/multifile/openapi.yaml"))
    assert "./order.yaml" in service.dependencies
    carriers = {e["source"] for e in service.dependency_edges if e["target"] == "./order.yaml"}
    assert carriers == {"schemas/order.yaml"}, "the reference was attributed to the wrong file"


def test_a_transitive_dependency_is_not_drawn_as_a_direct_one() -> None:
    graph = build(
        {
            "svc/api.yaml": [
                _edge("api.yaml", "../shared/money.yaml", resolved="shared/money.yaml"),
                _edge("shared/money.yaml", "./party.yaml", resolved="shared/party.yaml"),
            ]
        }
    )
    pairs = {(e.source, e.target) for e in graph.edges}
    assert pairs == {
        ("svc/api.yaml", "shared/money.yaml"),
        ("shared/money.yaml", "shared/party.yaml"),
    }


# ------------------------------------------------------------- blast radius


def test_every_contract_that_reaches_a_shared_schema_is_named() -> None:
    code, payload, _ = _run(["graph", str(_TREE), "--json"])
    assert code == EXIT_OK
    assert payload["shared"]["shared/money.yaml"] == [
        "services/billing/openapi.yaml",
        "services/orders/openapi.yaml",
    ]


def test_a_schema_nothing_references_directly_still_has_dependents() -> None:
    """`party.yaml` is reached only through `money.yaml`, and both contracts reach it."""
    _, payload, _ = _run(["graph", str(_TREE), "--dependents-of", "shared/party.yaml", "--json"])
    assert payload["dependents_of"]["contracts"] == [
        "services/billing/openapi.yaml",
        "services/orders/openapi.yaml",
    ]
    assert payload["dependents_of"]["known"] is True


def test_a_node_that_is_not_in_the_tree_says_so_rather_than_reporting_zero() -> None:
    """Nothing depends on it, and it is not here, produce the same empty list."""
    _, payload, _ = _run(["graph", str(_TREE), "--dependents-of", "nope.yaml", "--json"])
    assert payload["dependents_of"]["contracts"] == []
    assert payload["dependents_of"]["known"] is False


def test_two_contracts_with_the_same_relative_schema_path_do_not_collide() -> None:
    graph = build(
        {
            "a/api.yaml": [
                _edge("api.yaml", "./schemas/order.yaml", resolved="schemas/order.yaml")
            ],
            "b/api.yaml": [
                _edge("api.yaml", "./schemas/order.yaml", resolved="schemas/order.yaml")
            ],
        }
    )
    assert graph.shared() == {}, "two different files were merged into one node"
    assert set(graph.nodes) >= {"a/schemas/order.yaml", "b/schemas/order.yaml"}


# --------------------------------------------------- what it refuses to hide


def test_a_reference_this_run_did_not_follow_is_still_an_edge() -> None:
    """Dropping it makes a contract look like it depends on less than it does."""
    graph = build(
        {
            "api.yaml": [
                _edge(
                    "api.yaml",
                    "https://schemas.example.test/money.yaml",
                    refused="remote, and --allow-remote-refs was not given",
                )
            ]
        }
    )
    assert len(graph.edges) == 1
    assert graph.refused()[0].refused
    assert graph.nodes["https://schemas.example.test/money.yaml"].kind == REMOTE


def test_the_supply_chain_fixtures_remote_refs_are_in_the_graph() -> None:
    _, payload, _ = _run(["graph", str(_ROOT / "fixtures"), "--json"])
    reasons = {e["reason"] for e in payload["not_followed"]}
    assert reasons == {"remote, and --allow-remote-refs was not given"}
    assert any(e["target"].startswith("https://") for e in payload["edges"])


def test_a_reference_whose_parent_is_unknown_is_not_attached_to_the_root() -> None:
    """Attaching it would be a guess, and a guess is what a graph is for avoiding."""
    graph = build({"api.yaml": [_edge("mystery.yaml", "./x.yaml")]})
    assert graph.edges == []
    assert graph.unplaced[0]["source"] == "mystery.yaml"
    assert "never introduced" in graph.unplaced[0]["reason"]


def test_a_contract_that_will_not_load_is_named_not_skipped(tmp_path: Path) -> None:
    good = tmp_path / "good.yaml"
    good.write_text(
        (_ROOT / "fixtures/apis/crud/openapi.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (tmp_path / "broken.yaml").write_text(
        "openapi: 3.1.0\ninfo:\n  title: X\n   version: bad indent\npaths: {\n", encoding="utf-8"
    )
    code, payload, _ = _run(["graph", str(tmp_path), "--json"])
    assert [u["path"] for u in payload["unreadable"]] == ["broken.yaml"]
    assert code == EXIT_FINDINGS, "a tree with an unreadable contract passed silently"


# ------------------------------------------------------------------- cycles


def test_a_self_reference_is_reported_and_does_not_hang() -> None:
    """The multi-file fixture in this repository contains one."""
    _, payload, _ = _run(["graph", str(_ROOT / "fixtures"), "--json"])
    assert payload["cycles"] == [
        ["apis/multifile/schemas/order.yaml", "apis/multifile/schemas/order.yaml"]
    ]


def test_a_two_file_cycle_is_named_by_its_members() -> None:
    graph = build(
        {
            "api.yaml": [
                _edge("api.yaml", "./a.yaml", resolved="a.yaml"),
                _edge("a.yaml", "./b.yaml", resolved="b.yaml"),
                _edge("b.yaml", "./a.yaml", resolved="a.yaml"),
            ]
        }
    )
    assert len(graph.cycles) == 1
    assert set(graph.cycles[0]) == {"a.yaml", "b.yaml"}


def test_a_cycle_is_reported_once_however_it_is_entered() -> None:
    graph = build(
        {
            "one.yaml": [
                _edge("one.yaml", "./a.yaml", resolved="a.yaml"),
                _edge("a.yaml", "./b.yaml", resolved="b.yaml"),
                _edge("b.yaml", "./a.yaml", resolved="a.yaml"),
            ],
            "two.yaml": [
                _edge("two.yaml", "./b.yaml", resolved="b.yaml"),
                _edge("b.yaml", "./a.yaml", resolved="a.yaml"),
                _edge("a.yaml", "./b.yaml", resolved="b.yaml"),
            ],
        }
    )
    assert len(graph.cycles) == 1


def test_a_cycle_fails_the_run() -> None:
    code, _, _ = _run(["graph", str(_ROOT / "fixtures")])
    assert code == EXIT_FINDINGS


# ------------------------------------------------------------------- output


def test_the_diagram_marks_an_unfollowed_edge_differently() -> None:
    graph = build(
        {
            "api.yaml": [
                _edge("api.yaml", "./a.yaml", resolved="a.yaml"),
                _edge("api.yaml", "https://x.test/b.yaml", refused="remote"),
            ]
        }
    )
    body = mermaid(graph)
    assert "-->" in body and "-.->" in body
    assert body.startswith("graph LR")


def test_a_truncated_diagram_says_it_was_truncated() -> None:
    """One that silently drew the first hundred would read as the whole tree."""
    edges = [_edge("api.yaml", f"./s{n}.yaml") for n in range(10)]
    graph = build({"api.yaml": edges})
    assert "...and 7 more edges, not drawn" in mermaid(graph, limit=3)


def test_nodes_are_typed_so_a_url_is_not_counted_as_a_file_somebody_can_edit() -> None:
    graph = build(
        {
            "api.yaml": [
                _edge("api.yaml", "./a.yaml", resolved="a.yaml"),
                _edge("api.yaml", "https://x.test/b.yaml", refused="remote"),
            ]
        }
    )
    kinds = {n.id: n.kind for n in graph.nodes.values()}
    assert kinds["api.yaml"] == CONTRACT
    assert kinds["a.yaml"] == SCHEMA
    assert kinds["https://x.test/b.yaml"] == REMOTE


def test_a_reference_out_of_the_tree_is_marked_as_such() -> None:
    graph = build({"svc/api.yaml": [_edge("api.yaml", "../../../vendor/x.yaml")]})
    node = next(n for n in graph.nodes.values() if n.kind == SCHEMA)
    assert node.outside is True


def test_an_empty_tree_is_a_usage_error_not_an_empty_graph() -> None:
    code, _, err = _run(["graph", str(_ROOT / "docs")])
    assert code == EXIT_USAGE
    assert "not the same as nothing depending on anything" in err
