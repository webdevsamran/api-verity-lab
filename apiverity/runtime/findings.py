"""One finding shape across every way this tool detects drift.

`apiverity drift` has four paths -- a live HTTP probe, a recorded HAR corpus, a
GraphQL introspection compare, and an MCP server -- and each returned a report
whose findings had a different set of fields. A corpus finding carried
`occurrences` and `observations`; an MCP finding carried `tool`, `change_id`
and `source_rule_id`; the HTTP one carried neither. Same command, same flag,
four incompatible payloads, and a consumer had to work out which mode had run
before it could read anything.

Worse, none of them was covered by the published contract. `schemas/
result-v1.schema.json` constrains a top-level `findings` array; every drift
mode nested its findings under `report`, so the one place the shape was
actually written down did not apply to the command that varied most.

So the drift artifact now carries a top-level `findings` array in the
published shape, alongside the mode-specific `report` it always had. Additive
on purpose: a consumer reading `report.drift.findings` today keeps working,
and one reading `findings` works against all four modes and against every
other command in the tool.

The per-mode extras are not thrown away. They become documented optional
fields -- `occurrences`, `first_seen`, `tool`, `change_id` -- so a corpus
finding still says it happened four hundred times and an MCP finding still
names the rule that classified it. A field that is absent means the mode
cannot establish it, which is different from zero, and is why none of them
gets a default.
"""

from __future__ import annotations

from typing import Any

#: Optional fields a mode may contribute, in the order they are written.
#: Absent means "this mode cannot establish it" -- never zero, never "".
_OPTIONAL = (
    "operation_key",
    "tool",
    "occurrences",
    "observations",
    "frequency",
    "first_seen",
    "last_seen",
    "examples",
    "change_id",
    "source_rule_id",
)


def _value(finding: Any, name: str) -> Any:
    if isinstance(finding, dict):
        return finding.get(name)
    return getattr(finding, name, None)


def unify(finding: Any) -> dict[str, Any]:
    """One drift finding, in the shape `schemas/result-v1` publishes."""
    out: dict[str, Any] = {
        "rule_id": str(_value(finding, "rule_id") or ""),
        "severity": str(_value(finding, "severity") or "WARN").upper(),
        "message": str(_value(finding, "message") or ""),
    }
    for name in _OPTIONAL:
        value = _value(finding, name)
        if value is None or value == [] or value == "":
            continue
        if name == "frequency":
            out[name] = round(float(value), 4)
        else:
            out[name] = value
    return out


def unify_all(findings: list[Any]) -> list[dict[str, Any]]:
    return [unify(finding) for finding in findings]


__all__ = ["unify", "unify_all"]
