"""Self-hosted server package (modular monolith)."""

from apiverity.server.api import create_app
from apiverity.server.store import Store

__all__ = ["Store", "create_app"]
