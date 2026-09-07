"""Pluggable case generators (#19).

The `apiverity.generators` entry-point group was declared, documented and
registered -- and never read. `apiverity test` called `build_cases` directly,
so a third party could install a generator and it would load into the registry
and then do nothing. This module is the part that was missing: a protocol
generators implement, and a dispatch that actually calls them.

Each generator answers one question about an operation, and each ships as its
own strategy rather than more branches inside `operation_cases`, because the
strategies have genuinely different opinions about what a correct server does:

- `schema` -- the existing valid/invalid derivation from the declared schema.
- `unicode` -- text a real user will send. These are **positive**: a service
  that 500s on an emoji or mangles a combining mark has a bug, and asserting
  4xx here would be asserting the bug is correct.
- `nesting` -- payloads nested past any reasonable depth. **Negative**: a
  service should reject them, and the finding that matters is a 5xx, which
  `_check_response` already treats as a violation whatever the case kind.
- `numeric` -- sweeps derived from `multipleOf` and the exclusive bounds.
  Values inside the declared range are positive, values outside negative;
  which side of the boundary a value falls on is exactly what these are for.
- `header-safety` -- defensive only. Header values containing CR/LF and
  friends, to check the service rejects or sanitizes them. There is no exploit
  payload here and there is not meant to be: the generator's job is to find
  out whether untrusted bytes reach a header, not to weaponise it.

Determinism is per generator: each is handed a seed derived from the run seed
and its own name, so adding a generator does not renumber the cases of the
ones beside it.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable
from typing import Any, ClassVar, Protocol, runtime_checkable

from apiverity.core.model import Operation, SchemaNode
from apiverity.fuzz.generate import generate_valid

__all__ = [
    "BUILTIN_GENERATORS",
    "CaseGenerator",
    "GeneratedCase",
    "HeaderSafetyGenerator",
    "NestingGenerator",
    "NumericBoundaryGenerator",
    "UnicodeGenerator",
    "load_generators",
]


class GeneratedCase(dict[str, Any]):
    """One case, in the shape `build_cases` already consumes.

    A plain dict rather than a model: `operation_cases` has always produced
    these keys, and a generator written against the documented contract should
    not have to import a pydantic model to return four fields.
    """

    def __init__(
        self,
        *,
        kind: str,
        description: str,
        path_params: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        body: Any = None,
        media: str | None = None,
    ) -> None:
        super().__init__(
            kind=kind,
            description=description,
            path_params=path_params or {},
            query=query or {},
            headers=headers or {},
            body=body,
            media=media,
        )


@runtime_checkable
class CaseGenerator(Protocol):
    """What a third-party generator implements.

    Deliberately small. A generator that cannot say anything about an
    operation returns nothing; it does not need to know about the rest of the
    pipeline, and returning an empty list is the normal case for most
    operations.
    """

    name: str

    def generate(self, op: Operation, seed: int) -> Iterable[dict[str, Any]]:
        """Cases for one operation. Must be deterministic given `seed`."""
        ...


# --------------------------------------------------------------------- helpers


def _string_fields(schema: SchemaNode | None, prefix: str = "") -> list[tuple[str, SchemaNode]]:
    """Every string-typed leaf in a schema, with its dotted path."""
    if schema is None:
        return []
    found: list[tuple[str, SchemaNode]] = []
    if schema.type == "string":
        found.append((prefix or "$", schema))
    for name, child in (schema.properties or {}).items():
        found.extend(_string_fields(child, f"{prefix}.{name}" if prefix else name))
    if schema.items is not None:
        found.extend(_string_fields(schema.items, f"{prefix}[]"))
    return found


def _numeric_fields(schema: SchemaNode | None, prefix: str = "") -> list[tuple[str, SchemaNode]]:
    if schema is None:
        return []
    found: list[tuple[str, SchemaNode]] = []
    if schema.type in ("integer", "number"):
        found.append((prefix or "$", schema))
    for name, child in (schema.properties or {}).items():
        found.extend(_numeric_fields(child, f"{prefix}.{name}" if prefix else name))
    if schema.items is not None:
        found.extend(_numeric_fields(schema.items, f"{prefix}[]"))
    return found


def _set_at(body: Any, dotted: str, value: Any) -> Any:
    """Set a dotted path in a nested structure, returning a modified copy."""
    if dotted in ("$", ""):
        return value
    import copy

    out = copy.deepcopy(body)
    parts = dotted.split(".")
    cursor = out
    for part in parts[:-1]:
        if part.endswith("[]"):
            key = part[:-2]
            if not isinstance(cursor, dict) or key not in cursor:
                return out
            cursor = cursor[key]
            if not isinstance(cursor, list) or not cursor:
                return out
            cursor = cursor[0]
        else:
            if not isinstance(cursor, dict) or part not in cursor:
                return out
            cursor = cursor[part]
    last = parts[-1]
    if last.endswith("[]"):
        key = last[:-2]
        if isinstance(cursor, dict) and isinstance(cursor.get(key), list) and cursor[key]:
            cursor[key][0] = value
    elif isinstance(cursor, dict):
        cursor[last] = value
    return out


def _body_schema(op: Operation) -> tuple[str | None, SchemaNode | None]:
    if op.request_body is None or not op.request_body.content:
        return None, None
    media = sorted(op.request_body.content)[0]
    return media, op.request_body.content[media]


def _valid_body(op: Operation, seed: int) -> tuple[str | None, Any, SchemaNode | None]:
    import random

    media, schema = _body_schema(op)
    if schema is None:
        return None, None, None
    return media, generate_valid(schema, random.Random(seed)), schema


def _path_and_query(op: Operation, seed: int) -> tuple[dict[str, Any], dict[str, Any]]:
    import random

    rng = random.Random(seed)
    path_params = {
        p.name: generate_valid(p.schema_node, rng)
        for p in op.parameters
        if p.location.value == "path"
    }
    query = {
        p.name: generate_valid(p.schema_node, rng)
        for p in op.parameters
        if p.location.value == "query"
    }
    return path_params, query


def _fits(schema: SchemaNode, text: str) -> bool:
    """Whether a string still satisfies the schema's length bounds.

    A case that violates the declared contract is not testing what this
    generator is for -- a service rejecting an over-long string is behaving
    correctly, and reporting it as a unicode-handling failure would be a false
    positive with a misleading name.
    """
    if schema.max_length is not None and len(text) > schema.max_length:
        return False
    return not (schema.min_length is not None and len(text) < schema.min_length)


# ------------------------------------------------------------------- unicode

#: Text that is entirely valid and routinely breaks naive handling. Each entry
#: is (label, value); the labels end up in the case description, so a failure
#: says which property of the input broke the service.
UNICODE_SAMPLES: list[tuple[str, str]] = [
    # Built from codepoints rather than written as literals. The whole point
    # of this table is that the characters are invisible or easily confused,
    # which makes a literal one indistinguishable from a typo in review and
    # vulnerable to a re-encoding of the file. chr() says exactly what is
    # meant and survives any editor.
    ("combining acute (NFD)", "e" + chr(0x0301) + "cole"),
    ("precomposed (NFC)", chr(0x00E9) + "cole"),
    ("zero-width joiner emoji", chr(0x1F469) + chr(0x200D) + chr(0x1F4BB)),
    ("astral plane", chr(0x1F600) + chr(0x1F680)),
    ("right-to-left override", "abc" + chr(0x202E) + "def"),
    ("zero-width space", "a" + chr(0x200B) + "b"),
    ("non-breaking space", "a" + chr(0x00A0) + "b"),
    ("Turkish dotless i", chr(0x0131) + "stanbul"),
    ("CJK", chr(0x6F22) + chr(0x5B57)),
    ("control picture", "a" + chr(0x2401) + "b"),
]


class UnicodeGenerator:
    """Valid but awkward text in every string field.

    These are positive cases. A service that 500s on an emoji, or silently
    normalizes NFD to NFC and then fails its own length check, has a bug --
    asserting 4xx here would be asserting the bug is correct behaviour.
    """

    name = "unicode"

    def generate(self, op: Operation, seed: int) -> Iterable[dict[str, Any]]:
        path_params, query = _path_and_query(op, seed)
        media, body, schema = _valid_body(op, seed)
        cases: list[dict[str, Any]] = []

        for param in op.parameters:
            if param.location.value != "query" or param.schema_node is None:
                continue
            if param.schema_node.type != "string":
                continue
            for label, text in UNICODE_SAMPLES:
                if not _fits(param.schema_node, text):
                    continue
                cases.append(
                    GeneratedCase(
                        kind="positive",
                        description=f"query '{param.name}' with {label}",
                        path_params=path_params,
                        query={**query, param.name: text},
                    )
                )

        if schema is not None and body is not None:
            for dotted, field in _string_fields(schema):
                for label, text in UNICODE_SAMPLES:
                    if not _fits(field, text):
                        continue
                    cases.append(
                        GeneratedCase(
                            kind="positive",
                            description=f"body field '{dotted}' with {label}",
                            path_params=path_params,
                            query=query,
                            body=_set_at(body, dotted, text),
                            media=media,
                        )
                    )
        return cases


def normalization_pairs() -> list[tuple[str, str]]:
    """NFC/NFD pairs, for callers checking round-trip stability.

    Exposed because "did the service change my string" is a different question
    from "did the service accept it", and answering it needs both forms.
    """
    pairs = []
    for _, text in UNICODE_SAMPLES:
        nfc = unicodedata.normalize("NFC", text)
        nfd = unicodedata.normalize("NFD", text)
        if nfc != nfd:
            pairs.append((nfc, nfd))
    return pairs


# ------------------------------------------------------------------- nesting


class NestingGenerator:
    """Payloads nested past any reasonable depth.

    Negative: a service should reject these. The finding that matters is not
    the 4xx though -- it is a 5xx, a timeout, or a connection reset, which is
    a parser walking the structure without a depth limit. `_check_response`
    already flags 5xx whatever the case kind, so this generator's job is only
    to produce input deep enough to reach it.

    Depths climb rather than jumping straight to the maximum, because knowing
    a service dies at 64 and not at 32 is more useful than knowing it dies
    somewhere below 10,000.
    """

    name = "nesting"

    #: Past ~1000, JSON encoders in the harness itself start to struggle, and
    #: a case the tool cannot serialise is not a test of the service.
    DEPTHS: ClassVar[tuple[int, ...]] = (8, 32, 128, 512)

    def generate(self, op: Operation, seed: int) -> Iterable[dict[str, Any]]:
        media, schema = _body_schema(op)
        if schema is None:
            return []
        path_params, query = _path_and_query(op, seed)
        cases: list[dict[str, Any]] = []
        for depth in self.DEPTHS:
            nested: Any = "leaf"
            for _ in range(depth):
                nested = {"n": nested}
            cases.append(
                GeneratedCase(
                    kind="negative",
                    description=f"body nested {depth} levels deep",
                    path_params=path_params,
                    query=query,
                    body=nested,
                    media=media,
                )
            )
            array: Any = []
            for _ in range(depth):
                array = [array]
            cases.append(
                GeneratedCase(
                    kind="negative",
                    description=f"array nested {depth} levels deep",
                    path_params=path_params,
                    query=query,
                    body=array,
                    media=media,
                )
            )
        return cases


# ------------------------------------------------------------------- numeric


class NumericBoundaryGenerator:
    """Sweeps around declared numeric bounds.

    `generate_invalid` already produces an out-of-range value, but not the
    values that sit exactly on the boundary, and those are where off-by-one
    validators live. `exclusiveMinimum` and `multipleOf` are the two that get
    implemented wrong most often: a service that accepts its exclusive minimum
    is accepting a value its own contract forbids.
    """

    name = "numeric"

    def generate(self, op: Operation, seed: int) -> Iterable[dict[str, Any]]:
        path_params, query = _path_and_query(op, seed)
        media, body, schema = _valid_body(op, seed)
        cases: list[dict[str, Any]] = []

        for param in op.parameters:
            if param.location.value != "query" or param.schema_node is None:
                continue
            for kind, label, value in self._sweep(param.schema_node):
                cases.append(
                    GeneratedCase(
                        kind=kind,
                        description=f"query '{param.name}' {label}",
                        path_params=path_params,
                        query={**query, param.name: value},
                    )
                )

        if schema is not None and body is not None:
            for dotted, field in _numeric_fields(schema):
                for kind, label, value in self._sweep(field):
                    cases.append(
                        GeneratedCase(
                            kind=kind,
                            description=f"body field '{dotted}' {label}",
                            path_params=path_params,
                            query=query,
                            body=_set_at(body, dotted, value),
                            media=media,
                        )
                    )
        return cases

    def _sweep(self, schema: SchemaNode) -> list[tuple[str, str, Any]]:
        """(kind, label, value) triples for one numeric schema."""
        if schema.type not in ("integer", "number"):
            return []
        step = 1 if schema.type == "integer" else 0.000001
        out: list[tuple[str, str, Any]] = []

        if schema.minimum is not None:
            out.append(("positive", f"at minimum ({schema.minimum})", schema.minimum))
            out.append(
                ("negative", f"just below minimum ({schema.minimum})", schema.minimum - step)
            )
        if schema.exclusive_minimum is not None:
            # The value the contract forbids and implementations accept.
            out.append(
                (
                    "negative",
                    f"at exclusive minimum ({schema.exclusive_minimum}), which is excluded",
                    schema.exclusive_minimum,
                )
            )
            out.append(
                (
                    "positive",
                    f"just above exclusive minimum ({schema.exclusive_minimum})",
                    schema.exclusive_minimum + step,
                )
            )
        if schema.maximum is not None:
            out.append(("positive", f"at maximum ({schema.maximum})", schema.maximum))
            out.append(
                ("negative", f"just above maximum ({schema.maximum})", schema.maximum + step)
            )
        if schema.exclusive_maximum is not None:
            out.append(
                (
                    "negative",
                    f"at exclusive maximum ({schema.exclusive_maximum}), which is excluded",
                    schema.exclusive_maximum,
                )
            )
        if schema.multiple_of:
            factor = schema.multiple_of
            base = schema.minimum if schema.minimum is not None else 0
            aligned = (int(base / factor) + 1) * factor
            out.append(("positive", f"a multiple of {factor}", aligned))
            out.append(("negative", f"not a multiple of {factor}", aligned + factor / 2))
        return out


# ------------------------------------------------------------- header safety


class HeaderSafetyGenerator:
    """Defensive header-handling checks.

    Untrusted bytes in a header value: CR, LF, a null byte, an over-long
    value. The question is whether the service rejects or sanitizes them, not
    how to exploit anything -- there is no payload library here and there is
    not meant to be. A request-smuggling payload is not needed to learn that a
    header value is passed through unfiltered, and shipping one would make
    this tool something a security team has to review before installing.

    Note that httpx refuses to *send* a raw CR/LF in a header, which is
    correct of it. The encoded forms below are what actually travels, and
    reaching a service that decodes them is the thing worth knowing.
    """

    name = "header-safety"

    UNSAFE: ClassVar[list[tuple[str, str]]] = [
        ("percent-encoded CRLF", "value%0d%0aX-Injected:%20yes"),
        ("literal backslash-n", "value\\r\\nX-Injected: yes"),
        ("null byte, encoded", "value%00tail"),
        ("very long value", "v" * 8192),
        ("leading whitespace", "   value"),
        ("high-bit latin-1", "value" + chr(0x00FF) + "tail"),
    ]

    #: Header values must be encodable by the HTTP transport, and anything
    #: above latin-1 is not. A case the tool cannot send teaches nothing about
    #: the service, so U+2028 and friends belong in a body or query, not here
    #: -- an earlier version put one here and made the whole run unsendable.
    MAX_ORDINAL = 0xFF

    def generate(self, op: Operation, seed: int) -> Iterable[dict[str, Any]]:
        path_params, query = _path_and_query(op, seed)
        declared = [p for p in op.parameters if p.location.value == "header"]
        targets = [p.name for p in declared] or ["X-Apiverity-Probe"]
        cases: list[dict[str, Any]] = []
        for header in targets:
            for label, value in self.UNSAFE:
                if any(ord(ch) > self.MAX_ORDINAL for ch in value):
                    continue
                cases.append(
                    GeneratedCase(
                        kind="negative",
                        description=f"header '{header}' with {label}",
                        path_params=path_params,
                        query=query,
                        headers={header: value},
                    )
                )
        return cases


# ------------------------------------------------------------------ dispatch

BUILTIN_GENERATORS: dict[str, CaseGenerator] = {
    generator.name: generator
    for generator in (
        UnicodeGenerator(),
        NestingGenerator(),
        NumericBoundaryGenerator(),
        HeaderSafetyGenerator(),
    )
}


def load_generators(selected: list[str] | None = None) -> dict[str, CaseGenerator]:
    """Built-in generators plus anything registered under `apiverity.generators`.

    A third-party entry point wins over a built-in of the same name, so a
    strategy can be replaced without forking. Entry points that fail to load
    are skipped rather than aborting the run: one broken plugin in the
    environment should not stop the built-in strategies from working.
    """
    available: dict[str, CaseGenerator] = dict(BUILTIN_GENERATORS)

    try:
        from apiverity.plugins.registry import load_group

        for name, factory in load_group("apiverity.generators"):
            try:
                candidate = factory() if callable(factory) else factory
            except Exception:  # pragma: no cover - depends on installed plugins
                continue
            if hasattr(candidate, "generate") and hasattr(candidate, "name"):
                available[str(candidate.name)] = candidate
            elif callable(candidate) and name not in available:
                # The historical shape: a plain callable registered under
                # `schema-cases`. Kept working, but it operates on a whole
                # service rather than an operation, so it is not a
                # CaseGenerator and `build_cases` handles it separately.
                continue
    except Exception:  # pragma: no cover - registry is optional at runtime
        pass

    if selected is None:
        return available
    missing = [name for name in selected if name not in available]
    if missing:
        raise ValueError(
            f"unknown generator(s): {', '.join(sorted(missing))} "
            f"(available: {', '.join(sorted(available))})"
        )
    return {name: available[name] for name in selected}
