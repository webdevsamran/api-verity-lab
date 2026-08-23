"""Deterministic mock server generated from examples/schemas.

Binds to localhost by default. Optional development-only fault modes:
latency injection, forced status codes, malformed response bodies and
rate-limit simulation.
"""

from apiverity.mock.server import FaultConfig, MockServer, serve

__all__ = ["FaultConfig", "MockServer", "serve"]
