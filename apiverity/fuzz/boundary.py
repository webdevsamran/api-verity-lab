"""Boundary values, and every pair of parameters at least once.

`apiverity test --generator pairwise` is what reaches this. Until it did,
`docs/capability-status.md` published "boundary values, pairwise -- EXISTING"
about a module no command could run, and the thing below had gone unnoticed for
exactly that long.

## `boundary_values` returned values that violate the schema

Its docstring says "interesting values for a schema's constraints" and it
returned, among the valid ones:

- `"a" * (min_length - 1)` and `"a" * (max_length + 1)`, both marked `# invalid
  near-boundary` in the source and both already produced by
  `near_boundary_invalid_cases`;
- the exclusive bound itself. `exclusiveMinimum: 5` means 5 is forbidden, and
  `lo` was appended before `lo + 1`;
- `"A1-"` for any `pattern`, which is a guess at a regex nobody read.

That did not matter while the only caller was `pairwise_parameter_cases`, which
treats every value the same. It matters the moment a generator has to say
whether a case is positive or negative, because a case built from those values
expects a 4xx and would have been sent expecting a 2xx -- reporting a service
as broken for rejecting a value its own contract forbids.

So `boundary_values` returns only values that **satisfy** the schema, and
everything that violates one lives in `near_boundary_invalid_cases`. A
`pattern` yields nothing: a string that matches an arbitrary regex cannot be
derived here, and inventing one is how a generator ends up asserting that its
own guess is correct.

## Pairwise, measured rather than claimed

Five parameters with six values each: 276 cases against a Cartesian product of
7,776, covering all 360 pairs. It is not an optimal covering array -- an
optimal one needs about 36 -- and `tests/unit/test_pairwise_generator.py`
asserts the coverage rather than the optimality, because coverage is the
property the caller depends on.
"""

from __future__ import annotations

import itertools
import random
from typing import Any

from apiverity.core.model import Operation, Parameter, SchemaNode


def boundary_values(schema: SchemaNode | None) -> list[Any]:
    """Values that sit on a constraint and **satisfy** it.

    Every value here is one the contract permits, so a case built from them is
    a positive case. What violates a constraint is in
    `near_boundary_invalid_cases`, and the two used to overlap -- see the
    module docstring.
    """
    if schema is None:
        return [None]
    out: list[Any] = []
    t = schema.type or ""
    if schema.enum:
        out.extend(schema.enum)
        return out
    if t in ("integer", "number"):
        out.extend(_numeric_boundaries(schema))
    elif t == "string":
        if schema.pattern:
            # A string matching an arbitrary regex cannot be derived here, and
            # a guess would be a value this module asserts is valid without
            # having checked. The random generator still covers this field.
            return []
        if schema.min_length is not None:
            out.append("a" * schema.min_length)
        if schema.max_length is not None:
            out.append("a" * schema.max_length)
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


def _numeric_boundaries(schema: SchemaNode) -> list[Any]:
    """The smallest and largest permitted values, and one `multipleOf` step.

    `minimum` includes its bound; `exclusiveMinimum` does not, so the smallest
    permitted value is one step past it. Returning the exclusive bound itself
    -- which this did -- is returning the one value the contract singles out as
    forbidden.
    """
    out: list[Any] = []
    step = schema.multiple_of or 1
    low = None
    if schema.minimum is not None:
        low = schema.minimum
    elif schema.exclusive_minimum is not None:
        low = schema.exclusive_minimum + step
    high = None
    if schema.maximum is not None:
        high = schema.maximum
    elif schema.exclusive_maximum is not None:
        high = schema.exclusive_maximum - step
    if low is not None:
        out.append(low)
    if high is not None and high != low:
        out.append(high)
    if low is None and high is None:
        out.extend([0, 1])
    if schema.multiple_of:
        candidate = (low if low is not None else 0) + schema.multiple_of
        if high is None or candidate <= high:
            out.append(candidate)
    return out


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
    """Values that violate a constraint by exactly one step where possible.

    Off-by-one validators live here: a service that accepts its own
    `exclusiveMinimum` is accepting the one value its contract singles out as
    forbidden, and nothing else in the suite sends that value.
    """
    if schema is None:
        return []
    out: list[Any] = []
    t = schema.type or ""
    if t in ("integer", "number"):
        step = schema.multiple_of or 1
        if schema.minimum is not None:
            out.append(schema.minimum - step)
        if schema.maximum is not None:
            out.append(schema.maximum + step)
        # The exclusive bound itself. `boundary_values` used to return it as a
        # permitted value; it is the opposite.
        if schema.exclusive_minimum is not None:
            out.append(schema.exclusive_minimum)
        if schema.exclusive_maximum is not None:
            out.append(schema.exclusive_maximum)
    if t == "string":
        if schema.min_length:
            out.append("a" * max(0, schema.min_length - 1))
        if schema.max_length is not None:
            out.append("a" * (schema.max_length + 1))
        if schema.enum:
            out.append("__not_in_enum__")
    if t == "array":
        if schema.min_items:
            out.append([None] * (schema.min_items - 1))
        if schema.max_items is not None:
            out.append([None] * (schema.max_items + 1))
    return out
