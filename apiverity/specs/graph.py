"""Which contract reads whose schemas, across a tree of them.

A monorepo with forty services has forty contract gates and no answer to the
question a platform team actually has: *if I edit `shared/money.yaml`, whose
build goes red?*

`Service.dependencies` cannot answer it. It is the flat set of locations an
entry document pulled, so a shared schema that references a second shared
schema appears in it with no indication of who asked for it -- and a graph
built from the flat list draws every transitive dependency as a direct child of
the contract, at a relative path that does not resolve from the contract's own
directory. `Service.dependency_edges` carries the parent, which is what makes a
graph possible at all.

## What this refuses to call an absence

Three things, all of which look identical in a naive graph and mean different
things:

* **A reference this run did not follow.** A remote `$ref` without
  `--allow-remote-refs`, an absolute path, a file that would not read. The edge
  is drawn and marked `refused`, with the reason. Dropping it would make a
  contract look like it depends on less than it does, in the report whose whole
  job is the opposite.
* **A reference whose parent is unknown.** If a `$ref` is carried by a file
  this builder never saw introduced, the edge cannot be placed in the tree.
  It is listed in `unplaced` rather than attached to the contract root, which
  is where a guess would put it.
* **A cycle.** `a.yaml` refers to `b.yaml` refers to `a.yaml`, or a file refers
  to itself -- which the multi-file fixture in this repository does. Named,
  and never walked twice.

## What it is for

`dependents_of(node)` is the blast radius of editing one shared file, and it is
the number that makes the graph worth building.
"""

from __future__ import annotations

import posixpath
from dataclasses import dataclass, field
from typing import Any

#: What a node in the graph is.
#:
#: `remote` is separate from `schema` because a URL is not a file anybody in
#: this repository can edit, and a blast radius that mixes the two answers the
#: wrong question.
CONTRACT = "contract"
SCHEMA = "schema"
REMOTE = "remote"


def _is_remote(location: str) -> bool:
    return location.startswith(("http://", "https://"))


def _join(source_id: str, target: str) -> str:
    """Where `target` points, read from the file at `source_id`.

    Normalized with `posixpath` rather than `Path`, so a graph built on Windows
    and a graph built in CI name the same node.
    """
    if _is_remote(target):
        return target
    return posixpath.normpath(posixpath.join(posixpath.dirname(source_id), target))


@dataclass
class Node:
    id: str
    kind: str
    #: True when the node is outside the tree that was walked. A `../../`
    #: reference out of a monorepo is legitimate and is not a contract this run
    #: looked at, so nothing here knows whether it is governed.
    outside: bool = False


@dataclass
class GraphEdge:
    source: str
    target: str
    #: The reference as the document writes it, which is what a reader greps for.
    reference: str
    #: Why this run did not follow it, if it did not.
    refused: str | None = None
    #: The contract whose load produced this edge.
    via: str = ""


@dataclass
class DependencyGraph:
    nodes: dict[str, Node] = field(default_factory=dict)
    edges: list[GraphEdge] = field(default_factory=list)
    #: Edges whose parent file was never introduced, so they have no place in
    #: the tree. Reported rather than attached to the contract root.
    unplaced: list[dict[str, str]] = field(default_factory=list)
    #: Each cycle as the sequence of node ids that closes it.
    cycles: list[list[str]] = field(default_factory=list)

    def dependents_of(self, node_id: str) -> list[str]:
        """Every contract that reaches `node_id`, directly or through others.

        The blast radius of editing one shared file, and the reason this
        module exists.
        """
        incoming: dict[str, list[str]] = {}
        for edge in self.edges:
            incoming.setdefault(edge.target, []).append(edge.source)

        seen: set[str] = set()
        stack = [node_id]
        contracts: set[str] = set()
        while stack:
            current = stack.pop()
            for parent in incoming.get(current, []):
                if parent in seen:
                    continue
                seen.add(parent)
                if self.nodes.get(parent) and self.nodes[parent].kind == CONTRACT:
                    contracts.add(parent)
                stack.append(parent)
        return sorted(contracts)

    def shared(self) -> dict[str, list[str]]:
        """Nodes more than one contract reaches, with the contracts."""
        out: dict[str, list[str]] = {}
        for node_id, node in self.nodes.items():
            if node.kind == CONTRACT:
                continue
            dependents = self.dependents_of(node_id)
            if len(dependents) > 1:
                out[node_id] = dependents
        return dict(sorted(out.items()))

    def refused(self) -> list[GraphEdge]:
        return [edge for edge in self.edges if edge.refused]


def _find_cycles(edges: list[GraphEdge]) -> list[list[str]]:
    """Every cycle reachable in the edge set, each reported once.

    Iterative depth-first, because a contract tree that refers to itself is
    exactly the input that would blow a recursive walk's stack -- and the
    multi-file fixture in this repository contains a self-reference.
    """
    children: dict[str, list[str]] = {}
    for edge in edges:
        children.setdefault(edge.source, []).append(edge.target)

    found: list[list[str]] = []
    seen_signatures: set[tuple[str, ...]] = set()
    finished: set[str] = set()

    for start in list(children):
        if start in finished:
            continue
        # (node, path-to-it). The path is carried rather than reconstructed so
        # the cycle can be *named*, not merely detected.
        stack: list[tuple[str, list[str]]] = [(start, [start])]
        while stack:
            node, path = stack.pop()
            finished.add(node)
            for child in children.get(node, []):
                if child in path:
                    cycle = [*path[path.index(child) :], child]
                    signature = tuple(sorted(set(cycle)))
                    if signature not in seen_signatures:
                        seen_signatures.add(signature)
                        found.append(cycle)
                    continue
                if len(path) > 64:
                    continue
                stack.append((child, [*path, child]))
    return found


def build(contracts: dict[str, list[dict[str, Any]]]) -> DependencyGraph:
    """A graph from `{contract path: Service.dependency_edges}`.

    Contract paths are relative to whatever tree was walked, and every node id
    is relative to the same tree, so two contracts in different directories
    that both reference `schemas/order.yaml` do not collide.
    """
    graph = DependencyGraph()

    for contract, raw_edges in contracts.items():
        graph.nodes.setdefault(contract, Node(id=contract, kind=CONTRACT))
        # The bundler labels sources relative to the entry document's own
        # directory, so the entry is its bare filename. Everything else is
        # placed by following the edge that introduced it.
        entry_label = posixpath.basename(contract)
        label_to_id: dict[str, str] = {entry_label: contract}

        for raw in raw_edges:
            source_label = str(raw.get("source") or "")
            reference = str(raw.get("target") or "")
            source_id = label_to_id.get(source_label)
            if source_id is None:
                graph.unplaced.append(
                    {
                        "contract": contract,
                        "source": source_label,
                        "reference": reference,
                        "reason": (
                            "the file carrying this reference was never introduced by "
                            "another reference, so it has no place in the tree"
                        ),
                    }
                )
                continue

            target_id = _join(source_id, reference)
            kind = REMOTE if _is_remote(target_id) else SCHEMA
            outside = kind != REMOTE and target_id.startswith("..")
            if target_id not in graph.nodes:
                graph.nodes[target_id] = Node(id=target_id, kind=kind, outside=outside)

            edge = GraphEdge(
                source=source_id,
                target=target_id,
                reference=reference,
                refused=raw.get("refused"),
                via=contract,
            )
            if not any(e.source == edge.source and e.target == edge.target for e in graph.edges):
                graph.edges.append(edge)

            resolved = raw.get("resolved")
            if resolved:
                label_to_id.setdefault(str(resolved), target_id)

    graph.cycles = _find_cycles(graph.edges)
    return graph


def mermaid(graph: DependencyGraph, *, limit: int = 120) -> str:
    """The graph as a mermaid diagram, for a README or the docs site.

    Truncated loudly rather than quietly: a diagram of four hundred nodes is
    unreadable, and one that silently showed the first hundred would be read as
    the whole tree.
    """
    ids: dict[str, str] = {}

    def key(node_id: str) -> str:
        if node_id not in ids:
            ids[node_id] = f"n{len(ids)}"
        return ids[node_id]

    lines = ["graph LR"]
    for edge in graph.edges[:limit]:
        arrow = "-.->" if edge.refused else "-->"
        lines.append(
            f"  {key(edge.source)}[{edge.source}] {arrow} {key(edge.target)}[{edge.target}]"
        )
    if len(graph.edges) > limit:
        lines.append(f"  more[...and {len(graph.edges) - limit} more edges, not drawn]")
    for node_id, node in graph.nodes.items():
        if node.kind == CONTRACT and node_id in ids:
            lines.append(f"  style {ids[node_id]} stroke-width:2px")
    return "\n".join(lines) + "\n"


def as_dict(graph: DependencyGraph) -> dict[str, Any]:
    return {
        "nodes": [
            {"id": n.id, "kind": n.kind, **({"outside": True} if n.outside else {})}
            for n in graph.nodes.values()
        ],
        "edges": [
            {
                "source": e.source,
                "target": e.target,
                "reference": e.reference,
                "via": e.via,
                **({"refused": e.refused} if e.refused else {}),
            }
            for e in graph.edges
        ],
        "shared": graph.shared(),
        "cycles": graph.cycles,
        # Named, not counted. "Three references were not followed" tells a
        # reader nothing about whether the graph they are looking at is the
        # whole graph.
        "not_followed": [
            {"source": e.source, "reference": e.reference, "reason": e.refused}
            for e in graph.refused()
        ],
        "unplaced": graph.unplaced,
    }


__all__ = [
    "CONTRACT",
    "REMOTE",
    "SCHEMA",
    "DependencyGraph",
    "GraphEdge",
    "Node",
    "as_dict",
    "build",
    "mermaid",
]
