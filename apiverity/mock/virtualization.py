"""Several dependent mock APIs from one definition, under one seed.

`PRODUCT_GAPS.md` answers "why are there no hand-authored stub DSLs (WireMock
territory)" with *"virtualization derives from contracts"*. This is that, and
until `mock --workspace` it was reachable from no command -- so the published
answer to WireMock pointed at code a user could not run.

## Why a workspace rather than several `mock` commands

`apiverity mock a.yaml & apiverity mock b.yaml` gets you two servers. What it
does not get you is a *reproducible* pair: each process seeds its own generator
from its own default, so the data a frontend sees depends on which flags each
was started with, and a test that passed yesterday against `--latency-ms 0`
fails today against `--latency-ms 50` for reasons that have nothing to do with
latency.

A workspace is one file, one seed, and one address table printed at startup.

## The seed the fault config used to eat

`start()` read `self.definition.faults.get(vs.name) or FaultConfig(seed=...)`.
The workspace seed reached a service **only when that service had no fault
override at all** -- because a `FaultConfig` written for latency carries the
default seed of 0, and `or` takes it whole.

So configuring latency on one service silently reseeded that service's data
generator, and a workspace whose entire premise is one seed across the set
quietly stopped having one for exactly the services somebody had configured.

The workspace seed always wins now. A per-service seed is deliberately not
offered: a set of services that reproduce independently is not a workspace, it
is several mocks in one file.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import yaml

from apiverity.core.model import Service
from apiverity.mock.server import FaultConfig, MockServer


@dataclass
class VirtualService:
    name: str
    service: Service
    port: int = 0  # 0 = ephemeral
    #: Where the contract was read from, when it came from a file. Carried so
    #: an artifact can name each contract it served rather than only the
    #: workspace that listed them.
    spec_path: str | None = None


@dataclass
class WorkspaceDefinition:
    name: str
    services: list[VirtualService] = field(default_factory=list)
    seed: int = 0
    faults: dict[str, FaultConfig] = field(default_factory=dict)  # per-service overrides


class VirtualizationWorkspace:
    """Starts/stops a coordinated set of mock servers deterministically."""

    def __init__(self, definition: WorkspaceDefinition) -> None:
        self.definition = definition
        self.servers: dict[str, MockServer] = {}

    def start(self) -> dict[str, str]:
        """Start all mocks; returns name -> base_url mapping."""
        for vs in self.definition.services:
            # `replace`, not `or`: a per-service fault config carries the
            # default seed of 0, so taking it whole meant configuring latency
            # on a service silently reseeded that service's data.
            faults = replace(
                self.definition.faults.get(vs.name) or FaultConfig(),
                seed=self.definition.seed,
            )
            server = MockServer(vs.service, port=vs.port, faults=faults)
            server.start()
            self.servers[vs.name] = server
        return {name: srv.base_url for name, srv in self.servers.items()}

    def stop(self) -> None:
        for server in self.servers.values():
            server.stop()
        self.servers.clear()

    def base_url(self, name: str) -> str:
        if name not in self.servers:
            raise KeyError(f"virtual service '{name}' is not running")
        return self.servers[name].base_url

    def __enter__(self) -> VirtualizationWorkspace:
        self.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.stop()


def workspace_from_services(
    name: str,
    services: list[Service],
    *,
    seed: int = 0,
) -> VirtualizationWorkspace:
    """Convenience builder from plain Service objects."""
    return VirtualizationWorkspace(
        WorkspaceDefinition(
            name=name,
            services=[VirtualService(name=svc.title, service=svc) for svc in services],
            seed=seed,
        )
    )


#: Fault keys a workspace file may set per service. `seed` is deliberately not
#: among them. Anything else is a typo, and a typo that silently did nothing
#: would leave somebody debugging a fault they believe is active.
FAULT_KEYS = ("force_status", "latency_ms", "malformed_json", "rate_limit_after")

_TOP_KEYS = ("name", "seed", "services")
_SERVICE_KEYS = ("faults", "name", "port", "spec")


class WorkspaceError(ValueError):
    """The workspace file could not be used as written."""


def _default_loader(spec_path: str) -> Service:
    from apiverity.specs.loader import detect_and_load

    service, _findings, _plugin = detect_and_load(spec_path)
    return service


def load_workspace(
    path: str | Path, *, loader: Callable[[str], Service] | None = None
) -> WorkspaceDefinition:
    """Read a workspace file, resolving every contract it names.

    Contract paths resolve relative to the workspace file rather than to the
    working directory, so a workspace checked into a repository works from
    anywhere in it -- the same rule the project config uses for its
    suppressions path.

    Every key is checked. An unknown one is an error rather than a warning, for
    the reason the project config gives: a key nobody reads is a setting the
    reader believes is active.
    """
    source = Path(path)
    try:
        raw = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise WorkspaceError(f"{source}: not valid YAML ({exc})") from exc
    if not isinstance(raw, dict):
        raise WorkspaceError(f"{source}: a workspace file is a mapping at the top level")

    unknown = sorted(set(raw) - set(_TOP_KEYS))
    if unknown:
        raise WorkspaceError(f"{source}: unknown key(s) {unknown}; known: {', '.join(_TOP_KEYS)}")

    entries = raw.get("services")
    if not isinstance(entries, list) or not entries:
        raise WorkspaceError(f"{source}: `services` must be a non-empty list")

    seed = raw.get("seed", 0)
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise WorkspaceError(f"{source}: `seed` must be an integer, got {type(seed).__name__}")

    read = loader or _default_loader
    definition = WorkspaceDefinition(name=str(raw.get("name") or source.stem), seed=seed)
    for index, entry in enumerate(entries):
        _read_service(definition, entry, index, source, read)
    return definition


def _read_service(
    definition: WorkspaceDefinition,
    entry: Any,
    index: int,
    source: Path,
    read: Callable[[str], Service],
) -> None:
    if not isinstance(entry, dict):
        raise WorkspaceError(f"{source}: services[{index}] is not a mapping")
    extra = sorted(set(entry) - set(_SERVICE_KEYS))
    if extra:
        raise WorkspaceError(
            f"{source}: services[{index}] has unknown key(s) {extra}; "
            f"known: {', '.join(_SERVICE_KEYS)}"
        )
    spec = entry.get("spec")
    if not spec:
        raise WorkspaceError(f"{source}: services[{index}] names no `spec`")

    name = str(entry.get("name") or Path(str(spec)).stem)
    if any(vs.name == name for vs in definition.services):
        # The name is how `base_url(name)` addresses a service and how the
        # printed table is read. Two of them is not an ambiguity to resolve by
        # picking one.
        raise WorkspaceError(f"{source}: two services are called {name!r}")

    resolved = Path(str(spec))
    if not resolved.is_absolute():
        # `normpath` rather than `resolve`: the `..` in `../apis/crud` has to
        # go, because the path is written into an artifact, and `resolve` would
        # write this machine's absolute path into one instead.
        resolved = Path(os.path.normpath(source.parent / resolved))
    if not resolved.exists():
        raise WorkspaceError(f"{source}: services[{index}] names {spec!r}, which is not there")

    definition.services.append(
        VirtualService(
            name=name,
            service=read(str(resolved)),
            port=int(entry.get("port", 0)),
            spec_path=str(resolved),
        )
    )

    faults = entry.get("faults")
    if faults is None:
        return
    if not isinstance(faults, dict):
        raise WorkspaceError(f"{source}: services[{index}].faults must be a mapping")
    bad = sorted(set(faults) - set(FAULT_KEYS))
    if bad:
        extra_note = (
            " -- a per-service seed would defeat the workspace's own" if "seed" in bad else ""
        )
        raise WorkspaceError(
            f"{source}: services[{index}].faults has unknown key(s) {bad}{extra_note}; "
            f"known: {', '.join(FAULT_KEYS)}"
        )
    definition.faults[name] = FaultConfig(**faults)


__all__ = [
    "FAULT_KEYS",
    "VirtualService",
    "VirtualizationWorkspace",
    "WorkspaceDefinition",
    "WorkspaceError",
    "load_workspace",
    "workspace_from_services",
]
