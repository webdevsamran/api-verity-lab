"""Shared CLI plumbing: stable exit codes, spec loading, result emission."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
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

#: Format name from `--spec-format`, or None to sniff. Same reasoning as
#: `_ALLOW_REMOTE_REFS`: set once from the parsed arguments, read by every
#: call site that loads a contract.
_SPEC_FORMAT: str | None = None

#: The project config for this run, or None when there is none (or `--no-config`).
#:
#: `.apiverity.yaml` was parsed, schema-checked, and then applied to nothing.
#: `load_config` had exactly one caller -- `apiverity config`, the command that
#: prints it -- so `severity_overrides` did nothing, `fail_on` did nothing, and
#: a project that ran `apiverity init` got a file that CI dutifully validated
#: and every other command ignored. Held here so every command reads the same
#: one, loaded once.
_CONFIG: Any = None
_CONFIG_FINDINGS: list[Any] = []

_LAST_SPEC: str | None = None
_LAST_TARGET: str | None = None
_LAST_SEED: int | None = None
#: Protocol of the last contract loaded. Recorded so an artifact reports the
#: protocol it actually describes; the envelope used to hardcode "openapi-3.x",
#: so every gRPC, GraphQL and AsyncAPI run wrote an artifact claiming OpenAPI.
_LAST_PROTOCOL: str | None = None


def reset_provenance() -> None:
    """Forget which spec, target and seed the last command used.

    These are process globals set as a side effect of loading a contract, which
    is right for one command per process and wrong for N.
    `apiverity/mcp/tools.py` documents the same hazard and avoids it by not
    using them at all; `apiverity watch` re-enters `main()` in a loop, so it
    clears them instead. Without this, a run that fails *before* loading a spec
    stamps its artifact with the previous run's spec path -- an artifact
    describing a file it never read.
    """
    global _LAST_SPEC, _LAST_TARGET, _LAST_SEED, _LAST_PROTOCOL
    _LAST_SPEC = None
    _LAST_TARGET = None
    _LAST_SEED = None
    _LAST_PROTOCOL = None


def set_allow_remote_refs(allowed: bool) -> None:
    global _ALLOW_REMOTE_REFS
    _ALLOW_REMOTE_REFS = bool(allowed)


def set_spec_format(name: str | None) -> None:
    global _SPEC_FORMAT
    _SPEC_FORMAT = name or None


def load_project_config(path: str | None, *, disabled: bool = False) -> list[Any]:
    """Find and load `.apiverity.yaml` for this run. Returns its findings.

    A config that cannot be parsed is a hard error rather than a fallback to
    defaults: a project that wrote `severity_overides` and got the defaults
    silently is exactly the case the parser refuses unknown keys for, and
    falling back here would undo that at the last step.
    """
    global _CONFIG, _CONFIG_FINDINGS
    _CONFIG, _CONFIG_FINDINGS = None, []
    if disabled:
        return []

    from apiverity.core.config import find_config, load_config

    resolved = Path(path) if path else find_config()
    if resolved is None:
        return []
    if not resolved.exists():
        print(f"error: config not found: {resolved}", file=sys.stderr)
        sys.exit(EXIT_USAGE)
    try:
        config, findings = load_config(resolved)
    except Exception as exc:
        print(f"error: {resolved}: {exc}", file=sys.stderr)
        sys.exit(EXIT_USAGE)
    if any(getattr(f.severity, "value", str(f.severity)) == "ERROR" for f in findings):
        for finding in findings:
            print(f"error: {finding.message}", file=sys.stderr)
        sys.exit(EXIT_USAGE)
    _CONFIG, _CONFIG_FINDINGS = config, list(findings)
    return list(findings)


def project_config() -> Any:
    """The loaded config, or None. Read by the commands that honour it."""
    return _CONFIG


def config_setting(name: str, default: Any = None) -> Any:
    """One setting from the project config, or `default` when there is none."""
    if _CONFIG is None:
        return default
    value = getattr(_CONFIG, name, None)
    return default if value in (None, "", [], {}) else value


#: `--profile`, or None. Set from the parsed arguments alongside the config,
#: and read wherever the two are combined.
_PROFILE: str | None = None


def set_profile(name: str | None) -> None:
    global _PROFILE
    _PROFILE = name or None


def active_profile() -> str | None:
    """The profile in force: the flag, else the config's, else none."""
    return _PROFILE or config_setting("profile")


def merged_severity_overrides(cli_overrides: dict[str, str] | None) -> dict[str, str] | None:
    """Profile, then config, then the command line -- each more specific.

    A profile is a starting position, so anything stated explicitly wins over
    it: a team on `strict` that has agreed one rule is advisory writes that one
    rule down, and the profile must not put it back.
    """
    from apiverity.rules.profiles import severity_overrides

    merged: dict[str, str] = {}
    profile = active_profile()
    if profile:
        merged.update(severity_overrides(str(profile)))
    merged.update(config_setting("severity_overrides", {}) or {})
    merged.update(cli_overrides or {})
    return merged or None


def fail_on_threshold() -> str:
    """`error` / `warn` / `never`, from the config or the profile.

    Explicit beats implied in the same direction as the severities: a config
    that sets `fail_on` has said what it wants, and a profile is what you get
    when it has not.
    """
    from apiverity.core.config import DEFAULT_FAIL_ON

    explicit = config_setting("fail_on")
    if explicit:
        return str(explicit).lower()
    profile = active_profile()
    if profile:
        from apiverity.rules.profiles import fail_on

        return fail_on(str(profile))
    return DEFAULT_FAIL_ON


def apply_project_suppressions(findings: list[Any]) -> tuple[list[Any], dict[str, Any]]:
    """Split findings by the project's suppressions file, if it declares one.

    Returns `(findings_that_still_count, record)`. Suppressed findings are
    *not* discarded -- they are returned inside `record` and reported in the
    artifact, because a gate that silently drops findings on the say-so of a
    file is a gate nobody can audit. Expired suppressions become findings of
    their own, which is the mechanism that stops an ignore-list becoming
    permanent.
    """
    path = config_setting("suppressions")
    if not path:
        return findings, {}

    from apiverity.rules.suppressions import (
        DEFAULT_MAX_LIFETIME_DAYS,
        apply_suppressions,
        expired_suppression_findings,
        incomplete_suppression_findings,
        load_suppressions,
        unscoped_suppression_findings,
    )

    resolved = Path(path)
    if not resolved.is_absolute():
        base = getattr(_CONFIG, "source_path", None)
        # Relative to the config file, not to the working directory: a CI job
        # that runs from the repository root and a developer running from a
        # service directory must resolve it the same way.
        resolved = (Path(base).parent / path) if base else resolved
    try:
        suppressions = load_suppressions(resolved)
    except (OSError, ValueError) as exc:
        print(f"error: suppressions file {resolved}: {exc}", file=sys.stderr)
        sys.exit(EXIT_USAGE)

    result = apply_suppressions(
        findings,
        suppressions,
        max_days=int(config_setting("suppression_max_days", DEFAULT_MAX_LIFETIME_DAYS)),
        require_approver=bool(config_setting("suppression_require_approver", False)),
    )
    # All three go back into the run. An expired entry and an unjustified one
    # both left a finding active, and the reader needs to know which entry did
    # that -- otherwise the file looks like it is working and the finding looks
    # like a new one.
    active = (
        result.active
        + expired_suppression_findings(result.expired)
        + incomplete_suppression_findings(result.incomplete)
        + unscoped_suppression_findings(result.unscoped)
    )
    record = {
        "file": str(resolved),
        "declared": len(suppressions),
        "expired": len(result.expired),
        "incomplete": len(result.incomplete),
        "unscoped": len(result.unscoped),
        "suppressed": [
            {
                "rule_id": finding.rule_id,
                "operation_key": finding.operation_key,
                "message": finding.message,
                "owner": suppression.owner,
                "reason": suppression.reason,
                "expires": suppression.expires,
                "approved_by": suppression.approved_by,
            }
            for finding, suppression in result.suppressed
        ],
        # Named, not just counted: "2 incomplete" tells a reader a file is
        # wrong and not which line to open.
        "not_applied": [
            {
                "rule_id": suppression.rule_id,
                "operation_key": suppression.operation_key,
                "problems": problems,
            }
            for suppression, problems in result.incomplete
        ],
    }
    return active, record


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
    from apiverity.specs.loader import UnknownSpecFormatError, detect_and_load

    global _LAST_SPEC, _LAST_PROTOCOL
    _LAST_SPEC = path
    try:
        loaded = detect_and_load(
            path, allow_remote_refs=_ALLOW_REMOTE_REFS, spec_format=_SPEC_FORMAT
        )
        _LAST_PROTOCOL = getattr(loaded[0].protocol, "value", None)
        return loaded
    except FileNotFoundError:
        print(f"error: file not found: {path}", file=sys.stderr)
        sys.exit(EXIT_USAGE)
    except UnknownSpecFormatError as exc:
        print(f"error: {exc}", file=sys.stderr)
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
