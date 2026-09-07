"""Unrecognized sources must be distinguishable from broken contracts.

Regression guard for the contract gate: a repository routinely contains YAML
that is not an API spec (tool configs, CI files). Treating those as validation
failures made `api-verity.yml` block its own pull requests. The loader must
report "not a contract" as its own condition so callers can skip rather than
fail.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from apiverity.specs import UnrecognizedSpecError
from apiverity.specs.loader import detect_and_load

_NOT_A_SPEC = """\
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.16.4
    hooks:
      - id: ruff
"""

_BROKEN_OPENAPI = """\
openapi: "3.0.0"
info: {title: X, version: "1"}
paths: {"/a": {get: {responses: {"200": {description: ok
"""


def test_non_spec_yaml_raises_unrecognized(tmp_path: Path) -> None:
    src = tmp_path / ".pre-commit-config.yaml"
    src.write_text(_NOT_A_SPEC, encoding="utf-8")

    with pytest.raises(UnrecognizedSpecError) as excinfo:
        detect_and_load(str(src))

    assert excinfo.value.source == str(src)
    assert "openapi" in excinfo.value.tried
    # Each protocol is named once: OpenAPI and Swagger 2.0 share a value.
    assert len(excinfo.value.tried) == len(set(excinfo.value.tried))


def test_malformed_contract_is_not_reported_as_unrecognized(tmp_path: Path) -> None:
    """A broken spec is a real failure, not a file to skip."""
    src = tmp_path / "openapi.yaml"
    src.write_text(_BROKEN_OPENAPI, encoding="utf-8")

    with pytest.raises(Exception) as excinfo:
        detect_and_load(str(src))

    assert not isinstance(excinfo.value, UnrecognizedSpecError)


def test_unrecognized_is_a_valueerror() -> None:
    """Back-compat: existing `except ValueError` handlers keep working."""
    assert issubclass(UnrecognizedSpecError, ValueError)
