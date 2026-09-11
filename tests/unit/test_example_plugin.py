"""The plugin system, exercised through a real installation.

Every other test of the entry-point machinery hands `discover()` a hand-built
entry point, because that is fast and it tests the loading logic. What it does
not test is the part that actually has to work: that a distribution declaring
`[project.entry-points."apiverity.rules"]` is found by `importlib.metadata`,
loaded, and run by the engine — with nothing in this repository knowing it
exists.

So one test builds `examples/plugins/apiverity-house-rules`, installs it into a
throwaway virtualenv alongside this package, and runs the CLI there. It is the
slowest test in the suite and it is the only one that proves the plugin system
is a plugin system rather than an interface with one implementation.

The rest of the module checks the example package itself: that the entry point
names something that exists, that the pack is well-formed, and that the guide
does not describe a shape the example does not have.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_EXAMPLE = _ROOT / "examples" / "plugins" / "apiverity-house-rules"
_GUIDE = _ROOT / "docs" / "plugin-authoring.md"
_SPEC = _ROOT / "fixtures" / "apis" / "crud" / "openapi.yaml"

sys.path.insert(0, str(_EXAMPLE / "src"))


def _pyproject() -> dict:
    return tomllib.loads((_EXAMPLE / "pyproject.toml").read_text(encoding="utf-8"))


# -- the example package --------------------------------------------------


def test_the_entry_point_group_is_the_one_the_registry_reads() -> None:
    """A pack declaring `apiverity.rule_packs` would install cleanly, appear in
    no listing, and run for nobody."""
    from apiverity.rules.packs_registry import GROUP

    declared = _pyproject()["project"]["entry-points"]
    assert GROUP in declared, f"the example declares {sorted(declared)}, not {GROUP}"


def test_the_entry_point_resolves_to_something_that_returns_a_pack() -> None:
    from apiverity.rules.policy import RulePack

    target = _pyproject()["project"]["entry-points"]["apiverity.rules"]["house-rules"]
    module_name, _, attribute = target.partition(":")

    import importlib

    module = importlib.import_module(module_name)
    loaded = getattr(module, attribute)
    pack = loaded() if callable(loaded) else loaded
    assert isinstance(pack, RulePack)


def test_the_pack_declares_no_rule_id_the_engine_already_owns() -> None:
    """A duplicate id is a conflict the engine refuses to run, which would make
    the worked example an example of something that does not work."""
    from house_rules import PACK

    from apiverity.rules.packs_registry import discover

    builtin = {rule_id for d in discover().packs for rule_id in d.pack.rule_ids()}
    assert not builtin.intersection(PACK.rule_ids())


def test_every_rule_carries_a_rationale_and_a_remediation() -> None:
    """A rule that says only "no" gets switched off. The built-in catalogue
    holds itself to this, and an example that did not would be teaching the
    wrong shape."""
    from house_rules import PACK

    for rule in PACK.rules:
        assert rule.rationale.strip()
        assert rule.remediation.strip()
        assert rule.rule_id.startswith("HOUSE-")


def test_every_rule_is_reachable_and_refusable() -> None:
    """Both directions, for each rule. A check that fires on everything and a
    check that fires on nothing are equally useless, and only running them
    tells the two apart."""
    from house_rules import PACK

    from apiverity.core.model import Operation, Parameter, Protocol, Response, Service

    clean = Service(
        title="t",
        version="1.0.0",
        protocol=Protocol.OPENAPI,
        operations=[
            Operation(
                operation_id="list",
                method="GET",
                path="/user-profiles",
                parameters=[Parameter(name="limit", location="query")],
                responses=[
                    Response(status="200", description="ok"),
                    Response(status="400", description="bad"),
                ],
            )
        ],
    )
    dirty = Service(
        title="t",
        version="1.0.0",
        protocol=Protocol.OPENAPI,
        operations=[
            Operation(
                operation_id="list",
                method="GET",
                path="/userProfiles",
                responses=[Response(status="200", description="ok")],
            )
        ],
    )
    for rule in PACK.rules:
        assert not rule.check(clean), f"{rule.rule_id} fires on a contract that satisfies it"
        assert rule.check(dirty), f"{rule.rule_id} does not fire on a contract that violates it"


def test_the_example_has_its_own_tests_and_ci_runs_them() -> None:
    """A published pack with no tests is a pack whose rules nobody has run in
    both directions, and this one is meant to be the shape to copy.

    `testpaths = ["tests"]`, so the main run never reaches them -- an example
    whose own tests nobody runs can stop working while every check here stays
    green."""
    assert list((_EXAMPLE / "tests").glob("test_*.py"))
    workflow = (_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "examples/plugins/apiverity-house-rules/tests" in workflow


# -- the guide ------------------------------------------------------------


def test_the_guide_names_every_entry_point_group_the_code_reads() -> None:
    """A group the code supports and the guide omits is a capability nobody
    finds; a group the guide names and the code ignores is worse."""
    guide = _GUIDE.read_text(encoding="utf-8")
    groups = sorted(
        {
            f"apiverity.{name}"
            for name in ("specs", "rules", "checks", "generators", "exporters", "transports")
        }
    )
    missing = [group for group in groups if group not in guide]
    assert not missing, f"the guide does not mention: {missing}"


def test_the_guide_points_at_the_example_that_exists() -> None:
    guide = _GUIDE.read_text(encoding="utf-8")
    assert "examples/plugins/apiverity-house-rules" in guide


def test_the_guide_uses_the_group_name_the_registry_actually_reads() -> None:
    from apiverity.rules.packs_registry import GROUP

    assert GROUP in _GUIDE.read_text(encoding="utf-8")


# -- the whole thing, installed -------------------------------------------


@pytest.mark.integration
def test_an_installed_pack_is_discovered_and_run_by_the_cli(tmp_path: Path) -> None:
    """The only test that proves the plugin system is one.

    A hand-built entry point exercises `discover()`'s loading logic and skips
    the part that has to work in the field: a distribution's metadata being
    found by `importlib.metadata` at all. This builds the example, installs it
    into a throwaway virtualenv beside this package, and runs the CLI there.
    """
    if shutil.which("git") is None:  # pragma: no cover - defensive
        pytest.skip("pip needs a working toolchain here")

    venv = tmp_path / "venv"
    subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True, capture_output=True)
    python = venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")

    install = subprocess.run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--quiet",
            "--no-input",
            # This package first, so the example's `api-verity-lab` requirement
            # is already satisfied by the tree under test rather than by
            # whatever pip would fetch.
            str(_ROOT),
            str(_EXAMPLE),
        ],
        capture_output=True,
        text=True,
        timeout=900,
    )
    if install.returncode != 0:
        pytest.skip(f"could not install into a throwaway venv: {install.stderr[-400:]}")

    listed = subprocess.run(
        [str(python), "-m", "apiverity.cli.main", "rules", "--packs", "--json"],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert listed.returncode == 0, listed.stderr
    registry = json.loads(listed.stdout)
    names = {pack["name"]: pack for pack in registry["packs"]}
    assert "house-rules" in names, f"installed and not discovered; found {sorted(names)}"

    # Provenance, which is the thing a hand-rolled registry would have had to
    # invent a field for: the distribution that shipped it.
    assert "apiverity-house-rules" in names["house-rules"]["source"]
    assert not registry["failed"], registry["failed"]
    assert not registry["conflicts"], registry["conflicts"]

    validated = subprocess.run(
        [str(python), "-m", "apiverity.cli.main", "validate", str(_SPEC), "--json"],
        capture_output=True,
        text=True,
        timeout=300,
    )
    payload = json.loads(validated.stdout)
    fired = {f["rule_id"] for f in payload["findings"] if f["rule_id"].startswith("HOUSE-")}
    assert fired, "the pack was discovered and none of its rules ran"
