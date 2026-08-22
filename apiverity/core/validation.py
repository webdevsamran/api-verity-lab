"""Lightweight validator for values against :class:`SchemaNode`.

Used by the fuzz runner (response validation), drift detection (body
schema checks) and the mock server (example sanity). Deliberately small:
covers the constraint surface the normalized model carries.
"""

from __future__ import annotations

import re
from typing import Any

from apiverity.core.model import SchemaNode


def _type_matches(expected: str | None, value: Any) -> bool:
    if expected is None:
        return True
    if "|" in expected:
        return any(_type_matches(t, value) for t in expected.split("|"))
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "null":
        return value is None
    return True


def validate_value(
    schema: SchemaNode | None,
    value: Any,
    *,
    path: str = "$",
    forbid_undeclared_fields: bool = False,
) -> list[str]:
    """Return a list of violation messages (empty list means valid)."""
    errors: list[str] = []
    if schema is None:
        return errors

    if value is None:
        if not schema.nullable:
            errors.append(f"{path}: null is not allowed")
        return errors

    if schema.enum is not None and value not in schema.enum:
        errors.append(f"{path}: value {value!r} not in enum {schema.enum}")
        return errors

    if schema.const is not None and value != schema.const:
        errors.append(f"{path}: value {value!r} != const {schema.const!r}")
        return errors

    if not _type_matches(schema.type, value):
        errors.append(f"{path}: expected type {schema.type}, got {type(value).__name__}")
        return errors

    if schema.type == "string":
        assert isinstance(value, str)
        if schema.min_length is not None and len(value) < schema.min_length:
            errors.append(f"{path}: length {len(value)} < minLength {schema.min_length}")
        if schema.max_length is not None and len(value) > schema.max_length:
            errors.append(f"{path}: length {len(value)} > maxLength {schema.max_length}")
        if schema.pattern is not None and re.search(schema.pattern, value) is None:
            errors.append(f"{path}: does not match pattern {schema.pattern!r}")

    elif schema.type in ("integer", "number"):
        assert isinstance(value, (int, float))
        if schema.minimum is not None and value < schema.minimum:
            errors.append(f"{path}: {value} < minimum {schema.minimum}")
        if schema.maximum is not None and value > schema.maximum:
            errors.append(f"{path}: {value} > maximum {schema.maximum}")
        if schema.exclusive_minimum is not None and value <= schema.exclusive_minimum:
            errors.append(f"{path}: {value} <= exclusiveMinimum {schema.exclusive_minimum}")
        if schema.exclusive_maximum is not None and value >= schema.exclusive_maximum:
            errors.append(f"{path}: {value} >= exclusiveMaximum {schema.exclusive_maximum}")
        if schema.multiple_of is not None and schema.multiple_of != 0:
            if abs(value / schema.multiple_of - round(value / schema.multiple_of)) > 1e-9:
                errors.append(f"{path}: {value} not a multiple of {schema.multiple_of}")

    elif schema.type == "array":
        assert isinstance(value, list)
        if schema.min_items is not None and len(value) < schema.min_items:
            errors.append(f"{path}: {len(value)} items < minItems {schema.min_items}")
        if schema.max_items is not None and len(value) > schema.max_items:
            errors.append(f"{path}: {len(value)} items > maxItems {schema.max_items}")
        if schema.unique_items and len({repr(v) for v in value}) != len(value):
            errors.append(f"{path}: items are not unique")
        if schema.items is not None:
            for i, item in enumerate(value):
                errors.extend(validate_value(schema.items, item, path=f"{path}[{i}]"))

    elif schema.type == "object":
        assert isinstance(value, dict)
        for req in schema.required:
            if req not in value:
                errors.append(f"{path}: missing required field '{req}'")
        for name, sub in schema.properties.items():
            if name in value:
                errors.extend(validate_value(sub, value[name], path=f"{path}.{name}"))
        declared = set(schema.properties)
        extra = [k for k in value if k not in declared]
        if extra:
            addl = schema.additional_properties
            if addl is False:
                errors.append(f"{path}: undeclared field(s) {sorted(extra)} "
                              "(additionalProperties: false)")
            elif forbid_undeclared_fields and addl is None:
                errors.append(f"{path}: undeclared field(s) {sorted(extra)}")
            elif isinstance(addl, SchemaNode):
                for k in extra:
                    errors.extend(
                        validate_value(addl, value[k], path=f"{path}.{k}")
                    )

    # composition: anyOf/oneOf must match at least one variant
    for attr, label in (("any_of", "anyOf"), ("one_of", "oneOf")):
        variants = getattr(schema, attr)
        if variants:
            ok = any(not validate_value(v, value, path=path) for v in variants)
            if not ok:
                errors.append(f"{path}: does not match any {label} variant")

    return errors