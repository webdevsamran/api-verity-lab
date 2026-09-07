"""Tests for plugin API v2: manifests, isolation, conformance kit, scaffold."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from apiverity.core.model import Finding, Service
from apiverity.plugins.conformance import conformance_report, run_conformance
from apiverity.plugins.scaffold import scaffold_plugin
from apiverity.plugins.v2 import (
    HOST_PLUGIN_API_VERSION,
    PluginManager,
    PluginManifest,
)


class GoodPlugin:
    def __init__(self) -> None:
        self.manifest = PluginManifest(
            name="good-rules",
            version="1.0.0",
            capabilities=["rules"],
            entry_point="good_plugin_mod:INSTANCE",
        )

    def check(self, service: object) -> list[Finding]:
        return []


class BadPlugin:
    def __init__(self) -> None:
        self.manifest = PluginManifest(
            name="bad",
            version="0.0.1",
            capabilities=["rules"],
            entry_point="no.such.module:Thing",
        )


class TestManifest:
    def test_capability_validation(self) -> None:
        m = PluginManifest(
            name="x", version="1", entry_point="a:b", capabilities=["rules", "warp_drive"]
        )
        assert m.validate_capabilities() == ["warp_drive"]

    def test_host_negotiation(self) -> None:
        ok = PluginManifest(name="x", version="1", entry_point="a:b", api_version="2.3")
        bad = PluginManifest(name="y", version="1", entry_point="a:b", api_version="3.0")
        junk = PluginManifest(name="z", version="1", entry_point="a:b", api_version="banana")
        assert ok.supports_host()
        assert not bad.supports_host()
        assert not junk.supports_host()


def _install_good_module(tmp_path: Path) -> str:
    """Write a tiny importable module exposing a GoodPlugin instance."""
    lines = [
        "from apiverity.plugins.v2 import PluginManifest",
        "MANIFEST = PluginManifest(name='good-rules', version='1.0.0',",
        "                          capabilities=['rules'],",
        "                          entry_point='good_plugin_mod:INSTANCE')",
        "class Impl:",
        "    manifest = MANIFEST",
        "    def check(self, service):",
        "        return []",
        "INSTANCE = Impl()",
    ]
    (tmp_path / "good_plugin_mod.py").write_text(chr(10).join(lines), encoding="utf-8")
    return str(tmp_path)


class TestPluginManager:
    def test_load_isolated_failure(self) -> None:
        mgr = PluginManager()
        result = mgr.load_from_manifest(BadPlugin().manifest)
        assert result is None
        diag = mgr.diagnostics[-1]
        assert not diag.ok
        assert diag.error and "No module named" in diag.error
        assert diag.traceback  # full traceback captured for diagnostics

    def test_successful_load_and_capability_index(self, tmp_path: Path) -> None:
        sys.path.insert(0, _install_good_module(tmp_path))
        try:
            mgr = PluginManager()
            loaded = mgr.load_from_manifest(GoodPlugin().manifest)
            assert loaded is not None
            assert mgr.by_capability("rules") == [loaded]
            assert mgr.by_capability("exporters") == []
        finally:
            sys.path.remove(str(tmp_path))
            sys.modules.pop("good_plugin_mod", None)

    def test_call_isolation(self, tmp_path: Path) -> None:
        sys.path.insert(0, _install_good_module(tmp_path))
        try:
            mgr = PluginManager()
            loaded = mgr.load_from_manifest(GoodPlugin().manifest)
            assert loaded is not None
            result, err = mgr.call_isolated(
                loaded, "check", Service(title="t", version="1", protocol="openapi")
            )
            assert err is None and result == []
        finally:
            sys.path.remove(str(tmp_path))
            sys.modules.pop("good_plugin_mod", None)


class TestConformance:
    def test_good_plugin_conforms(self) -> None:
        assert run_conformance(GoodPlugin()) == []
        report = conformance_report(GoodPlugin())
        assert report["conforms"] is True
        assert report["plugin"] == "good-rules"

    def test_missing_manifest(self) -> None:
        failures = run_conformance(object())
        assert any("manifest" in f for f in failures)

    def test_bad_api_version_flagged(self) -> None:
        class Old:
            manifest = PluginManifest(
                name="o", version="1", entry_point="a:b", api_version="1.0", capabilities=["rules"]
            )

            def check(self, service: object) -> list[Finding]:
                return []

        failures = run_conformance(Old())
        assert any("api_version" in f for f in failures)

    def test_nondeterministic_check_flagged(self) -> None:
        import random

        class Flaky:
            manifest = GoodPlugin().manifest

            def check(self, service: object) -> list[Finding]:
                if random.random() < 0.5:
                    return [Finding(rule_id="X", severity="INFO", message="m")]
                return []

        # With enough trials the determinism probe must eventually catch it.
        caught = False
        for _ in range(50):
            if run_conformance(Flaky()):
                caught = True
                break
        assert caught


def test_scaffold_creates_conforming_plugin(tmp_path: Path) -> None:
    pkg = scaffold_plugin("acme-lint", tmp_path, description="Acme lint pack")
    assert (pkg / "plugin.py").exists()
    assert (pkg / "tests").is_dir()
    # Import the generated plugin and verify conformance.
    sys.path.insert(0, str(tmp_path))
    try:
        mod = (
            pytest.importorskip("acme_lint.plugin")
            if False
            else __import__("acme_lint.plugin", fromlist=["AcmeLint"])
        )
        instance = mod.AcmeLint()
        assert conformance_report(instance)["conforms"] is True
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop("acme_lint.plugin", None)
        sys.modules.pop("acme_lint", None)


def test_host_version_constant() -> None:
    assert HOST_PLUGIN_API_VERSION.startswith("2.")
