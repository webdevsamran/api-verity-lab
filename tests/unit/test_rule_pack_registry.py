"""The entry-point group that was published, listed, and loaded into nothing.

`apiverity.rules` has existed since the plugin registry did. `apiverity plugins`
listed it. `PolicyEngine` ran a hard-coded pair of built-in packs, so a team's
own pack had no way in short of editing this package.
"""

from __future__ import annotations

import contextlib
import io
import json
from typing import Any

from apiverity.cli.commands.common import EXIT_FINDINGS, EXIT_OK
from apiverity.cli.main import main
from apiverity.core.model import Finding, Protocol, Service, Severity
from apiverity.rules.packs_registry import discover
from apiverity.rules.policy import RuleDefinition, RulePack


class _Entry:
    """An entry point, without needing a distribution installed."""

    def __init__(self, name: str, value: str, loader: Any, dist: Any = None) -> None:
        self.name = name
        self.value = value
        self.dist = dist
        self._loader = loader

    def load(self) -> Any:
        return self._loader()


class _Dist:
    def __init__(self, name: str, version: str) -> None:
        self.name = name
        self.version = version


def _pack(name: str, rule_ids: list[str], version: str = "1.0.0") -> RulePack:
    return RulePack(
        name=name,
        version=version,
        description=f"{name} rules",
        rules=tuple(
            RuleDefinition(
                rule_id=rule_id,
                severity=Severity.WARN,
                rationale="because",
                remediation="do the other thing",
                check=lambda svc, rid=rule_id: [
                    Finding(rule_id=rid, severity=Severity.WARN, message="fired")
                ],
            )
            for rule_id in rule_ids
        ),
    )


def _run(argv: list[str]) -> tuple[int, dict[str, Any]]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        code = main(argv)
    text = out.getvalue()
    return code, (json.loads(text) if text.strip().startswith("{") else {})


# --------------------------------------------------------------- discovery


def test_the_built_in_packs_are_found() -> None:
    registry = discover(entry_points=[])
    names = {d.pack.name for d in registry.packs}
    assert names == {"apiverity-governance", "apiverity-security"}
    assert all(d.source == "built-in" for d in registry.packs)


def test_a_third_party_pack_is_found_and_attributed() -> None:
    """Where it came from is the question a list of rule ids cannot answer."""
    entry = _Entry(
        "acme",
        "acme_rules:pack",
        lambda: _pack("acme-house", ["ACME-ONE"]),
        dist=_Dist("acme-apiverity-rules", "2.1.0"),
    )
    registry = discover(entry_points=[entry])
    found = next(d for d in registry.packs if d.pack.name == "acme-house")
    assert found.source == "acme-apiverity-rules 2.1.0"
    assert found.entry_point == "acme"


def test_an_entry_point_with_no_distribution_falls_back_to_its_module() -> None:
    entry = _Entry("local", "my_rules:pack", lambda: _pack("local-pack", ["LOCAL-ONE"]))
    found = next(d for d in discover(entry_points=[entry]).packs if d.pack.name == "local-pack")
    assert found.source == "my_rules"


def test_a_pack_object_works_as_well_as_a_factory() -> None:
    pack = _pack("direct", ["DIRECT-ONE"])
    entry = _Entry("direct", "m:pack", lambda: pack)
    assert any(d.pack is pack for d in discover(entry_points=[entry]).packs)


# ----------------------------------------------- what it refuses to hide


def test_a_pack_that_raises_on_load_is_named_not_skipped() -> None:
    """A team whose pack raises should find out here, not believe it is running."""

    def explode() -> Any:
        raise RuntimeError("no such module")

    registry = discover(entry_points=[_Entry("broken", "broken:pack", explode)])
    assert registry.failed == [
        {
            "entry_point": "broken",
            "value": "broken:pack",
            "error": "RuntimeError: no such module",
        }
    ]
    assert not any(d.entry_point == "broken" for d in registry.packs)


def test_a_conflicting_rule_id_names_both_packs() -> None:
    """`PolicyEngine` raises on this, which is right for the engine and wrong
    for a listing: one bad pack should not stop the listing saying which."""
    entries = [
        _Entry("a", "a:pack", lambda: _pack("pack-a", ["DUPLICATE-ID"])),
        _Entry("b", "b:pack", lambda: _pack("pack-b", ["DUPLICATE-ID"])),
    ]
    registry = discover(include_builtin=False, entry_points=entries)
    assert registry.conflicts == {"DUPLICATE-ID": ["pack-a@1.0.0", "pack-b@1.0.0"]}


def test_a_conflict_does_not_drop_either_side() -> None:
    """Silently dropping one would run a gate nobody configured."""
    entries = [
        _Entry("a", "a:pack", lambda: _pack("pack-a", ["DUPLICATE-ID"])),
        _Entry("b", "b:pack", lambda: _pack("pack-b", ["DUPLICATE-ID"])),
    ]
    registry = discover(include_builtin=False, entry_points=entries)
    assert len(registry.runnable) == 2


def test_a_non_pack_entry_point_is_ignored_rather_than_reported() -> None:
    """`apiverity.rules` also publishes the breaking-rule catalogue, as a dict.

    Reporting "not a RulePack" about the project's own entry point would be a
    false alarm on every installation there is.
    """
    entry = _Entry("core", "apiverity.plugins.builtins:core_rules", lambda: lambda: {"BRK-X": 1})
    registry = discover(include_builtin=False, entry_points=[entry])
    assert registry.packs == []
    assert registry.failed == []


# ------------------------------------------------------------- it actually runs


def test_a_discovered_pack_reaches_the_security_check_run(monkeypatch: Any) -> None:
    """The point of the whole unit: before this, a third-party pack was
    discovered by `apiverity plugins` and run by nothing."""
    import apiverity.rules.packs_registry as registry_module
    from apiverity.security import run_security_checks

    pack = _pack("acme-house", ["ACME-FIRED"])
    monkeypatch.setattr(
        registry_module,
        "discover",
        lambda **kw: registry_module.Registry(
            packs=[registry_module.Discovered(pack=pack, source="test")]
        ),
    )
    service = Service(title="t", version="1", protocol=Protocol.OPENAPI)
    assert "ACME-FIRED" in {f.rule_id for f in run_security_checks(service)}


# ------------------------------------------------------------------ the command


def test_rules_packs_lists_what_is_installed() -> None:
    code, payload = _run(["rules", "--packs", "--json"])
    assert code == EXIT_OK
    assert {p["name"] for p in payload["packs"]} == {
        "apiverity-governance",
        "apiverity-security",
    }
    assert payload["rules"] == sum(p["rules"] for p in payload["packs"])
    assert payload["conflicts"] == {}
    assert payload["failed"] == []


def test_rules_packs_fails_when_something_needs_attention(monkeypatch: Any) -> None:
    import apiverity.rules.packs_registry as registry_module

    monkeypatch.setattr(
        registry_module,
        "discover",
        lambda **kw: registry_module.Registry(
            failed=[{"entry_point": "x", "value": "x:y", "error": "ImportError: no"}]
        ),
    )
    code, payload = _run(["rules", "--packs", "--json"])
    assert code == EXIT_FINDINGS
    assert payload["failed"][0]["entry_point"] == "x"


def test_the_plain_rules_listing_is_unchanged() -> None:
    code, payload = _run(["rules", "--json"])
    assert code == EXIT_OK
    assert "packs" not in payload
