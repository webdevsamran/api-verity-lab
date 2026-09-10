"""A contract inferred from traffic, labelled as inferred.

The most common answer to "run the contract gate on this API" is "we do not
have a contract". Every capability in this project starts from a document that
does not exist, and writing one by hand for a service with ninety endpoints is
the reason it never gets written.

Recorded traffic is the next best evidence. This reads a HAR and produces an
OpenAPI 3.1 document describing what was actually observed -- which is a
different thing from what the API supports, and the document says so on every
line where it matters.

Three places this could lie, and does not
-----------------------------------------
**Required.** A field present in all four observed responses is not a field the
API guarantees. Every schema carries `x-apiverity-samples`, and a property is
marked required only when it appeared in every sample *and* there were at least
`MIN_SAMPLES_FOR_REQUIRED` of them. Below that the property is optional and the
count is there for a reader to disagree with.

**Enums.** Three responses with `status: "open"` do not make `open` the only
value. Enum inference is off unless asked for, and even then needs a threshold,
because a fabricated constraint is worse than an absent one: it turns a valid
request into a reported violation.

**Path parameters.** `/users/42` and `/users/43` are one operation;
`/users/me` and `/users/settings` are two. Collapsing too eagerly invents an
operation nobody serves, and collapsing too late produces a hundred. A segment
becomes a parameter only when the sibling values at that position either all
look like identifiers or there are enough of them that a literal set is not
credible -- and the document records which rule fired.

The output is a draft. It is titled as one, its description says how many
requests it came from and over what window, and `x-apiverity-inferred` marks
the document so a later reader cannot mistake it for something a person wrote.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

#: Below this, "present in every sample" is a coincidence rather than a rule.
MIN_SAMPLES_FOR_REQUIRED = 3

#: Distinct sibling values above which a literal path segment is not credible.
MIN_SIBLINGS_FOR_PARAMETER = 4

#: With fewer samples than this, an enum is a guess.
MIN_SAMPLES_FOR_ENUM = 8

#: Above this many distinct values, it was never an enum.
MAX_ENUM_VALUES = 12

_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_INTEGER = re.compile(r"^\d+$")
_HEX = re.compile(r"^[0-9a-fA-F]{16,}$")
_PREFIXED = re.compile(r"^[a-z]{2,10}_[A-Za-z0-9]{8,}$")


def looks_like_identifier(segment: str) -> str | None:
    """The kind of identifier this segment is, or None if it reads as a word."""
    if _UUID.match(segment):
        return "uuid"
    if _INTEGER.match(segment):
        return "integer"
    if _HEX.match(segment):
        return "hex"
    if _PREFIXED.match(segment):
        return "prefixed id"
    return None


def _parameter_name(parent: str | None, taken: set[str]) -> str:
    """`/users/42` -> `userId`. Predictable beats clever."""
    base = "id"
    if (parent and parent.isidentifier()) or (parent and re.fullmatch(r"[A-Za-z][\w-]*", parent)):
        stem = parent[:-1] if parent.endswith("s") and len(parent) > 2 else parent
        base = re.sub(r"[^A-Za-z0-9]", "", stem) + "Id"
    name, index = base, 2
    while name in taken:
        name, index = f"{base}{index}", index + 1
    return name


@dataclass
class _Node:
    """One segment position in the observed path tree."""

    children: dict[str, _Node] = field(default_factory=dict)
    terminal: int = 0


def _tree(paths: list[str]) -> _Node:
    root = _Node()
    for path in paths:
        node = root
        for segment in [s for s in path.split("/") if s]:
            node = node.children.setdefault(segment, _Node())
        node.terminal += 1
    return root


@dataclass
class Templating:
    """A concrete path and the template it was folded into."""

    template: str
    reason: str


def infer_templates(paths: list[str]) -> dict[str, Templating]:
    """Fold concrete paths into templates, recording why each fold happened."""
    root = _tree(paths)
    out: dict[str, Templating] = {}

    for path in paths:
        segments = [s for s in path.split("/") if s]
        node = root
        rendered: list[str] = []
        reasons: list[str] = []
        taken: set[str] = set()

        for index, segment in enumerate(segments):
            siblings = list(node.children)
            kinds = {looks_like_identifier(s) for s in siblings}
            identifier_kind = looks_like_identifier(segment)

            collapse = False
            reason = ""
            if len(siblings) > 1 and identifier_kind and None not in kinds:
                collapse = True
                reason = f"every sibling of {segment!r} looks like a {identifier_kind}"
            elif len(siblings) >= MIN_SIBLINGS_FOR_PARAMETER and identifier_kind:
                collapse = True
                reason = (
                    f"{len(siblings)} distinct values at this position; a literal set that "
                    "large is not credible"
                )

            if collapse:
                name = _parameter_name(segments[index - 1] if index else None, taken)
                taken.add(name)
                rendered.append("{" + name + "}")
                reasons.append(reason)
            else:
                rendered.append(segment)

            node = node.children[segment]

        template = "/" + "/".join(rendered) if rendered else "/"
        out[path] = Templating(
            template=template,
            reason="; ".join(reasons) or "every segment was a stable literal",
        )
    return out


@dataclass
class _Observed:
    """What the samples said about one position in a JSON document."""

    types: set[str] = field(default_factory=set)
    seen: int = 0
    values: list[Any] = field(default_factory=list)
    properties: dict[str, _Observed] = field(default_factory=dict)
    items: _Observed | None = None
    formats: set[str] = field(default_factory=set)


_FORMAT_HINTS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("uuid", _UUID),
    ("date-time", re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}")),
    ("date", re.compile(r"^\d{4}-\d{2}-\d{2}$")),
    ("email", re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")),
    ("uri", re.compile(r"^https?://\S+$")),
)


def _json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "object"


def observe(node: _Observed, value: Any) -> None:
    """Fold one sample into an accumulating description."""
    node.seen += 1
    kind = _json_type(value)
    node.types.add(kind)

    if kind == "string":
        if len(node.values) < 64:
            node.values.append(value)
        for name, pattern in _FORMAT_HINTS:
            if pattern.match(value):
                node.formats.add(name)
                break
    elif kind in ("integer", "number", "boolean") and len(node.values) < 64:
        node.values.append(value)
    elif kind == "object":
        for key, child in value.items():
            observe(node.properties.setdefault(str(key), _Observed()), child)
    elif kind == "array":
        for item in value:
            if node.items is None:
                node.items = _Observed()
            observe(node.items, item)


def to_schema(node: _Observed, *, infer_enums: bool = False) -> dict[str, Any]:
    """A JSON Schema for what was observed, with the evidence attached."""
    concrete = sorted(node.types - {"null"})
    schema: dict[str, Any] = {}
    if len(concrete) == 1:
        schema["type"] = concrete[0]
    elif concrete:
        # Two shapes for one field is a fact about the API, not a problem to
        # smooth over. `type` as a list says so; picking one would not.
        schema["type"] = concrete
    if "null" in node.types and concrete:
        schema["type"] = [
            *(schema["type"] if isinstance(schema["type"], list) else [schema["type"]]),
            "null",
        ]

    if node.formats and len(node.formats) == 1:
        schema["format"] = next(iter(node.formats))

    if node.properties:
        schema["properties"] = {
            name: to_schema(child, infer_enums=infer_enums)
            for name, child in sorted(node.properties.items())
        }
        # Required needs both: present every time, and enough times that
        # "every time" means something.
        required = sorted(
            name
            for name, child in node.properties.items()
            if child.seen == node.seen and node.seen >= MIN_SAMPLES_FOR_REQUIRED
        )
        if required:
            schema["required"] = required

    if node.items is not None:
        schema["items"] = to_schema(node.items, infer_enums=infer_enums)

    if (
        infer_enums
        and schema.get("type") == "string"
        and node.seen >= MIN_SAMPLES_FOR_ENUM
        and node.values
    ):
        distinct = sorted({str(v) for v in node.values})
        if len(distinct) <= MAX_ENUM_VALUES:
            schema["enum"] = distinct

    schema["x-apiverity-samples"] = node.seen
    return schema


@dataclass
class InferredOperation:
    method: str
    template: str
    statuses: dict[int, _Observed] = field(default_factory=dict)
    requests: int = 0
    mime: str = "application/json"
    templating_reason: str = ""


def infer(
    entries: list[dict[str, Any]],
    *,
    title: str = "Inferred API",
    version: str = "0.0.0-inferred",
    infer_enums: bool = False,
    request_noun: str = "recorded",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """An OpenAPI 3.1 document, and a record of how it was derived.

    `request_noun` is the word the document uses for where its requests came
    from. "recorded" is a claim about a HAR: those requests happened, in that
    order. A Postman collection's requests were *saved* by somebody, possibly
    years ago and possibly by hand, and calling them recorded would assert an
    observation nobody made -- in the one sentence of the draft a reader is
    most likely to quote.
    """
    from urllib.parse import urlparse

    usable = [
        entry
        for entry in entries
        if isinstance(entry.get("method"), str) and isinstance(entry.get("url"), str)
    ]
    paths = [urlparse(str(entry["url"])).path or "/" for entry in usable]
    templates = infer_templates(paths)

    operations: dict[tuple[str, str], InferredOperation] = {}
    stamps: list[str] = []
    bodies_seen = 0
    bodies_absent = 0

    for entry, path in zip(usable, paths, strict=True):
        method = str(entry["method"]).upper()
        templating = templates[path]
        key = (method, templating.template)
        operation = operations.setdefault(
            key,
            InferredOperation(
                method=method,
                template=templating.template,
                templating_reason=templating.reason,
            ),
        )
        operation.requests += 1

        started = entry.get("started_at")
        if isinstance(started, str) and started:
            stamps.append(started)

        status = entry.get("status")
        if not isinstance(status, int):
            continue
        body = entry.get("response_body")
        if body is None:
            bodies_absent += 1
            operation.statuses.setdefault(status, _Observed())
            continue
        bodies_seen += 1
        observe(operation.statuses.setdefault(status, _Observed()), body)

    document = _document(
        operations,
        title=title,
        version=version,
        infer_enums=infer_enums,
        requests=len(usable),
        window=(min(stamps), max(stamps)) if stamps else None,
        bodies_seen=bodies_seen,
        request_noun=request_noun,
    )
    provenance = {
        "requests_read": len(entries),
        "requests_usable": len(usable),
        "operations": len(operations),
        "bodies_observed": bodies_seen,
        "bodies_absent": bodies_absent,
        "window": {"first": min(stamps), "last": max(stamps)} if stamps else None,
        "templating": {
            operation.template: operation.templating_reason for operation in operations.values()
        },
        "enums_inferred": infer_enums,
    }
    return document, provenance


def _document(
    operations: dict[tuple[str, str], InferredOperation],
    *,
    title: str,
    version: str,
    infer_enums: bool,
    requests: int,
    window: tuple[str, str] | None,
    bodies_seen: int,
    request_noun: str,
) -> dict[str, Any]:
    paths: dict[str, dict[str, Any]] = defaultdict(dict)
    for (method, template), operation in sorted(operations.items()):
        responses: dict[str, Any] = {}
        for status, observed in sorted(operation.statuses.items()):
            entry: dict[str, Any] = {
                "description": f"Observed {observed.seen} time(s)."
                if observed.seen
                else "Observed, with no response body recorded."
            }
            if observed.seen:
                entry["content"] = {
                    operation.mime: {"schema": to_schema(observed, infer_enums=infer_enums)}
                }
            responses[str(status)] = entry

        paths[template][method.lower()] = {
            "summary": f"{method} {template}",
            "description": (
                f"Inferred from {operation.requests} {request_noun} request(s). "
                f"Path templating: {operation.templating_reason}."
            ),
            "responses": responses or {"default": {"description": "No status was recorded."}},
            "x-apiverity-requests": operation.requests,
        }

    span = f" between {window[0]} and {window[1]}" if window else ""
    return {
        "openapi": "3.1.0",
        "info": {
            "title": f"{title} (inferred draft)",
            "version": version,
            "description": (
                f"Inferred by apiverity from {requests} {request_noun} request(s){span}. "
                f"{bodies_seen} response body/bodies were available to describe.\n\n"
                "This describes what was observed, which is not what the API supports. "
                "Absent operations were not exercised; a property marked required was "
                "present in every sample and every sample is a small number. Each schema "
                "carries `x-apiverity-samples` so a reader can weigh it, and nothing here "
                "should be published as a contract without being read by someone who "
                "knows the service."
            ),
        },
        # Marks the document at the top level, so a tool or a person reading it
        # later cannot mistake it for something a human authored.
        "x-apiverity-inferred": True,
        "paths": dict(sorted(paths.items())),
    }


__all__ = [
    "MAX_ENUM_VALUES",
    "MIN_SAMPLES_FOR_ENUM",
    "MIN_SAMPLES_FOR_REQUIRED",
    "MIN_SIBLINGS_FOR_PARAMETER",
    "Templating",
    "infer",
    "infer_templates",
    "looks_like_identifier",
    "observe",
    "to_schema",
]
