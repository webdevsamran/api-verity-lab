"""Service virtualization workspace.

Runs multiple dependent mock APIs from one workspace definition with a
shared deterministic seed so frontend/tests reproduce exactly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from apiverity.core.model import Service
from apiverity.mock.server import FaultConfig, MockServer


@dataclass
class VirtualService:
    name: str
    service: Service
    port: int = 0  # 0 = ephemeral


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
            faults = self.definition.faults.get(vs.name) or FaultConfig(seed=self.definition.seed)
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
