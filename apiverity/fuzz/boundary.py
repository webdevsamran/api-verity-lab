"""Boundary-aware and pairwise case generation.

Extends the base random generator with:
- explicit boundary values for numeric/string/array constraints;
- seeded deterministic "near-boundary" valid and invalid values;
- pairwise parameter-interaction coverage without Cartesian explosion.
"""

from __future__ import annotations

import itertools
import random
from typing import Any

from apiverity.core.model import Operation, Parameter, SchemaNode


def boundary_values(schema: SchemaNode | None) -> list[Any]:
    """Deterministic interesting values for a schema's constraints."""
    if schema is None:
        return [None]
    out: list[Any] = []
    t = schema.type or ""
    if schema.enum:
        out.extend(schema.enum)
        return out
    if t in ("integer", "number"):
        lo = schema.minimum if schema.minimum is not None else schema.exclusive_minimum
        hi = schema.maximum if schema.maximum is not None else schema.exclusive_maximum
        if lo is not None:
            out.append(lo)
            if schema.exclusive_minimum is not None:
                out.append(lo + 1)
        if hi is not None:
            out.append(hi)
            if schema.exclusive_maximum is not None:
                out.append(hi - 1)
        if lo is None and hi is None:
            out.extend([0, 1])
        if schema.multiple_of:
            base = int(lo or 0)
            out.append(base + schema.multiple_of)
    elif t == "string":
        if schema.min_length is not None:
            out.append("a" * schema.min_length)
            if schema.min_length > 0:
                out.append("a" * (schema.min_length - 1))  # invalid near-boundary
        if schema.max_length is not None:
            out.append("a" * schema.max_length)
            out.append("a" * (schema.max_length + 1))  # invalid near-boundary
        if schema.pattern:
            out.append("A1-")
        if not out:
            out.extend(["", "seeded-value"])
    elif t == "array":
        if schema.min_items is not None:
            out.append([None] * schema.min_items)
        if schema.max_items is not None:
            out.append([None] * schema.max_items)
        if not out:
            out.append([])
    elif t == "boolean":
        out.extend([True, False])
    elif t == "object":
        out.append({})
    else:
        out.append(None)
    return out or [None]


def _param_choice_sets(params: list[Parameter]) -> dict[str, list[Any]]:
    choices: dict[str, list[Any]] = {}
    for p in params:
        vals = boundary_values(p.schema_node)
        if p.example is not None:
            vals.insert(0, p.example)
        choices[p.name] = vals[:6]  # cap per-parameter explosion
    return choices


def pairwise_parameter_cases(op: Operation, seed: int = 0) -> list[dict[str, Any]]:
    """Pairwise coverage across query/header/path parameters.

    Uses a greedy pairing strategy: every pair of parameters gets at least one
    combined assignment from their choice sets, without full Cartesian product.
    """
    params = [p for p in op.parameters if p.location.value in ("query", "header")]
    choices = _param_choice_sets(params)
    names = list(choices)
    if len(names) < 2:
        if names:
            return [{names[0]: v} for v in choices[names[0]]]
        return []

    rng = random.Random(seed)
    cases: list[dict[str, Any]] = []
    covered: set[tuple[int, int, Any, Any]] = set()

    # Seed with one random full assignment
    base_case = {n: rng.choice(choices[n]) for n in names}
    cases.append(base_case)

    for a, b in itertools.combinations(names, 2):
        for va in choices[a]:
            for vb in choices[b]:
                key = (names.index(a), names.index(b), va, vb)
                if key in covered:
                    continue
                case = dict(base_case)
                case[a] = va
                case[b] = vb
                cases.append(case)
                # mark this pair-instance covered
                for other in names:
                    if other not in (a, b):
                        covered.add(
                            (
                                names.index(a),
                                names.index(other),
                                va,
                                case[other],
                            )
                        )
                        covered.add(
                            (
                                names.index(b),
                                names.index(other),
                                vb,
                                case[other],
                            )
                        )
                covered.add(key)
    # dedupe while preserving order
    seen: set[tuple[tuple[str, str], ...]] = set()
    unique = []
    for c in cases:
        sig = tuple(sorted((k, repr(v)) for k, v in c.items()))
        if sig not in seen:
            seen.add(sig)
            unique.append(c)
    return unique


def near_boundary_invalid_cases(schema: SchemaNode | None) -> list[Any]:
    """Values that violate constraints by exactly one step where possible."""
    if schema is None:
        return []
    out: list[Any] = []
    t = schema.type or ""
    if t in ("integer", "number") and schema.minimum is not None:
        out.append(schema.minimum - 1)
    if t in ("integer", "number") and schema.maximum is not None:
        out.append(schema.maximum + 1)
    if t == "string":
        if schema.min_length:
            out.append("a" * max(0, schema.min_length - 1))
        if schema.max_length is not None:
            out.append("a" * (schema.max_length + 1))
        if schema.enum:
            out.append("__not_in_enum__")
    if t == "array" and schema.min_items:
        out.append([None] * (schema.min_items - 1))
    return out
