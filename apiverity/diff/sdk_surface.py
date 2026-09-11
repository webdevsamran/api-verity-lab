"""Changes that are wire-compatible and break every generated client.

A contract diff asks what happens to bytes on a socket. A generated SDK is a
second contract, derived from the first by naming conventions, and it can break
while the wire stays identical.

Rename an `operationId` from `getUser` to `fetchUser`. Nothing about the
request or the response moves; every rule in the catalogue is silent -- and
`apiverity diff` reports **no change at all**, because `operation_id` is not
compared. Every generated client's `client.getUser()` stops compiling.

## What this claims, and what it does not

Nothing here is tested against any particular generator. Each rule names the
*convention* it depends on, from :data:`CONVENTIONS`, and applies only when
that convention is in force:

* `operation-id-names` -- method names derive from `operationId`.
* `tag-namespaces` -- operations are grouped into a class or namespace per tag.
* `title-model-names` -- model classes are named after a schema's `title` or
  its component name.
* `closed-enums` -- an enum becomes a closed type; an unknown value is a
  deserialization failure or a non-exhaustive match, not an unrecognised
  string.
* `positional-parameters` -- required parameters become positional arguments in
  declaration order.

These are what generators *do*, stated as assumptions rather than asserted as
facts about a tool this project has not run. A team whose generator does not
follow one turns it off, and the findings that depend on it disappear --
including from the summary, so a filtered run never reports a total that
includes what it did not check.

## What is deliberately not here

A response field becoming nullable. `BRK-RESP-NULLABLE-ADDED` reaches the same
verdict about the same change -- consumers that did not expect a null break --
and a second rule saying it in generator vocabulary is one finding printed
twice.

`SDK-ENUM-VALUE-ADDED` is kept beside `BRK-ENUM-WIDENED` for the opposite
reason: those two *disagree*. The wire rule says additive and safe, which it
is, and the SDK rule says breaking for a generated closed type, which it also
is. That disagreement is the whole point of this family.

A severity here is never ERROR. These are real and they are not wire-breaking,
and a rule that outranks "you deleted a required response field" because a
class got renamed is a rule somebody disables along with everything near it.
"""

from __future__ import annotations

from typing import Any

from apiverity.core.model import Finding, Operation, SchemaNode, Service, Severity

#: Convention -> what a generator has to do for the rules keyed on it to apply.
CONVENTIONS: dict[str, str] = {
    "operation-id-names": "method names are derived from `operationId`",
    "tag-namespaces": "operations are grouped into a namespace per tag",
    "title-model-names": "model class names come from a schema's title",
    "closed-enums": "enums become closed types that reject unknown values",
    "positional-parameters": "required parameters become positional arguments",
}

#: Rule -> the convention it depends on. Every rule below is in here; a test
#: asserts the two agree, because a rule that applied unconditionally would be
#: making a claim about generators this project has not run.
RULE_CONVENTIONS: dict[str, str] = {
    "SDK-OPERATION-ID-CHANGED": "operation-id-names",
    "SDK-OPERATION-ID-REMOVED": "operation-id-names",
    "SDK-OPERATION-ID-ADDED": "operation-id-names",
    "SDK-TAG-NAMESPACE-CHANGED": "tag-namespaces",
    "SDK-MODEL-NAME-CHANGED": "title-model-names",
    "SDK-ENUM-VALUE-ADDED": "closed-enums",
    "SDK-PARAMETER-ORDER-CHANGED": "positional-parameters",
}


def _tag(op: Operation) -> str | None:
    """The tag a generator would group this operation under.

    The first one. Generators that group by tag pick one, and the first is
    what the common ones pick; a set comparison would report a reordering that
    changes nothing and miss one that changes everything.
    """
    return op.tags[0] if op.tags else None


def _required_names(op: Operation) -> list[str]:
    return [p.name for p in op.parameters if p.required]


def _walk(
    schema: SchemaNode | None, prefix: str = "", depth: int = 0
) -> list[tuple[str, SchemaNode]]:
    """Every schema in a tree, with a dotted path.

    Depth-bounded: a self-referential contract (a `Node` with `children` of
    `Node`) resolves into an infinite tree, and a generator only ever emits one
    class per model anyway.
    """
    if schema is None or depth > 6:
        return []
    out: list[tuple[str, SchemaNode]] = [(prefix, schema)]
    for name, child in schema.properties.items():
        out.extend(_walk(child, f"{prefix}.{name}" if prefix else name, depth + 1))
    if schema.items is not None:
        out.extend(_walk(schema.items, f"{prefix}[]" if prefix else "[]", depth + 1))
    return out


def _response_schemas(op: Operation) -> dict[str, SchemaNode]:
    """`status:media:path` -> schema, for every success response."""
    out: dict[str, SchemaNode] = {}
    for response in op.responses:
        if not response.status.startswith(("2", "default")):
            continue
        for media, schema in response.content.items():
            for path, node in _walk(schema):
                out[f"{response.status}:{media}:{path}"] = node
    return out


def _enum(schema: SchemaNode) -> list[Any]:
    return list(schema.enum or [])


class SdkSurfaceAnalyzer:
    """Wire-compatible changes that move a generated client's surface."""

    def __init__(self, old: Service, new: Service, conventions: set[str]) -> None:
        self.old = old
        self.new = new
        self.conventions = conventions

    def _on(self, rule_id: str) -> bool:
        return RULE_CONVENTIONS[rule_id] in self.conventions

    def _finding(
        self, rule_id: str, message: str, key: str | None, hint: str, severity: Severity
    ) -> Finding:
        convention = RULE_CONVENTIONS[rule_id]
        return Finding(
            rule_id=rule_id,
            severity=severity,
            message=message,
            operation_key=key,
            hint=hint,
            # The assumption is carried on the finding, not only in the docs. A
            # reader who disagrees with it can see which one to switch off.
            metadata={"convention": convention, "assumes": CONVENTIONS[convention]},
        )

    def analyze(self) -> list[Finding]:
        out: list[Finding] = []
        for key in self.old.operation_keys():
            old_op = self.old.find_operation(key)
            new_op = self.new.find_operation(key)
            if old_op is None or new_op is None:
                # A removed operation is already the loudest finding there is.
                continue
            self._operation_id(out, key, old_op, new_op)
            self._tags(out, key, old_op, new_op)
            self._parameter_order(out, key, old_op, new_op)
            self._response_types(out, key, old_op, new_op)
        return out

    # ------------------------------------------------------------------ names

    def _operation_id(self, out: list[Finding], key: str, old: Operation, new: Operation) -> None:
        if not self._on("SDK-OPERATION-ID-CHANGED"):
            return
        before, after = old.operation_id, new.operation_id
        if before == after:
            return
        if before and after:
            out.append(
                self._finding(
                    "SDK-OPERATION-ID-CHANGED",
                    f"'{key}' renamed its operationId from '{before}' to '{after}'. The "
                    "request and the response are unchanged, so no wire-level rule "
                    "reports this -- and every generated client's "
                    f"`{before}(...)` call site stops compiling",
                    key,
                    f"keep '{before}' and change the summary instead, or ship the "
                    "rename as a major version of the SDK",
                    Severity.WARN,
                )
            )
        elif before and not after:
            out.append(
                self._finding(
                    "SDK-OPERATION-ID-REMOVED",
                    f"'{key}' dropped its operationId '{before}'. Generators fall back "
                    "to a name derived from the method and path, so the method is not "
                    "removed -- it is renamed to something the contract no longer states",
                    key,
                    f"restore `operationId: {before}`",
                    Severity.WARN,
                )
            )
        elif after and not before:
            out.append(
                self._finding(
                    "SDK-OPERATION-ID-ADDED",
                    f"'{key}' gained an operationId '{after}'. Clients generated before "
                    "this used a name derived from the method and path, and that name "
                    "is now replaced",
                    key,
                    "expected when adopting operationIds; ship it as a major SDK version",
                    Severity.INFO,
                )
            )

    def _tags(self, out: list[Finding], key: str, old: Operation, new: Operation) -> None:
        if not self._on("SDK-TAG-NAMESPACE-CHANGED"):
            return
        before, after = _tag(old), _tag(new)
        if before == after:
            return
        out.append(
            self._finding(
                "SDK-TAG-NAMESPACE-CHANGED",
                f"'{key}' moved from tag '{before or '(none)'}' to '{after or '(none)'}'. "
                "Where a generator groups by tag, the operation moves to a different "
                "client class: `client." + (before or "default") + "." + "…` becomes "
                "`client." + (after or "default") + ".…`",
                key,
                "add the new tag alongside the old one rather than replacing it",
                Severity.WARN,
            )
        )

    def _parameter_order(
        self, out: list[Finding], key: str, old: Operation, new: Operation
    ) -> None:
        if not self._on("SDK-PARAMETER-ORDER-CHANGED"):
            return
        before, after = _required_names(old), _required_names(new)
        # Only a reordering. An added or removed required parameter is a
        # wire-level change that is already reported, and reporting it a second
        # time here would make this family look noisier than it is.
        if before == after or sorted(before) != sorted(after) or len(before) < 2:
            return
        out.append(
            self._finding(
                "SDK-PARAMETER-ORDER-CHANGED",
                f"'{key}' reordered its required parameters from {before} to {after}. "
                "Where a generator emits them positionally, existing call sites keep "
                "compiling and start passing the arguments the other way round",
                key,
                "restore the declaration order; nothing about the request depends on it",
                # The only WARN here that is not a compile error. It is a silent
                # wrong-value bug, which is worse, and the severity does not
                # say so because severity is about the gate, not about dread.
                Severity.WARN,
            )
        )

    # ------------------------------------------------------------------ types

    def _response_types(self, out: list[Finding], key: str, old: Operation, new: Operation) -> None:
        before = _response_schemas(old)
        after = _response_schemas(new)
        for path, new_schema in after.items():
            old_schema = before.get(path)
            if old_schema is None:
                continue
            where = path.split(":", 2)[-1] or "(body)"

            if (
                self._on("SDK-MODEL-NAME-CHANGED")
                and old_schema.title != new_schema.title
                # Only a rename. A title appearing or disappearing changes the
                # generated name from a fallback, which is worth less than the
                # noise it would add to every contract that adds a title.
                and old_schema.title
                and new_schema.title
            ):
                out.append(
                    self._finding(
                        "SDK-MODEL-NAME-CHANGED",
                        f"'{key}' response {where} changed its schema title from "
                        f"'{old_schema.title}' to '{new_schema.title}'. The shape is "
                        "unchanged; the generated class is renamed",
                        key,
                        "keep the title and change the description instead",
                        Severity.INFO,
                    )
                )

            if self._on("SDK-ENUM-VALUE-ADDED"):
                added = [v for v in _enum(new_schema) if v not in _enum(old_schema)]
                if added and _enum(old_schema):
                    out.append(
                        self._finding(
                            "SDK-ENUM-VALUE-ADDED",
                            f"'{key}' response {where} added enum value(s) "
                            f"{added!r}. A client may now receive a value its generated "
                            "type does not have a member for -- a deserialization "
                            "failure, or a match that is no longer exhaustive",
                            key,
                            "roll this out behind a version, or document the field as "
                            "open by removing the enum and constraining it in prose",
                            Severity.WARN,
                        )
                    )


def analyze_sdk_surface(
    old: Service, new: Service, conventions: set[str] | None = None
) -> list[Finding]:
    """SDK-surface findings between two revisions of one contract.

    `conventions` defaults to all of them. Narrowing it removes the rules that
    depend on the ones left out -- they are not downgraded or hidden, they do
    not run.
    """
    active = set(CONVENTIONS) if conventions is None else set(conventions)
    unknown = active - set(CONVENTIONS)
    if unknown:
        raise ValueError(
            f"unknown SDK convention(s): {sorted(unknown)}. Known: {sorted(CONVENTIONS)}"
        )
    if not active:
        return []
    return SdkSurfaceAnalyzer(old, new, active).analyze()


__all__ = [
    "CONVENTIONS",
    "RULE_CONVENTIONS",
    "SdkSurfaceAnalyzer",
    "analyze_sdk_surface",
]
