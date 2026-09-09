"""Who breaks, not just what breaks.

`BRK-OP-REMOVED: operation 'DELETE /users/{id}' was removed` is accurate and
tells the reader nothing they can act on. The question in the pull request is
whose build fails on Monday, and the answer lives in a file nobody has: which
services call which operations.

A consumer registry is that file, and this turns a finding into a blast radius.

The downgrade this refuses to do by default
-------------------------------------------
The obvious next step is to soften a finding nobody consumes -- a removal with
no registered caller is not the same event as one three services depend on, and
that is true. But a registry is incomplete the moment somebody writes a client
without telling anyone, which is most of the time, and "no consumer listed"
then reads as "no consumer exists". Downgrading on that is exactly how a
breaking change ships.

So annotation is the default and downgrading needs two things: the registry
must declare `complete: true`, taking responsibility for the claim, and the
caller must ask with `--severity-by-consumers`. A finding softened that way
says so in its own message, naming the file that made the claim. Everything
else is added information, never removed severity.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from apiverity.core.model import Finding, Severity


class RegistryError(ValueError):
    """The consumer registry could not be used as written."""


@dataclass(frozen=True)
class Consumer:
    """One service, and the operations it calls."""

    name: str
    operations: tuple[str, ...]
    team: str | None = None
    contact: str | None = None

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"name": self.name, "operations": list(self.operations)}
        if self.team:
            out["team"] = self.team
        if self.contact:
            out["contact"] = self.contact
        return out


@dataclass
class Registry:
    version: int = 1
    #: Whether this file claims to list every consumer. Only a registry that
    #: says so may be used to soften a finding.
    complete: bool = False
    consumers: list[Consumer] = field(default_factory=list)
    source: str = ""

    def for_operation(self, operation_key: str) -> list[Consumer]:
        return [c for c in self.consumers if operation_key in c.operations]

    @property
    def operations(self) -> set[str]:
        return {op for c in self.consumers for op in c.operations}


def _operation_key(entry: Any) -> str:
    """`operation: "GET /users"` or `tool: search` -- the manifest's own key."""
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        tool = entry.get("tool")
        if isinstance(tool, str):
            return f"tool {tool}"
        operation = entry.get("operation")
        if isinstance(operation, str):
            return operation
    raise RegistryError("each `uses` entry names an `operation` or a `tool`")


def load_registry(path: str | Path) -> Registry:
    """Parse a consumer registry (YAML or JSON)."""
    import yaml

    source = Path(path)
    try:
        raw = yaml.safe_load(source.read_text(encoding="utf-8-sig")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise RegistryError(f"{source}: {exc}") from exc
    if not isinstance(raw, dict):
        raise RegistryError(f"{source}: a consumer registry is a mapping at the top level")
    if raw.get("version") != 1:
        raise RegistryError(
            f"{source}: registry version {raw.get('version')!r} is not supported; "
            "this build understands 1"
        )

    entries = raw.get("consumers")
    if not isinstance(entries, list):
        raise RegistryError(f"{source}: `consumers` must be a list")

    consumers: list[Consumer] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise RegistryError(f"{source}: each consumer is a mapping")
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            raise RegistryError(f"{source}: each consumer needs a `name`")
        uses = entry.get("uses")
        if not isinstance(uses, list):
            raise RegistryError(f"{source}: consumer {name!r} needs a `uses` list")
        consumers.append(
            Consumer(
                name=name,
                operations=tuple(sorted({_operation_key(use) for use in uses})),
                team=entry.get("team") if isinstance(entry.get("team"), str) else None,
                contact=entry.get("contact") if isinstance(entry.get("contact"), str) else None,
            )
        )

    duplicates = sorted(
        {c.name for c in consumers if [x.name for x in consumers].count(c.name) > 1}
    )
    if duplicates:
        raise RegistryError(f"{source}: {duplicates} appear more than once")

    return Registry(
        version=1,
        complete=bool(raw.get("complete", False)),
        consumers=consumers,
        source=str(source),
    )


def validate_against(registry: Registry, declared_operations: set[str]) -> list[Finding]:
    """Registry entries that name something the contract does not declare.

    An entry pointing at an operation that does not exist can never match a
    finding, so the registry looks like coverage and provides none -- and with
    `complete: true` it would actively soften findings for the operation the
    author meant to protect.

    `declared_operations` must be the union of both sides of the comparison. A
    consumer that uses an operation the new version removed is the case this
    whole module exists to report; checking against the new contract alone
    would flag every one of them as a typo, which is both wrong and exactly
    backwards.
    """
    findings: list[Finding] = []
    for consumer in registry.consumers:
        for operation in consumer.operations:
            if operation not in declared_operations:
                findings.append(
                    Finding(
                        rule_id="CONSUMER-UNKNOWN-OPERATION",
                        severity=Severity.ERROR,
                        operation_key=operation,
                        message=(
                            f"{registry.source}: {consumer.name!r} declares it uses "
                            f"{operation!r}, which this contract does not declare. The entry "
                            "can never match a finding, so it is coverage in name only"
                        ),
                    )
                )
    return findings


#: Findings about the registry itself. Annotating one with the consumers that
#: caused it is circular -- "'legacy-batch' names an operation that does not
#: exist -- affects legacy-batch" -- and it reads like two problems.
_ABOUT_THE_REGISTRY = ("CONSUMER-",)


def annotate(
    findings: list[Finding],
    registry: Registry,
    *,
    adjust_severity: bool = False,
) -> list[Finding]:
    """Attach the affected consumers to each finding, in place-safe copies."""
    out: list[Finding] = []
    for finding in findings:
        if finding.rule_id.startswith(_ABOUT_THE_REGISTRY):
            out.append(finding)
            continue
        affected = registry.for_operation(finding.operation_key or "")
        if not affected and not (adjust_severity and registry.complete):
            out.append(finding)
            continue

        updated = finding.model_copy(deep=True)
        if affected:
            updated.metadata = {
                **updated.metadata,
                "consumers": [c.name for c in affected],
                "consumer_teams": sorted({c.team for c in affected if c.team}),
            }
            names = ", ".join(c.name for c in affected)
            updated.message = f"{updated.message} — affects {names}"
        elif (
            adjust_severity
            and registry.complete
            and finding.severity is Severity.ERROR
            and finding.operation_key
        ):
            # Only from a registry that took responsibility for being complete,
            # and the finding says which file made that claim.
            updated.severity = Severity.WARN
            updated.metadata = {**updated.metadata, "consumers": [], "downgraded_from": "ERROR"}
            updated.message = (
                f"{updated.message} — no registered consumer calls this, and "
                f"{registry.source} declares itself complete, so it is reported at WARN"
            )
        out.append(updated)
    return out


def blast_radius(findings: list[Finding], registry: Registry) -> dict[str, Any]:
    """What breaks, per consumer and per operation."""
    per_consumer: dict[str, dict[str, Any]] = {}
    per_operation: dict[str, list[str]] = {}

    for finding in findings:
        if finding.severity is not Severity.ERROR:
            continue
        key = finding.operation_key or ""
        affected = registry.for_operation(key)
        if key:
            per_operation.setdefault(key, sorted(c.name for c in affected))
        for consumer in affected:
            record = per_consumer.setdefault(
                consumer.name,
                {
                    "team": consumer.team,
                    "contact": consumer.contact,
                    "operations": [],
                    "findings": 0,
                },
            )
            record["findings"] += 1
            if key not in record["operations"]:
                record["operations"].append(key)

    return {
        "registry": registry.source,
        "complete": registry.complete,
        "consumers_registered": len(registry.consumers),
        # Operations with a breaking finding and nobody registered against
        # them. Named separately because that is where an incomplete registry
        # hurts, and a reader should see the gap rather than infer it.
        "unclaimed_operations": sorted(k for k, v in per_operation.items() if not v),
        "by_operation": dict(sorted(per_operation.items())),
        "by_consumer": {k: per_consumer[k] for k in sorted(per_consumer)},
    }


__all__ = [
    "Consumer",
    "Registry",
    "RegistryError",
    "annotate",
    "blast_radius",
    "load_registry",
    "validate_against",
]
