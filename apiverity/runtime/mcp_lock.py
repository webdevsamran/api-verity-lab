"""`mcp.lock` — a reviewed baseline for a server's tool surface.

The problem this solves is not detection, it is *review*. `drift` answers "does
the server still match the manifest", which needs a manifest somebody captured
and kept. Most teams have neither. Their agent talks to a server they do not
control, its tool surface changes whenever the operator ships, and the first
sign of it is behaviour.

A lockfile changes who has to notice. The surface is captured once, committed,
and CI fails on any change to it until a human updates the file in a pull
request — the same bargain `package-lock.json` makes, for the same reason.

Why the whole surface is in the file and not just a hash
--------------------------------------------------------
A hash can only say *that* something changed. The interesting question in the
pull request is which tool, and whether the change breaks a caller, and the
only way to answer it is to still have the old surface. So the lock carries the
normalized tools, and `check` rebuilds them through the same `load_manifest`
the new capture goes through — two contracts handed to `diff_services` must
have been built the same way, or the differences it reports include the ones
the loader invented.

That also means the diff is not this module's opinion. A newly-required
argument in a lockfile change fires `BRK-PARAM-ADDED-REQUIRED`, the same rule
an OpenAPI change would, and the finding carries that id.

Where the version lives
-----------------------
An MCP tool carries no version field, and SEP-1575 *Tool Semantic Versioning*
is an open, unsponsored proposal. Rather than invent a field in someone else's
protocol, the version lives in the file *you* own: `surface_version` in the
lock. `check` runs the recorded version and the classified changes through the
same `suggest_bump` the OpenAPI advisor uses, so the recommendation and its
reasons come from the shared policy rather than from a second implementation.

Signing
-------
`--sign` writes an HMAC over the canonical lock body, keyed from an environment
variable. Be precise about what that buys: it detects an edit made by someone
who does not hold the key. It is not provenance and it is not a public-key
signature — anyone who can run CI can compute a new one. It is there for the
case where the baseline is rewritten by something that never had the key, and
it says so rather than implying more.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from apiverity.core.hash import canonical_json
from apiverity.core.model import Finding, Service, Severity
from apiverity.diff.engine import diff_services
from apiverity.rules.breaking import evaluate_breaking
from apiverity.rules.semver import VersionAdvice, suggest_bump
from apiverity.specs.mcp.manifest import load_manifest, unwrap_manifest

#: Bump this when the meaning of an existing key changes, never for an addition.
LOCK_VERSION = 1

DEFAULT_LOCK_NAME = "mcp.lock"

#: The version a first capture starts at. 1.0.0 rather than 0.1.0: the surface
#: being locked already exists and is already being called.
INITIAL_SURFACE_VERSION = "1.0.0"

DEFAULT_KEY_ENV = "APIVERITY_LOCK_KEY"

#: Cache and pagination state on a `tools/list` result. Excluded from the lock
#: for the same reason `manifest.py` keeps them out of the model: they differ
#: run to run, and a baseline that churns is a baseline nobody re-reads.
_VOLATILE_TOOL_KEYS = ("_meta",)

_SIGNATURE_ALG = "hmac-sha256"


class LockError(ValueError):
    """The lockfile could not be used as written."""


class LockDelta(BaseModel):
    """What changed between a recorded surface and a fresh capture."""

    changed: bool = False
    added: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)
    modified: list[str] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    advice: dict[str, Any] = Field(default_factory=dict)
    recorded_hash: str = ""
    observed_hash: str = ""
    surface_version: str = INITIAL_SURFACE_VERSION
    signature_state: str = "absent"


def _clean_tool(tool: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in tool.items() if key not in _VOLATILE_TOOL_KEYS}


def tool_hash(tool: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(_clean_tool(tool)).encode()).hexdigest()


def surface_hash(tools: list[dict[str, Any]]) -> str:
    """A hash over the whole surface, keyed by tool name.

    Built from the per-tool hashes rather than from the document, so a server
    that reorders `tools/list` between calls -- which the specification permits,
    since it only SHOULDs a deterministic order -- does not produce a different
    baseline every run.
    """
    pairs = sorted((str(tool.get("name", "")), tool_hash(tool)) for tool in tools)
    return "sha256:" + hashlib.sha256(canonical_json(pairs).encode()).hexdigest()


def _signable(body: dict[str, Any]) -> bytes:
    """Canonical bytes of a lock body, excluding the signature itself."""
    return canonical_json({k: v for k, v in body.items() if k != "signature"}).encode()


def sign_body(body: dict[str, Any], key: str) -> str:
    return hmac.new(key.encode(), _signable(body), hashlib.sha256).hexdigest()


def build_lock(
    tools: list[dict[str, Any]],
    *,
    source: str,
    tool_version: str,
    surface_version: str = INITIAL_SURFACE_VERSION,
    key_env: str | None = None,
) -> dict[str, Any]:
    """The lock document for a captured tool surface."""
    ordered = sorted((_clean_tool(t) for t in tools), key=lambda t: str(t.get("name", "")))
    body: dict[str, Any] = {
        "lock_version": LOCK_VERSION,
        "surface_version": surface_version,
        "generated_by": f"apiverity {tool_version}",
        "source": source,
        "surface_hash": surface_hash(ordered),
        "tools": {str(t.get("name", "")): tool_hash(t) for t in ordered},
        # The tools themselves, so `check` can say *what* changed rather than
        # only that something did.
        "surface": {"tools": ordered},
    }
    if key_env:
        key = os.environ.get(key_env)
        if not key:
            raise LockError(
                f"{key_env} is not set in the environment, so the lock cannot be signed. "
                "Set it or drop --sign; a lock written with an empty key would verify "
                "against an empty key"
            )
        body["signature"] = {
            "alg": _SIGNATURE_ALG,
            "key_env": key_env,
            "value": sign_body(body, key),
        }
    return body


def dumps_lock(body: dict[str, Any]) -> str:
    """Stable text for a lockfile. Indented and sorted: it is reviewed by hand."""
    return json.dumps(body, indent=2, sort_keys=True) + "\n"


def load_lock(path: str | Path) -> dict[str, Any]:
    try:
        raw = Path(path).read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise LockError(f"{path}: {exc}") from exc
    try:
        body = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LockError(f"{path}: not valid JSON ({exc})") from exc
    if not isinstance(body, dict):
        raise LockError(f"{path}: a lockfile is a JSON object")
    version = body.get("lock_version")
    if version != LOCK_VERSION:
        raise LockError(
            f"{path}: lock_version {version!r} is not supported; this build writes and reads "
            f"{LOCK_VERSION}. Reading a format it does not understand would mis-apply it"
        )
    if not isinstance(body.get("surface"), dict):
        raise LockError(f"{path}: no `surface` -- this lock cannot be compared, only matched")
    return body


def verify_signature(body: dict[str, Any]) -> tuple[str, Finding | None]:
    """Signature state, and a finding when that state is worth reporting."""
    signature = body.get("signature")
    if not isinstance(signature, dict):
        return "absent", Finding(
            rule_id="MCP-LOCK-UNSIGNED",
            severity=Severity.INFO,
            message=(
                "this lock carries no signature, so an edit to it is indistinguishable from "
                "a review. Write it with --sign if the baseline matters more than the "
                "convenience"
            ),
        )

    key_env = str(signature.get("key_env") or DEFAULT_KEY_ENV)
    key = os.environ.get(key_env)
    if not key:
        return "unverified", Finding(
            rule_id="MCP-LOCK-SIGNATURE-UNVERIFIED",
            severity=Severity.WARN,
            message=(
                f"the lock is signed but {key_env} is not set here, so the signature was not "
                "checked. An unchecked signature is not a passed check"
            ),
        )

    expected = sign_body(body, key)
    if not hmac.compare_digest(expected, str(signature.get("value", ""))):
        return "invalid", Finding(
            rule_id="MCP-LOCK-SIGNATURE-INVALID",
            severity=Severity.ERROR,
            message=(
                "the lock's signature does not match its contents: it was edited by something "
                f"that did not hold {key_env}"
            ),
        )
    return "valid", None


def recorded_service(body: dict[str, Any], *, label: str = "locked") -> Service:
    """Rebuild the locked surface through the same normalizer a capture uses."""
    service, _ = load_manifest(body["surface"], label=label)
    return service


def compare(
    body: dict[str, Any],
    observed_tools: list[dict[str, Any]],
    *,
    require_minor_for_warnings: bool = False,
) -> LockDelta:
    """A recorded baseline against a fresh capture."""
    state, signature_finding = verify_signature(body)
    findings: list[Finding] = [signature_finding] if signature_finding is not None else []

    recorded_map = {str(name): str(h) for name, h in (body.get("tools") or {}).items()}
    observed_map = {str(t.get("name", "")): tool_hash(t) for t in observed_tools}

    added = sorted(set(observed_map) - set(recorded_map))
    removed = sorted(set(recorded_map) - set(observed_map))
    modified = sorted(
        name
        for name in set(recorded_map) & set(observed_map)
        if recorded_map[name] != observed_map[name]
    )

    observed = surface_hash(observed_tools)
    recorded = str(body.get("surface_hash", ""))
    surface_version = str(body.get("surface_version") or INITIAL_SURFACE_VERSION)

    delta = LockDelta(
        changed=observed != recorded,
        added=added,
        removed=removed,
        modified=modified,
        recorded_hash=recorded,
        observed_hash=observed,
        surface_version=surface_version,
        signature_state=state,
    )

    if not delta.changed:
        delta.findings = findings
        delta.advice = VersionAdvice("none", surface_version, [], satisfied=True).as_dict()
        return delta

    old = recorded_service(body)
    new, _ = load_manifest({"tools": observed_tools}, label="observed")
    changes = diff_services(old, new)
    classified = evaluate_breaking(changes)

    # A tool appearing is the one case where this command disagrees with the
    # shared catalogue, and it disagrees on purpose. `BRK-RPC-ADDED` grades an
    # addition INFO, which is right for a version diff -- nothing that worked
    # stopped working. Against a *baseline* an addition is the whole point: a
    # capability an agent can now reach that nobody reviewed. So the addition
    # is re-stated at ERROR and the INFO it replaces is dropped, rather than
    # both being printed and the reader deciding which one this tool meant.
    #
    # There is no matching `MCP-LOCK-TOOL-REMOVED`. `BRK-RPC-REMOVED` is
    # already ERROR and already says the tool is gone; repeating it under a
    # second id would be one fact with two rule ids, which is how a report
    # earns "it found forty things and none of them mattered".
    added_keys = {f"tool {name}" for name in added}
    findings.extend(
        f
        for f in classified
        if not (f.rule_id == "BRK-RPC-ADDED" and f.operation_key in added_keys)
    )
    for name in added:
        findings.append(
            Finding(
                rule_id="MCP-LOCK-TOOL-ADDED",
                severity=Severity.ERROR,
                message=(
                    f"tool {name!r} is served and is not in the baseline. Adding a tool breaks "
                    "nothing, which is why the catalogue grades it INFO -- but a capability an "
                    "agent can reach without anyone reviewing it is what a baseline is for"
                ),
                operation_key=f"tool {name}",
            )
        )

    delta.findings = findings
    # `classified`, deliberately not `findings`. The version advice answers
    # "what does SemVer call this change", where adding a tool is a minor; the
    # findings answer "should this have been reviewed", where adding a tool is
    # the whole point. A run can therefore report an ERROR and recommend a
    # minor bump, and both are correct about different questions.
    delta.advice = suggest_bump(
        surface_version,
        classified,
        changes,
        require_minor_for_warnings=require_minor_for_warnings,
    ).as_dict()
    return delta


def tools_from_document(document: Any) -> list[dict[str, Any]]:
    """The tools array out of any shape a saved manifest arrives in."""
    tools, _ = unwrap_manifest(document)
    return [t for t in tools if isinstance(t, dict)]


__all__ = [
    "DEFAULT_KEY_ENV",
    "DEFAULT_LOCK_NAME",
    "INITIAL_SURFACE_VERSION",
    "LOCK_VERSION",
    "LockDelta",
    "LockError",
    "build_lock",
    "compare",
    "dumps_lock",
    "load_lock",
    "recorded_service",
    "sign_body",
    "surface_hash",
    "tool_hash",
    "tools_from_document",
    "verify_signature",
]
