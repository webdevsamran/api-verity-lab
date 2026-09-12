"""The contract gate blocked a merge over a file that is not a contract.

`fixtures/apis/**` holds two kinds of file: standalone contracts, and the
`$ref` fragments those contracts point at -- `shared/error.yaml`,
`multifile/schemas/order.yaml`, and five more. The gate collected every changed
YAML and JSON under that tree and handed each to `apiverity validate`, which
exits 2 on a fragment with "not an API contract".

So a pull request touching a shared schema failed a required-looking check over
a file that has no `openapi:` key because it was never meant to have one, and
is already validated through the document that references it.

`.github/scripts/changed_contracts.py` filters the list. The half worth testing
is not that it drops fragments -- it is that it drops *only* fragments: a
malformed contract, an unreadable file, a format that failed to parse, all have
to reach the gate, because a filter that swallows those turns a red gate green
without changing a thing about the code.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / ".github" / "scripts" / "changed_contracts.py"

#: Real files from this repository, so the test moves when the fixtures do.
_CONTRACT = "fixtures/apis/lint/openapi.yaml"
_FRAGMENT = "fixtures/apis/shared/error.yaml"


def _module() -> Any:
    spec = importlib.util.spec_from_file_location("changed_contracts", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["changed_contracts"] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop("changed_contracts", None)
    return module


@pytest.fixture(scope="module")
def filter_module() -> Any:
    return _module()


def test_the_fixtures_this_test_relies_on_are_still_what_it_thinks() -> None:
    """Named rather than discovered, so the test says what it is about -- and
    checked, so it fails loudly if either file moves."""
    assert (_ROOT / _CONTRACT).is_file()
    assert (_ROOT / _FRAGMENT).is_file()
    assert "openapi:" in (_ROOT / _CONTRACT).read_text(encoding="utf-8")
    assert "openapi:" not in (_ROOT / _FRAGMENT).read_text(encoding="utf-8")


def test_a_contract_is_kept(filter_module: Any) -> None:
    keep, _ = filter_module.is_contract(str(_ROOT / _CONTRACT))
    assert keep


def test_a_ref_fragment_is_dropped_with_a_reason(filter_module: Any) -> None:
    keep, reason = filter_module.is_contract(str(_ROOT / _FRAGMENT))
    assert not keep
    assert "$ref" in reason, reason


def test_a_malformed_contract_still_reaches_the_gate(filter_module: Any, tmp_path: Path) -> None:
    """The half that matters. A file that announces itself as OpenAPI and then
    fails to parse is a real failure, and a filter that quietly removed it
    would turn the gate green while the contract stayed broken."""
    broken = tmp_path / "openapi.yaml"
    broken.write_text("openapi: '3.0.3'\npaths: [this is not a mapping]\n", encoding="utf-8")
    keep, _ = filter_module.is_contract(str(broken))
    assert keep


def test_an_unreadable_file_still_reaches_the_gate(filter_module: Any, tmp_path: Path) -> None:
    keep, _ = filter_module.is_contract(str(tmp_path / "not-there.yaml"))
    assert keep


def test_contracts_go_to_stdout_and_skips_go_to_the_log() -> None:
    """Skips are printed, not swallowed. A gate that drops what it cannot read
    without saying so is the shape this repository keeps removing."""
    result = subprocess.run(
        [sys.executable, str(_SCRIPT), _CONTRACT, _FRAGMENT],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == [_CONTRACT]
    assert _FRAGMENT in result.stderr
    assert "skipped" in result.stderr


def test_a_path_that_does_not_exist_is_passed_over_rather_than_failing() -> None:
    """`git diff --name-only` lists deletions too, and a deleted contract is
    not something to validate."""
    result = subprocess.run(
        [sys.executable, str(_SCRIPT), "fixtures/apis/deleted-in-this-pr.yaml"],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_every_committed_fixture_is_either_a_contract_or_an_explained_skip(
    filter_module: Any,
) -> None:
    """Run over the whole tree the gate globs, because the list of fragments
    is not fixed and the next one added should not fail a merge either."""
    unexplained = []
    for path in sorted((_ROOT / "fixtures" / "apis").rglob("*")):
        if path.suffix not in (".yaml", ".yml", ".json") or not path.is_file():
            continue
        keep, reason = filter_module.is_contract(str(path))
        if not keep and not reason:
            unexplained.append(path.relative_to(_ROOT).as_posix())
    assert not unexplained, f"dropped without a reason: {unexplained}"
