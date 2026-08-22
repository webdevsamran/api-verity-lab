"""Plugin discovery via importlib entry points.

Six versioned groups: apiverity.specs / rules / checks / generators /
exporters / transports. Plugin API contract version is ``1``; see
docs/plugins.md.
"""
from __future__ import annotations

PLUGIN_API_VERSION = 1

ENTRY_POINT_GROUPS = [
    "apiverity.specs",
    "apiverity.rules",
    "apiverity.checks",
    "apiverity.generators",
    "apiverity.exporters",
    "apiverity.transports",
]


def list_entry_points() -> dict[str, list[dict[str, str]]]:
    from importlib.metadata import entry_points

    out: dict[str, list[dict[str, str]]] = {}
    for group in ENTRY_POINT_GROUPS:
        try:
            eps = entry_points(group=group)
        except TypeError:  # pragma: no cover - older Python fallback
            eps = entry_points().get(group, [])
        out[group] = [{"name": ep.name, "value": ep.value} for ep in eps]
    return out


class PluginRegistry:
    """Loads and caches plugins for a given entry-point group."""

    def __init__(self, group: str) -> None:
        self.group = group
        self._plugins: list[tuple[str, object]] | None = None

    def load(self) -> list[tuple[str, object]]:
        if self._plugins is None:
            self._plugins = load_group(self.group)
        return self._plugins

    def instances(self) -> list[object]:
        return [factory() if callable(factory) else factory for _, factory in self.load()]


def load_group(group: str) -> list[tuple[str, object]]:
    """Load all registered plugins for a group."""
    from importlib.metadata import entry_points

    if group not in ENTRY_POINT_GROUPS:
        raise ValueError(f"unknown entry point group '{group}'")
    loaded = []
    try:
        eps = entry_points(group=group)
    except TypeError:  # pragma: no cover
        eps = entry_points().get(group, [])
    for ep in eps:
        loaded.append((ep.name, ep.load()))
    return loaded