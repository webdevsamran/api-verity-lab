"""Protocol v2: stable entity IDs, canonical hashes, migrations and bundles.

Layered on top of the normalized model without breaking v1 readers:

- ``entity_id``  — deterministic, human-readable stable IDs for every entity.
- ``entity_hash`` — canonical content hash of an entity subtree.
- ``migrate_artifact`` — upgrades a persisted result-v1 artifact to the
  current schema version, recording a supersession record instead of
  discarding history.
- :class:`ContractBundle` — multiple services/protocols combined into one
  versioned API surface with catalog indexes and ownership metadata.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .hash import canonical_json
from .model import Operation, Protocol, Service

ARTIFACT_SCHEMA_VERSION = "2.0"
SUPPORTED_ARTIFACT_VERSIONS = ("1.0", "2.0")


def _slug(value: str) -> str:
    out = []
    for ch in value.lower():
        if ch.isalnum():
            out.append(ch)
        elif out and out[-1] != "-":
            out.append("-")
    return "".join(out).strip("-") or "x"


def service_id(service: Service) -> str:
    """Stable ID for a contract: ``svc:<protocol>:<title-slug>:<version>``."""
    return f"svc:{service.protocol.value}:{_slug(service.title)}:{service.version}"


def operation_entity_id(op: Operation) -> str:
    """Stable entity ID for an operation within its service.

    Format: ``op:<kind>:<canonical-key-slug>``. The canonical key is already
    stable across revisions, so IDs survive reordering and cosmetic edits.
    """
    return f"op:{op.kind.value}:{_slug(op.key)}"


def parameter_entity_id(op: Operation, param_name: str) -> str:
    return f"{operation_entity_id(op)}:param:{_slug(param_name)}"


def response_entity_id(op: Operation, status: str) -> str:
    return f"{operation_entity_id(op)}:response:{status}"


def schema_entity_id(parent_id: str, pointer: str) -> str:
    return f"{parent_id}:schema:{pointer}"


def entity_hash(entity: Any) -> str:
    """Canonical SHA-256 over the entity's serialized model, excluding volatile fields."""
    if hasattr(entity, "model_dump"):
        data = entity.model_dump(mode="json")
        for volatile in ("source_location", "new_location"):
            data.pop(volatile, None)
        payload = canonical_json(data)
    else:
        payload = canonical_json(entity)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def fingerprint_findings(findings: list[dict[str, Any]]) -> list[str]:
    """Deterministic fingerprints for findings so repeats dedupe across revisions.

    The fingerprint covers rule id, severity, operation key and message but
    NOT timestamps or file paths that legitimately change between runs.
    """
    prints = []
    for f in findings:
        basis = {
            "rule": f.get("rule_id"),
            "severity": f.get("severity"),
            "op": f.get("operation_key"),
            "msg": f.get("message"),
        }
        prints.append(hashlib.sha256(canonical_json(basis).encode()).hexdigest()[:16])
    return prints


# --- Artifact migration ------------------------------------------------------


class SupersessionRecord(BaseModel):
    """Immutable record that one artifact version supersedes another."""

    previous_schema_version: str
    new_schema_version: str
    migrated_utc: str
    lossy: bool = False
    notes: list[str] = Field(default_factory=list)


def migrate_artifact(artifact: dict[str, Any]) -> tuple[dict[str, Any], SupersessionRecord]:
    """Upgrade a persisted result artifact to the current schema version.

    v1 artifacts gain ``artifact_schema_version``, per-finding ``fingerprint``
    values and UTC provenance. Nothing is removed; readers of either version
    keep working (backwards-compatible reader policy).
    """
    version = str(
        artifact.get("result_schema_version") or artifact.get("artifact_schema_version") or "1.0"
    )
    notes: list[str] = []
    migrated = dict(artifact)
    if version == ARTIFACT_SCHEMA_VERSION:
        rec = SupersessionRecord(
            previous_schema_version=version,
            new_schema_version=version,
            migrated_utc=_utcnow(),
            notes=["already current"],
        )
        return migrated, rec
    if version not in SUPPORTED_ARTIFACT_VERSIONS:
        raise ValueError(f"unsupported artifact schema version: {version}")
    migrated["artifact_schema_version"] = ARTIFACT_SCHEMA_VERSION
    migrated["superseded_schema_version"] = version
    findings = migrated.get("findings")
    if isinstance(findings, list):
        for f in findings:
            if isinstance(f, dict) and not f.get("fingerprint"):
                f["fingerprint"] = fingerprint_findings([f])[0]
        notes.append(f"fingerprinted {len(findings)} findings")
    if not migrated.get("generated_utc"):
        migrated["generated_utc"] = _utcnow()
        notes.append("backfilled generated_utc")
    rec = SupersessionRecord(
        previous_schema_version=version,
        new_schema_version=ARTIFACT_SCHEMA_VERSION,
        migrated_utc=_utcnow(),
        lossy=False,
        notes=notes,
    )
    return migrated, rec


def _utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


# --- Bundles & catalog -------------------------------------------------------


class BundleEntry(BaseModel):
    """One contract inside a bundle, with its own lifecycle/version identity."""

    path: str
    protocol: Protocol
    title: str
    version: str
    owner: str | None = None
    team: str | None = None
    product: str | None = None
    lifecycle_state: str | None = None


class ContractBundle(BaseModel):
    """A versioned product surface combining multiple contracts/protocols."""

    name: str
    version: str
    description: str | None = None
    entries: list[BundleEntry] = Field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    @staticmethod
    def from_services(name: str, version: str, services: list[Service]) -> ContractBundle:
        entries = [
            BundleEntry(
                path=svc.source_file or svc.title,
                protocol=svc.protocol,
                title=svc.title,
                version=svc.version,
                owner=svc.owner,
                team=svc.team,
                product=svc.product,
                lifecycle_state=svc.lifecycle_state.value if svc.lifecycle_state else None,
            )
            for svc in services
        ]
        return ContractBundle(name=name, version=version, entries=entries)


def load_ownership_mapping(path: str | Path) -> dict[str, dict[str, str]]:
    """Parse a CODEOWNERS-style file into per-glob ownership metadata.

    Lines look like ``glob  @team  owner@example.com``; later matches win.
    Returns ``{glob: {"owner": ..., "team": ...}}``.
    """
    mapping: dict[str, dict[str, str]] = {}
    text = Path(path).read_text(encoding="utf-8")
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        glob, owners = parts[0], parts[1]
        entry = mapping.setdefault(glob, {})
        entry["owner"] = owners.lstrip("@")
        if len(parts) > 2:
            entry.setdefault("team", parts[2].lstrip("@"))
    return mapping


def apply_ownership(services: list[Service], mapping: dict[str, dict[str, str]]) -> list[str]:
    """Apply CODEOWNERS-style metadata onto services by source file glob match.

    Uses simple fnmatch semantics. Returns the globs that were applied.
    """
    import fnmatch

    applied: list[str] = []
    for svc in services:
        target = svc.source_file or ""
        for glob, meta in mapping.items():
            if target and fnmatch.fnmatch(target.replace("\\", "/"), glob):
                svc.owner = meta.get("owner", svc.owner)
                svc.team = meta.get("team", svc.team)
                applied.append(glob)
    return sorted(set(applied))


def build_catalog_index(
    services: list[Service],
    *,
    group_by: str = "product",
) -> dict[str, list[dict[str, Any]]]:
    """Build a catalog index grouped by product/team/lifecycle/environment/protocol.

    Environment grouping uses server URL hostnames as a proxy when explicit
    environment metadata is absent.
    """
    groups: dict[str, list[dict[str, Any]]] = {}

    def key_for(svc: Service) -> str:
        if group_by == "product":
            return svc.product or "ungrouped"
        if group_by == "team":
            return svc.team or "ungrouped"
        if group_by == "owner":
            return svc.owner or "ungrouped"
        if group_by == "lifecycle":
            return svc.lifecycle_state.value if svc.lifecycle_state else "unspecified"
        if group_by == "protocol":
            return svc.protocol.value
        if group_by == "environment":
            hosts = {s.url for s in svc.servers}
            return ",".join(sorted(hosts)) or "no-servers"
        raise ValueError(f"unknown group_by: {group_by}")

    for svc in services:
        groups.setdefault(key_for(svc), []).append(
            {
                "service_id": service_id(svc),
                "title": svc.title,
                "version": svc.version,
                "protocol": svc.protocol.value,
                "operations": len(svc.operations),
                "owner": svc.owner,
                "team": svc.team,
                "product": svc.product,
                "lifecycle_state": svc.lifecycle_state.value if svc.lifecycle_state else None,
            }
        )
    return dict(sorted(groups.items()))
