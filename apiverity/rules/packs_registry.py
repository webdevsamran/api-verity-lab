"""Finding the rule packs a machine has, and saying where each came from.

`PolicyEngine` runs whatever list of packs it is handed, and the only callers
hand it the two built-in ones. A team's own pack had no way in short of editing
this package — so the `apiverity.rules` entry-point group existed, was listed
by `apiverity plugins`, and loaded nothing into the engine.

## There is no registry to run, and that is the design

"Publish and discover, npm-style" does not need a server here. A rule pack is
Python, Python already has a distribution channel, and a pack published to PyPI
declaring an `apiverity.rules` entry point is discoverable by every installation
that pip-installs it. Inventing a second index would mean operating one.

So discovery is `importlib.metadata`, and `apiverity rules --packs` is the
listing. Provenance is the distribution name and version, which is what a
reader needs to answer "where did this rule come from" and is exactly what a
hand-rolled registry would have had to invent a field for.

## Conflicts are reported, not raised

`PolicyEngine.__init__` raises `ValueError` on a duplicate rule id across packs.
That is right for the engine — two rules with one id cannot both be explained —
and wrong for the listing, because it means one badly-behaved third-party pack
makes `apiverity rules --packs` fail to tell you *which* pack is the problem.

:func:`discover` reports conflicts as data. The engine still refuses to run
them; the listing still tells you why.

## A pack that will not load is named

An entry point pointing at a module that raises on import, or at a factory that
returns something which is not a `RulePack`, is a fact about this installation.
Skipping it silently would leave a team believing their pack is running.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from apiverity.rules.policy import DEFAULT_PACK, RulePack

#: The entry-point group a distribution declares to ship rule packs.
GROUP = "apiverity.rules"


@dataclass
class Discovered:
    """One pack, and where it came from."""

    pack: RulePack
    #: `built-in`, or the distribution that provided it.
    source: str
    #: The entry-point name, for a pack that came from one.
    entry_point: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.pack.name,
            "version": self.pack.version,
            "description": self.pack.description,
            "source": self.source,
            **({"entry_point": self.entry_point} if self.entry_point else {}),
            "rules": len(self.pack.rules),
            "rule_ids": self.pack.rule_ids(),
        }


@dataclass
class Registry:
    """Every pack this installation can run."""

    packs: list[Discovered] = field(default_factory=list)
    #: rule id -> the packs claiming it, when more than one does.
    conflicts: dict[str, list[str]] = field(default_factory=dict)
    #: Entry points that did not produce a pack, with the reason.
    failed: list[dict[str, str]] = field(default_factory=list)

    @property
    def runnable(self) -> list[RulePack]:
        """The packs, in a form `PolicyEngine` takes.

        Excludes nothing on account of a conflict: the engine's own refusal is
        the right place for that, and silently dropping one side of a clash
        would run a gate nobody configured.
        """
        return [d.pack for d in self.packs]

    def as_dict(self) -> dict[str, Any]:
        return {
            "packs": [d.as_dict() for d in self.packs],
            "rules": sum(len(d.pack.rules) for d in self.packs),
            # Named rather than counted: "one conflict" does not tell anybody
            # which rule or which packs.
            "conflicts": self.conflicts,
            "failed": self.failed,
        }


def _distribution_for(entry_point: Any) -> str:
    """The distribution that shipped this entry point, if it says.

    `EntryPoint.dist` is populated when the entry point came from installed
    metadata and absent when it was constructed by hand, which is what a test
    does -- so this falls back to the module path rather than raising.
    """
    dist = getattr(entry_point, "dist", None)
    if dist is not None:
        name = getattr(dist, "name", None)
        version = getattr(dist, "version", None)
        if name:
            return f"{name} {version}" if version else str(name)
    value = str(getattr(entry_point, "value", "") or "")
    return value.split(":")[0] or "unknown"


def discover(*, include_builtin: bool = True, entry_points: Any = None) -> Registry:
    """Every rule pack this installation has.

    `entry_points` is injected for tests. Nothing else passes it: production
    discovery is `importlib.metadata` and only that.
    """
    registry = Registry()
    if include_builtin:
        registry.packs.append(Discovered(pack=DEFAULT_PACK, source="built-in"))
        from apiverity.security.packs import SECURITY_PACK

        registry.packs.append(Discovered(pack=SECURITY_PACK, source="built-in"))

    if entry_points is None:
        from importlib.metadata import entry_points as _eps

        try:
            found = list(_eps(group=GROUP))
        except TypeError:  # pragma: no cover - older Python fallback
            found = list(_eps().get(GROUP, []))  # type: ignore[attr-defined]
    else:
        found = list(entry_points)

    for entry in found:
        try:
            loaded = entry.load()
            pack = loaded() if callable(loaded) else loaded
        except Exception as exc:
            # Named, never skipped. A team whose pack raises on import should
            # find that out here rather than believe it is running.
            registry.failed.append(
                {
                    "entry_point": str(getattr(entry, "name", "?")),
                    "value": str(getattr(entry, "value", "?")),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            continue
        if not isinstance(pack, RulePack):
            # `apiverity.rules` is also how the built-in *catalogue* is
            # published (a dict of breaking rules), so a non-pack here is
            # expected rather than broken -- and saying "not a RulePack" about
            # the project's own entry point would be a false alarm on every
            # installation.
            continue
        registry.packs.append(
            Discovered(
                pack=pack,
                source=_distribution_for(entry),
                entry_point=str(getattr(entry, "name", "?")),
            )
        )

    seen: dict[str, list[str]] = {}
    for discovered in registry.packs:
        label = f"{discovered.pack.name}@{discovered.pack.version}"
        for rule_id in discovered.pack.rule_ids():
            seen.setdefault(rule_id, []).append(label)
    registry.conflicts = {rule: packs for rule, packs in seen.items() if len(packs) > 1}
    return registry


__all__ = ["GROUP", "Discovered", "Registry", "discover"]
