"""Deterministic positive/negative case generation from schema constraints.

Generation is fully seeded: identical contract + seed produce identical
cases. Positive cases satisfy every constraint; negative cases violate
exactly one constraint at a time so failures are attributable.
"""

from __future__ import annotations

import random
import string
from typing import Any

from apiverity.core.model import Operation, SchemaNode

_FORMAT_SAMPLES = {
    "uuid": "123e4567-e89b-42d3-a456-426614174000",
    "email": "user@example.com",
    "date": "2026-01-15",
    "date-time": "2026-01-15T10:30:00Z",
    "uri": "https://example.com/resource",
    "ipv4": "192.0.2.1",
    "int32": 42,
    "int64": 42,
}


def _random_string(rng: random.Random, length: int) -> str:
    return "".join(rng.choices(string.ascii_lowercase, k=length))


def generate_valid(schema: SchemaNode | None, rng: random.Random, depth: int = 0) -> Any:
    """Generate a value satisfying the schema constraints."""
    if schema is None or depth > 8:
        return None
    if schema.example is not None:
        return schema.example
    if schema.const is not None:
        return schema.const
    if schema.enum:
        return rng.choice(schema.enum)
    if schema.default is not None:
        return schema.default

    stype = schema.type or "object"
    if "|" in stype:
        stype = stype.split("|")[0]

    if stype == "string":
        if schema.format in _FORMAT_SAMPLES:
            sample = _FORMAT_SAMPLES[schema.format]
            return sample if isinstance(sample, str) else str(sample)
        min_len = max(schema.min_length or 1, 1)
        max_len = schema.max_length or max(min_len, 8)
        length = min(max(min_len, 3), max_len)
        return _random_string(rng, length)

    if stype == "integer":
        lo = int(schema.minimum if schema.minimum is not None else 1)
        hi = int(schema.maximum if schema.maximum is not None else lo + 100)
        if schema.exclusive_minimum is not None:
            lo = max(lo, int(schema.exclusive_minimum) + 1)
        if schema.exclusive_maximum is not None:
            hi = min(hi, int(schema.exclusive_maximum) - 1)
        return rng.randint(lo, max(lo, hi))

    if stype == "number":
        flo = schema.minimum if schema.minimum is not None else 1.0
        fhi = schema.maximum if schema.maximum is not None else flo + 100.0
        return round(rng.uniform(flo, fhi), 2)

    if stype == "boolean":
        return True

    if stype == "array":
        count = schema.min_items or 1
        item_schema = schema.items or SchemaNode(type="string")
        return [generate_valid(item_schema, rng, depth + 1) for _ in range(count)]

    # object (default)
    out: dict[str, Any] = {}
    for name, sub in schema.properties.items():
        if name in schema.required or rng.random() < 0.7:
            out[name] = generate_valid(sub, rng, depth + 1)
    for req in schema.required:
        if req not in out and req in schema.properties:
            out[req] = generate_valid(schema.properties[req], rng, depth + 1)
    return out


def generate_invalid(
    schema: SchemaNode | None, rng: random.Random, depth: int = 0
) -> list[tuple[str, Any]]:
    """Generate values violating exactly one constraint each.

    Returns ``[(violation_description, value)]``.
    """
    if schema is None or depth > 8:
        return []
    violations: list[tuple[str, Any]] = []

    stype = schema.type or "object"
    if "|" in stype:
        stype = stype.split("|")[0]

    wrong_type = {
        "string": 12345,
        "integer": "not-an-int",
        "number": "not-a-number",
        "boolean": "not-a-bool",
        "array": {"not": "an-array"},
        "object": ["not", "an-object"],
    }
    if stype in wrong_type:
        violations.append((f"wrong type (expected {stype})", wrong_type[stype]))

    if schema.enum:
        bad = f"__invalid_enum_{rng.randint(0, 9999)}"
        violations.append((f"value outside enum {schema.enum}", bad))

    if stype == "string":
        base = _random_string(rng, 5)
        if schema.min_length is not None:
            violations.append(
                (
                    f"length < minLength({schema.min_length})",
                    _random_string(rng, max(schema.min_length - 1, 0)),
                )
            )
        if schema.max_length is not None:
            violations.append(
                (
                    f"length > maxLength({schema.max_length})",
                    _random_string(rng, schema.max_length + 5),
                )
            )
        if schema.pattern is not None:
            violations.append((f"violates pattern {schema.pattern!r}", base + "!!!"))

    if stype in ("integer", "number"):
        lo = schema.minimum
        hi = schema.maximum
        if lo is not None:
            violations.append((f"value < minimum({lo})", lo - 1))
        if hi is not None:
            violations.append((f"value > maximum({hi})", hi + 1))
        if schema.exclusive_minimum is not None:
            violations.append(
                (f"value <= exclusiveMinimum({schema.exclusive_minimum})", schema.exclusive_minimum)
            )
        if schema.exclusive_maximum is not None:
            violations.append(
                (f"value >= exclusiveMaximum({schema.exclusive_maximum})", schema.exclusive_maximum)
            )
        if schema.multiple_of:
            m = schema.multiple_of
            violations.append((f"not a multiple of {m}", m / 2 if m else 1))

    if stype == "array":
        if schema.min_items is not None:
            violations.append(
                (f"{max(schema.min_items - 1, 0)} items < minItems({schema.min_items})", [])
            )
        if schema.items is not None:
            bad_items = generate_invalid(schema.items, rng, depth + 1)
            for desc, val in bad_items[:2]:
                violations.append((f"item {desc}", [val]))

    if stype == "object":
        for req in schema.required:
            partial = {
                name: generate_valid(sub, rng, depth + 1)
                for name, sub in schema.properties.items()
                if name != req
            }
            violations.append((f"missing required field '{req}'", partial))
        for name, sub in list(schema.properties.items())[:4]:
            for desc, val in generate_invalid(sub, rng, depth + 1)[:2]:
                full = {
                    n: generate_valid(s2, rng, depth + 1) for n, s2 in schema.properties.items()
                }
                full[name] = val
                violations.append((f"field '{name}': {desc}", full))

    return violations


def fill_path(path: str, params: dict[str, Any]) -> str:
    """Substitute ``{name}`` placeholders in a path template."""
    out = path
    for name, value in params.items():
        out = out.replace("{" + name + "}", str(value))
    return out


def operation_cases(op: Operation, seed: int) -> list[dict[str, Any]]:
    """Build positive + negative request cases for one operation.

    Returns dicts with keys: kind, description, path_params, query,
    headers, body.
    """
    rng = random.Random(seed)
    cases: list[dict[str, Any]] = []

    path_params = {
        p.name: generate_valid(p.schema_node, rng)
        for p in op.parameters
        if p.location.value == "path"
    }
    query_valid = {
        p.name: generate_valid(p.schema_node, rng)
        for p in op.parameters
        if p.location.value == "query"
    }
    header_valid = {
        p.name: str(generate_valid(p.schema_node, rng))
        for p in op.parameters
        if p.location.value == "header"
    }

    body_media = None
    body_schema = None
    if op.request_body is not None and op.request_body.content:
        body_media = sorted(op.request_body.content)[0]
        body_schema = op.request_body.content[body_media]

    # positive case
    cases.append(
        {
            "kind": "positive",
            "description": f"valid request to {op.key}",
            "path_params": path_params,
            "query": query_valid,
            "headers": header_valid,
            "body": generate_valid(body_schema, rng) if body_schema else None,
            "media": body_media,
        }
    )

    # negative cases from parameters
    for p in op.parameters:
        if p.location.value in ("path", "query") and p.schema_node is not None:
            for desc, val in generate_invalid(p.schema_node, rng)[:2]:
                q = dict(query_valid)
                if p.location.value == "query":
                    q[p.name] = val
                    cases.append(
                        {
                            "kind": "negative",
                            "description": f"parameter '{p.name}' invalid: {desc}",
                            "path_params": path_params,
                            "query": q,
                            "headers": header_valid,
                            "body": None,
                            "media": None,
                        }
                    )
                elif p.location.value == "path":
                    pp = dict(path_params)
                    pp[p.name] = val
                    cases.append(
                        {
                            "kind": "negative",
                            "description": f"path parameter '{p.name}' invalid: {desc}",
                            "path_params": pp,
                            "query": query_valid,
                            "headers": header_valid,
                            "body": None,
                            "media": None,
                        }
                    )

    # negative cases from body
    if body_schema is not None:
        for desc, val in generate_invalid(body_schema, rng):
            cases.append(
                {
                    "kind": "negative",
                    "description": f"request body invalid: {desc}",
                    "path_params": path_params,
                    "query": query_valid,
                    "headers": header_valid,
                    "body": val,
                    "media": body_media,
                }
            )

    return cases
