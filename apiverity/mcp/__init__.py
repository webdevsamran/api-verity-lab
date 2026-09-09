"""apiverity exposed to agents over the Model Context Protocol.

Distinct from `apiverity.specs.mcp`, which reads *other* servers' manifests as
a contract format. This package is the other direction: it lets an agent ask
apiverity whether a change is breaking.
"""

from __future__ import annotations

from .server import main, serve
from .tools import MCP_TOOLS_SCHEMA_VERSION, TOOLS

__all__ = ["MCP_TOOLS_SCHEMA_VERSION", "TOOLS", "main", "serve"]
