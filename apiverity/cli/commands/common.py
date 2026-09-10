"""Shared CLI plumbing: stable exit codes, spec loading, result emission."""

from __future__ import annotations

import argparse
import json
import sys
from typing import TYPE_CHECKING, Any

NL = chr(10)

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_USAGE = 2
EXIT_UNREACHABLE = 3
EXIT_INTERNAL = 4

if TYPE_CHECKING:
    from apiverity.core.model import Finding, Service
    from apiverity.specs import SpecPlugin

#: Whether the OpenAPI bundler may fetch a `$ref` that names a URL. Module
#: state rather than a parameter on `_load`, because it is set once from the
#: parsed arguments and read by seventeen call sites that otherwise have no
#: reason to know about it. `main()` sets it before dispatching, next to
#: `_use_utf8_streams()`, so a command can never see a stale value from
#: another run in the same process.
_ALLOW_REMOTE_REFS = False

_LAST_SPEC: str | None = None
_LAST_TARGET: str | None = None
_LAST_SEED: int | None = None
#: Protocol of the last contract loaded. Recorded so an artifact reports the
#: protocol it actually describes; the envelope used to hardcode "openapi-3.x",
#: so every gRPC, GraphQL and AsyncAPI run wrote an artifact claiming OpenAPI.
_LAST_PROTOCOL: str | None = None


def set_allow_remote_refs(allowed: bool) -> None:
    global _ALLOW_REMOTE_REFS
    _ALLOW_REMOTE_REFS = bool(allowed)


def set_last_target(target: str | None) -> None:
    """Record the most recent base URL for artifact enrichment."""
    global _LAST_TARGET
    _LAST_TARGET = target


def set_last_seed(seed: int | None) -> None:
    """Record the most recent generation seed for artifact enrichment."""
    global _LAST_SEED
    _LAST_SEED = seed


def set_last_contract(path: str | None, protocol: str | None) -> None:
    """Record a contract read without going through `_load`.

    `mcp-lock` reads a tools/list manifest directly -- from a file or off a
    live server -- so it never touches `_load`, and its artifacts were stamped
    with the "no contract" sentinel hash and `protocol_version: unknown` while
    describing a specific MCP tool surface. Provenance that does not name the
    thing it came from is worse than absent.
    """
    global _LAST_SPEC, _LAST_PROTOCOL
    _LAST_SPEC = path
    _LAST_PROTOCOL = protocol


def _load(path: str) -> tuple[Service, list[Finding], SpecPlugin]:
    from apiverity.specs import UnrecognizedSpecError
    from apiverity.specs.loader import detect_and_load

    global _LAST_SPEC, _LAST_PROTOCOL
    _LAST_SPEC = path
    try:
        loaded = detect_and_load(path, allow_remote_refs=_ALLOW_REMOTE_REFS)
        _LAST_PROTOCOL = getattr(loaded[0].protocol, "value", None)
        return loaded
    except FileNotFoundError:
        print(f"error: file not found: {path}", file=sys.stderr)
        sys.exit(EXIT_USAGE)
    except UnrecognizedSpecError as exc:
        # Not a contract at all -- distinct from a contract that fails to parse.
        # Say so explicitly so the caller can tell "skip this file" from
        # "this contract is broken"; a CI gate scanning a mixed directory
        # depends on that distinction.
        print(f"error: not an API contract: {exc}", file=sys.stderr)
        print(
            "hint: pass an OpenAPI, Swagger 2.0, GraphQL, gRPC or AsyncAPI "
            "document, or point the gate at your contract directory.",
            file=sys.stderr,
        )
        sys.exit(EXIT_USAGE)
    except Exception as exc:
        print(f"error: failed to load spec: {exc}", file=sys.stderr)
        sys.exit(EXIT_USAGE)


def _pair(args: argparse.Namespace) -> tuple[Service, Service]:
    old_service, _, _ = _load(args.old)
    new_service, _, _ = _load(args.new)
    return old_service, new_service


def _jsonable(value: Any) -> Any:
    """Convert Pydantic models to plain JSON structures, recursively.

    `json.dumps(..., default=str)` alone silently rendered every model as its
    Python repr, so `--json` emitted strings like
    ``"id='CHG-OP-REMOVED-1' kind=<ChangeKind.OPERATION_REMOVED: ...>"``
    where a consumer expects an object. That defeats the point of the flag:
    the documented contract is structured output for scripting, and no
    consumer can parse a repr. The text renderer already called model_dump;
    only the JSON path was wrong.
    """
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _emit(data: dict[str, Any], as_json: bool) -> None:
    from apiverity.core.artifact import enrich

    data = enrich(
        data,
        spec_path=_LAST_SPEC,
        target=_LAST_TARGET,
        seed=_LAST_SEED,
        protocol=_LAST_PROTOCOL,
    )
    if as_json:
        print(json.dumps(_jsonable(data), indent=2, default=str))
    else:
        for key, value in data.items():
            if isinstance(value, list) and value and hasattr(value[0], "model_dump"):
                print(f"{key}:")
                for item in value:
                    print("  " + _render_row(item.model_dump()))
            else:
                print(f"{key}: {value}")


def _render_row(d: dict[str, Any]) -> str:
    """One line for a finding, a test result, or a change.

    These three shapes share this renderer and only findings carry a
    `severity` and a `rule_id`. A `Change` has neither, so the previous
    formatting printed a literal empty bracket and then dropped the change id
    entirely -- `apiverity diff` emitted lines like

        []  operation 'DELETE /users/{id}' was removed

    with no way to reference the change it just told you about, even though
    every Change has a stable `id` for exactly that purpose. The label now
    falls back to the change's direction, the identifier falls back to `id`,
    and an absent label prints nothing rather than `[]`.
    """
    label = d.get("severity") or d.get("status") or d.get("direction") or ""
    identifier = d.get("rule_id") or d.get("case_id") or d.get("step") or d.get("id") or ""
    text = d.get("message") or d.get("description") or ""
    if not identifier and not text:
        # A model with none of these keys. Rendering it as an empty line is
        # how `apiverity mcp-inventory` printed three blank rows where three
        # configured servers should have been: the data was in the artifact
        # and the text output said nothing at all. Falling back to the fields
        # themselves is uglier and is never silent.
        fields = ", ".join(
            f"{key}={value}" for key, value in d.items() if value not in (None, "", [], {})
        )
        return f"[{label}] {fields}".strip() if label else fields
    prefix = f"[{label}] " if label else ""
    return f"{prefix}{identifier}  {text}".strip()
