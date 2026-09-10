"""A workspace: several contracts, one seed, one address table.

`PRODUCT_GAPS.md` answers "why are there no hand-authored stub DSLs (WireMock
territory)" with "virtualization derives from contracts". The module that
sentence points at was reachable from no command until `mock --workspace`, and
the seed its docstring is built around reached a service only when that service
had no fault override -- so configuring latency on one silently reseeded its
data.

Both are what these tests are for.
"""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from apiverity.core.model import Operation, Protocol, Service
from apiverity.mock.server import FaultConfig
from apiverity.mock.virtualization import (
    FAULT_KEYS,
    VirtualizationWorkspace,
    VirtualService,
    WorkspaceDefinition,
    WorkspaceError,
    load_workspace,
)

_ROOT = Path(__file__).resolve().parents[2]
_FIXTURE = _ROOT / "fixtures" / "workspaces" / "checkout-stack.yaml"


def _service(title: str = "s") -> Service:
    return Service(
        title=title,
        version="1.0.0",
        protocol=Protocol.OPENAPI,
        operations=[Operation(method="GET", path="/x")],
    )


def _write(tmp_path: Path, document: Any) -> Path:
    path = tmp_path / "workspace.yaml"
    path.write_text(
        document if isinstance(document, str) else yaml.safe_dump(document), encoding="utf-8"
    )
    return path


def _loader(_path: str) -> Service:
    return _service()


# --------------------------------------------------------------- the seed


def test_a_service_with_faults_keeps_the_workspace_seed() -> None:
    """The defect. `faults.get(name) or FaultConfig(seed=...)` took a
    per-service config whole, and one written for latency carries the default
    seed of 0 -- so the one setting that must not vary across a workspace
    varied with whether somebody had configured that service."""
    definition = WorkspaceDefinition(
        name="w",
        seed=42,
        services=[VirtualService(name="a", service=_service("a"))],
        faults={"a": FaultConfig(latency_ms=5)},
    )
    workspace = VirtualizationWorkspace(definition)
    try:
        workspace.start()
        assert workspace.servers["a"].faults.seed == 42
        assert workspace.servers["a"].faults.latency_ms == 5
    finally:
        workspace.stop()


def test_every_service_gets_the_same_seed() -> None:
    definition = WorkspaceDefinition(
        name="w",
        seed=7,
        services=[VirtualService(name=n, service=_service(n)) for n in ("a", "b", "c")],
        faults={"b": FaultConfig(force_status=503)},
    )
    workspace = VirtualizationWorkspace(definition)
    try:
        workspace.start()
        assert {s.faults.seed for s in workspace.servers.values()} == {7}
    finally:
        workspace.stop()


def test_a_per_service_seed_is_refused_by_the_file_format(tmp_path: Path) -> None:
    """A set of services that reproduce independently is not a workspace, it
    is several mocks in one file."""
    assert "seed" not in FAULT_KEYS
    path = _write(tmp_path, {"services": [{"spec": "a.yaml", "faults": {"seed": 1}}]})
    (tmp_path / "a.yaml").write_text("{}", encoding="utf-8")
    with pytest.raises(WorkspaceError, match="defeat the workspace"):
        load_workspace(path, loader=_loader)


# --------------------------------------------------------------- the file


def test_the_bundled_fixture_loads_with_its_seed_and_faults() -> None:
    definition = load_workspace(_FIXTURE)
    assert definition.name == "checkout-stack"
    assert definition.seed == 42
    assert [s.name for s in definition.services] == ["users", "catalogue", "billing"]
    assert definition.faults["billing"].latency_ms == 120


def test_contract_paths_resolve_against_the_workspace_file_not_the_cwd() -> None:
    """A workspace checked into a repository has to work from anywhere in it --
    the rule the project config already uses for its suppressions path."""
    paths = [s.spec_path for s in load_workspace(_FIXTURE).services]
    assert all(p and "workspaces" not in p and ".." not in p for p in paths)
    assert all(Path(p).exists() for p in paths if p)


def test_a_service_takes_its_name_from_the_file_when_none_is_given(tmp_path: Path) -> None:
    (tmp_path / "billing.yaml").write_text("{}", encoding="utf-8")
    path = _write(tmp_path, {"services": [{"spec": "billing.yaml"}]})
    assert [s.name for s in load_workspace(path, loader=_loader).services] == ["billing"]


@pytest.mark.parametrize(
    ("document", "message"),
    [
        ({"servcies": []}, "unknown key"),
        ({"services": []}, "non-empty list"),
        ({"services": {}}, "non-empty list"),
        ({"seed": "42", "services": [{"spec": "a.yaml"}]}, "`seed` must be an integer"),
        ({"services": [{"port": 1}]}, "names no `spec`"),
        ({"services": [{"spec": "a.yaml", "prot": 1}]}, "unknown key"),
        ({"services": ["a.yaml"]}, "is not a mapping"),
        ({"services": [{"spec": "a.yaml", "faults": 3}]}, "faults must be a mapping"),
        ({"services": [{"spec": "a.yaml", "faults": {"latencyms": 5}}]}, "unknown key"),
        ({"services": [{"spec": "gone.yaml"}]}, "which is not there"),
        ("- a\n- b\n", "mapping at the top level"),
        ("services: [\n", "not valid YAML"),
    ],
)
def test_what_the_file_refuses(tmp_path: Path, document: Any, message: str) -> None:
    """Every key is checked, for the reason the project config gives: a key
    nobody reads is a setting the reader believes is active."""
    (tmp_path / "a.yaml").write_text("{}", encoding="utf-8")
    with pytest.raises(WorkspaceError, match=message):
        load_workspace(_write(tmp_path, document), loader=_loader)


def test_two_services_with_the_same_name_are_refused(tmp_path: Path) -> None:
    """The name is how `base_url(name)` addresses a service and how the printed
    table is read. Two of them is not an ambiguity to resolve by picking one."""
    (tmp_path / "a.yaml").write_text("{}", encoding="utf-8")
    (tmp_path / "b.yaml").write_text("{}", encoding="utf-8")
    path = _write(
        tmp_path,
        {"services": [{"name": "api", "spec": "a.yaml"}, {"name": "api", "spec": "b.yaml"}]},
    )
    with pytest.raises(WorkspaceError, match="two services are called 'api'"):
        load_workspace(path, loader=_loader)


def test_an_unknown_service_address_is_an_error_not_an_empty_string() -> None:
    workspace = VirtualizationWorkspace(WorkspaceDefinition(name="w"))
    with pytest.raises(KeyError, match="is not running"):
        workspace.base_url("nope")


# ------------------------------------------------------------ the command


def _run(argv: list[str]) -> tuple[int, str, dict[str, Any]]:
    import apiverity.cli.commands.testing as testing
    from apiverity.cli.main import main

    original = testing._block
    testing._block = lambda: None  # the servers are up; do not wait for Ctrl+C
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(argv)
    finally:
        testing._block = original
    try:
        return code, err.getvalue(), json.loads(out.getvalue())
    except ValueError:
        return code, err.getvalue(), {"_text": out.getvalue()}


def test_the_command_prints_an_address_for_every_service() -> None:
    """Printed before the servers block, and to stdout: ports may be
    ephemeral, and a workspace whose addresses appear only after Ctrl+C is a
    workspace nothing can connect to."""
    code, _err, payload = _run(["--no-config", "mock", "--workspace", str(_FIXTURE), "--json"])
    assert code == 0
    names = [s["name"] for s in payload["services"]]
    assert names == ["users", "catalogue", "billing"]
    assert all(s["base_url"].startswith("http://127.0.0.1:") for s in payload["services"])
    assert payload["seed"] == 42


def test_the_artifact_names_every_contract_it_served() -> None:
    """One run served three contracts, so no single `contract_hash` names what
    was served. The workspace file that named all three does, and each service
    carries its own."""
    _code, _err, payload = _run(["--no-config", "mock", "--workspace", str(_FIXTURE), "--json"])
    assert payload["contract_hash"] != "0" * 64
    assert payload["protocol_version"] == "workspace"
    hashes = {s["contract_hash"] for s in payload["services"]}
    assert len(hashes) == 3
    assert all(len(h) == 64 for h in hashes)


def test_the_seed_is_reported_once_rather_than_per_service() -> None:
    """Repeating it per service would suggest it can differ, and it is exactly
    the thing that must not."""
    _code, _err, payload = _run(["--no-config", "mock", "--workspace", str(_FIXTURE), "--json"])
    assert "seed" in payload
    assert all("seed" not in s["faults"] for s in payload["services"])


def test_the_text_table_shows_the_faults_that_are_set() -> None:
    _code, _err, payload = _run(["--no-config", "mock", "--workspace", str(_FIXTURE)])
    text = payload["_text"]
    assert "workspace 'checkout-stack', seed 42" in text
    assert "latency_ms" in text and "rate_limit_after" in text
    assert text.count("http://127.0.0.1:") == 3


def test_a_workspace_and_a_spec_together_are_refused() -> None:
    """Two different answers to "what is being served". Picking one silently is
    how somebody ends up debugging a service that is not running."""
    code, err, _payload = _run(
        ["--no-config", "mock", "fixtures/apis/crud/openapi.yaml", "--workspace", str(_FIXTURE)]
    )
    assert code != 0
    assert "drop the" in err


def test_mock_with_neither_says_what_to_pass() -> None:
    code, err, _payload = _run(["--no-config", "mock"])
    assert code != 0
    assert "--workspace FILE" in err


def test_a_broken_workspace_file_is_a_usage_error_not_a_traceback(tmp_path: Path) -> None:
    path = _write(tmp_path, {"services": [{"spec": "gone.yaml"}]})
    code, err, _payload = _run(["--no-config", "mock", "--workspace", str(path)])
    assert code != 0
    assert "which is not there" in err
