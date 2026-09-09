"""The tool surface this server exposes, and its handlers.

`docs/mcp-exposure.md` decided the shape of this before any of it was built:
a deliberately small read-only subset, and an explicit list of what is *not*
exposed and why. That decision is reused here rather than re-litigated.

Two implementation rules, both of which look like style and are not.

**Handlers never touch the CLI's emit path.** `cli/commands/common.py` carries
four process globals -- `_LAST_SPEC`, `_LAST_TARGET`, `_LAST_SEED`,
`_LAST_PROTOCOL` -- set as a side effect of `_load` and read by `_emit`. That
is fine in a one-shot process and wrong the moment one process serves many
calls: a `rules` request, which loads no contract, would inherit the previous
caller's spec provenance and report it as its own. `_load` also calls
`sys.exit` on a bad path, which would take the server down. And `_emit` prints
to stdout, which *is* the JSON-RPC frame stream. So handlers call
`core.artifact.enrich` directly with per-call arguments.

**Errors never carry `str(exc)`.** Loader failures embed the full resolved
path, so echoing them would disclose the operator's directory layout to the
model on every typo.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from apiverity.core.artifact import enrich
from apiverity.mcp.paths import PathRefused, relative_label, resolve_within
from apiverity.specs import UnrecognizedSpecError

#: Version of the *tool surface*, not of the package.
#:
#: These inputs are a public contract with the same never-change-a-meaning rule
#: as the exit codes. Removing a tool or changing what an argument means
#: increments this; while the package is 0.x it also bumps the package minor.
#: It is deliberately not tied to the package version, which moves for reasons
#: that have nothing to do with this surface.
MCP_TOOLS_SCHEMA_VERSION = 1

_SPEC_ARG = {
    "type": "string",
    "description": "Path to a contract, relative to the server's configured root.",
}


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[Path, dict[str, Any]], dict[str, Any]]

    def manifest_entry(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
            # Every tool here is a pure function of files on disk. The hints are
            # true, and they are also the reason this surface was chosen.
            "annotations": {
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
        }


def _load_contract(root: Path, spec: str) -> tuple[Any, list[Any], Any, Path]:
    """Load a contract from a confined path.

    The *resolved* path is what reaches `detect_and_load`, because the loader
    re-reads the caller's string; see `paths.py`.
    """
    from apiverity.specs.loader import detect_and_load

    resolved = resolve_within(root, spec)
    try:
        service, findings, plugin = detect_and_load(str(resolved))
    except FileNotFoundError as exc:
        raise PathRefused(f"no such file: {relative_label(root, resolved)}") from exc
    except UnrecognizedSpecError as exc:
        raise PathRefused(
            f"{relative_label(root, resolved)} is not a contract in any recognized format"
        ) from exc
    except (OSError, ValueError) as exc:
        raise PathRefused(
            f"{relative_label(root, resolved)} could not be read as a contract"
        ) from exc
    return service, findings, plugin, resolved


def _artifact(command: str, payload: dict[str, Any], **meta: Any) -> dict[str, Any]:
    """Stamp a payload the way the CLI does, without the CLI's globals."""
    return enrich({"tool": "apiverity", "command": command, **payload}, **meta)


def _validate(root: Path, args: dict[str, Any]) -> dict[str, Any]:
    from apiverity.security.checks import run_security_checks

    service, findings, plugin, resolved = _load_contract(root, str(args.get("spec", "")))
    findings = list(findings) + list(run_security_checks(service))
    return _artifact(
        "validate",
        {
            "protocol": plugin.protocol().value,
            "title": service.title,
            "version": service.version,
            "operations": len(service.operations),
            "findings": [f.model_dump(mode="json") for f in findings],
        },
        spec_path=str(resolved),
        protocol=plugin.protocol().value,
    )


def _diff(root: Path, args: dict[str, Any]) -> dict[str, Any]:
    from apiverity.diff.engine import diff_services

    old, _, plugin, old_path = _load_contract(root, str(args.get("old", "")))
    new, _, _, _ = _load_contract(root, str(args.get("new", "")))
    changes = diff_services(old, new)
    return _artifact(
        "diff",
        {
            "old_version": old.version,
            "new_version": new.version,
            "changes": [c.model_dump(mode="json") for c in changes],
        },
        spec_path=str(old_path),
        protocol=plugin.protocol().value,
    )


def _breaking(root: Path, args: dict[str, Any]) -> dict[str, Any]:
    from apiverity.diff.compat import analyze_compat
    from apiverity.diff.engine import diff_services
    from apiverity.diff.protocol_compat import analyze_protocol_compat
    from apiverity.rules.breaking import evaluate_breaking

    old, _, plugin, old_path = _load_contract(root, str(args.get("old", "")))
    new, _, _, _ = _load_contract(root, str(args.get("new", "")))
    changes = diff_services(old, new)
    findings = (
        evaluate_breaking(changes) + analyze_compat(old, new) + analyze_protocol_compat(old, new)
    )
    errors = sum(1 for f in findings if f.severity.value == "ERROR")
    return _artifact(
        "breaking",
        {
            "old_version": old.version,
            "new_version": new.version,
            "change_count": len(changes),
            "findings": [f.model_dump(mode="json") for f in findings],
            "errors": errors,
        },
        spec_path=str(old_path),
        protocol=plugin.protocol().value,
    )


def _changelog(root: Path, args: dict[str, Any]) -> dict[str, Any]:
    from apiverity.diff.engine import diff_services
    from apiverity.rules.breaking import evaluate_breaking
    from apiverity.rules.changelog import generate_changelog

    old, _, plugin, old_path = _load_contract(root, str(args.get("old", "")))
    new, _, _, _ = _load_contract(root, str(args.get("new", "")))
    changes = diff_services(old, new)
    markdown = generate_changelog(
        old.title, old.version, new.version, changes, evaluate_breaking(changes)
    )
    return _artifact(
        "changelog",
        {"markdown": markdown},
        spec_path=str(old_path),
        protocol=plugin.protocol().value,
    )


def _coverage(root: Path, args: dict[str, Any]) -> dict[str, Any]:
    from apiverity.coverage import measure_coverage

    service, _, plugin, resolved = _load_contract(root, str(args.get("spec", "")))
    # No exercised set: over MCP this reports what the contract declares, which
    # is the baseline an agent can use. Feeding it a test run would mean
    # reading results the caller did not provide.
    report = measure_coverage(service)
    return _artifact(
        "coverage",
        {"report": report.model_dump(mode="json")},
        spec_path=str(resolved),
        protocol=plugin.protocol().value,
    )


def _rules(root: Path, args: dict[str, Any]) -> dict[str, Any]:
    from apiverity.rules.breaking import CATALOG

    return _artifact(
        "rules",
        {
            "count": len(CATALOG),
            "catalog": [
                {
                    "rule_id": spec.rule_id,
                    "severity": spec.severity.value,
                    "description": spec.description,
                }
                for spec in CATALOG.values()
            ],
        },
    )


def _plugins(root: Path, args: dict[str, Any]) -> dict[str, Any]:
    from apiverity.specs.loader import _builtin_plugins

    seen: list[str] = []
    for plugin in _builtin_plugins():
        value = plugin.protocol().value
        if value not in seen:
            seen.append(value)
    return _artifact("plugins", {"formats": seen})


#: The exposed surface, in the order `docs/mcp-exposure.md` lists it.
#:
#: What is *not* here is the point, and the boundary is the one
#: `SAFETY_MODEL.md` already draws: `drift`, `replay`, `baseline` and
#: `regression` contact a target, and a model should not be able to send
#: traffic to an arbitrary base URL because a prompt told it to; `mock`,
#: `serve` and `server-db` start listeners and hold state, and a tool call that
#: leaves a process running is not a tool call; `export` writes to disk.
TOOLS: tuple[Tool, ...] = (
    Tool(
        "validate",
        "Validate an API contract and report parse, reference and security findings.",
        {
            "type": "object",
            "required": ["spec"],
            "properties": {"spec": _SPEC_ARG},
            "additionalProperties": False,
        },
        _validate,
    ),
    Tool(
        "diff",
        "Compare two versions of a contract and return the semantic changes.",
        {
            "type": "object",
            "required": ["old", "new"],
            "properties": {"old": _SPEC_ARG, "new": _SPEC_ARG},
            "additionalProperties": False,
        },
        _diff,
    ),
    Tool(
        "breaking",
        "Classify the changes between two contract versions, direction-aware, "
        "with a stable rule id and severity per finding.",
        {
            "type": "object",
            "required": ["old", "new"],
            "properties": {"old": _SPEC_ARG, "new": _SPEC_ARG},
            "additionalProperties": False,
        },
        _breaking,
    ),
    Tool(
        "changelog",
        "Render the changes between two contract versions as a human changelog.",
        {
            "type": "object",
            "required": ["old", "new"],
            "properties": {"old": _SPEC_ARG, "new": _SPEC_ARG},
            "additionalProperties": False,
        },
        _changelog,
    ),
    Tool(
        "coverage",
        "Report which operations a contract declares, as a coverage baseline.",
        {
            "type": "object",
            "required": ["spec"],
            "properties": {"spec": _SPEC_ARG},
            "additionalProperties": False,
        },
        _coverage,
    ),
    Tool(
        "rules",
        "List every breaking-change rule with its id, severity and rationale.",
        {"type": "object", "properties": {}, "additionalProperties": False},
        _rules,
    ),
    Tool(
        "plugins",
        "List the contract formats this installation can read.",
        {"type": "object", "properties": {}, "additionalProperties": False},
        _plugins,
    ),
)

TOOLS_BY_NAME: dict[str, Tool] = {tool.name: tool for tool in TOOLS}
