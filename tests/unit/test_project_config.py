"""`apiverity init` and `apiverity config validate`.

There was no project config at all: every run repeated its options, and there
was nowhere to record "these are our contracts" so that a laptop and CI agree
about what is being checked.

The design decision worth testing is the strict one. An unknown key is an
ERROR, not a warning, because `severity_overides` (one 'r') is a typo someone
will make — and a tool that ignores it reports that nothing is wrong while the
override the reader believes is active does nothing at all.
"""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from apiverity.cli.commands.common import EXIT_FINDINGS, EXIT_OK, EXIT_USAGE
from apiverity.cli.main import main
from apiverity.core.config import (
    CONFIG_SCHEMA_VERSION,
    DEFAULT_CONFIG_NAME,
    ConfigError,
    find_config,
    json_schema,
    load_config,
)

_ROOT = Path(__file__).resolve().parents[2]


def _run(argv: list[str]) -> tuple[int, dict[str, Any], str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    text = out.getvalue()
    return code, (json.loads(text) if text.strip().startswith("{") else {}), err.getvalue()


def _write(tmp_path: Path, config: dict[str, Any]) -> Path:
    path = tmp_path / DEFAULT_CONFIG_NAME
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return path


def _ids(findings: list[dict[str, Any]]) -> set[str]:
    return {f["rule_id"] for f in findings}


# ------------------------------------------------------------------- init


def test_init_finds_contracts_and_writes_a_valid_config(tmp_path: Path) -> None:
    api = tmp_path / "api" / "v1"
    api.mkdir(parents=True)
    (api / "openapi.yaml").write_text(
        (_ROOT / "fixtures/apis/versioned/v1.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    code, payload, _ = _run(["init", str(tmp_path), "--json"])
    assert code == EXIT_OK
    assert payload["contracts_found"] == 1
    assert payload["written"] is True

    _, findings = load_config(tmp_path / DEFAULT_CONFIG_NAME)
    assert [f for f in findings if f.severity.value == "ERROR"] == []


def test_init_ignores_files_that_are_not_contracts(tmp_path: Path) -> None:
    """A repo is full of YAML and JSON that is not a spec."""
    api = tmp_path / "api"
    api.mkdir()
    (api / "package.json").write_text('{"name": "x"}', encoding="utf-8")
    (api / "ci.yaml").write_text("jobs:\n  build:\n    runs-on: ubuntu\n", encoding="utf-8")

    _, payload, _ = _run(["init", str(tmp_path), "--json"])
    assert payload["contracts_found"] == 0


def test_a_json_schema_mentioning_openapi_is_not_a_contract(tmp_path: Path) -> None:
    """Found by running `init` on this repository.

    It proposed `schemas/**` because `schemas/result-v1.schema.json` contains
    the string "openapi" inside an enum of protocol names. A config listing the
    wrong files is worse than one listing none: it looks configured.
    """
    schemas = tmp_path / "schemas"
    schemas.mkdir()
    (schemas / "result.schema.json").write_text(
        '{"properties": {"protocol": {"enum": ["openapi", "graphql"]}}}', encoding="utf-8"
    )
    _, payload, _ = _run(["init", str(tmp_path), "--json"])
    assert payload["contracts_found"] == 0, payload["contracts"]


def test_a_real_contract_in_the_same_directory_is_still_found(tmp_path: Path) -> None:
    """The sniff must not have been tightened into uselessness."""
    schemas = tmp_path / "schemas"
    schemas.mkdir()
    (schemas / "result.schema.json").write_text(
        '{"properties": {"protocol": {"enum": ["openapi"]}}}', encoding="utf-8"
    )
    (schemas / "api.yaml").write_text(
        "openapi: 3.1.0\ninfo: {title: X, version: '1'}\npaths: {}\n",
        encoding="utf-8",
    )
    _, payload, _ = _run(["init", str(tmp_path), "--json"])
    assert payload["contracts"] == ["schemas/api.yaml"]


def test_init_starts_with_the_gate_off(tmp_path: Path) -> None:
    """A gate that fails on its first run gets removed rather than adopted."""
    _run(["init", str(tmp_path), "--json"])
    config, _ = load_config(tmp_path / DEFAULT_CONFIG_NAME)
    assert config.fail_on == "never"


def test_init_refuses_to_clobber_an_existing_config(tmp_path: Path) -> None:
    _write(tmp_path, {"version": 1})
    code, _, err = _run(["init", str(tmp_path), "--json"])
    assert code == EXIT_USAGE
    assert "--force" in err


def test_init_dry_run_writes_nothing(tmp_path: Path) -> None:
    code, payload, _ = _run(["init", str(tmp_path), "--dry-run", "--json"])
    assert code == EXIT_OK
    assert payload["written"] is False
    assert not (tmp_path / DEFAULT_CONFIG_NAME).exists()


def test_init_is_safe_to_run_twice(tmp_path: Path) -> None:
    """Not interactive, so it has to be re-runnable and deterministic."""
    _run(["init", str(tmp_path), "--json"])
    first = (tmp_path / DEFAULT_CONFIG_NAME).read_text(encoding="utf-8")
    _run(["init", str(tmp_path), "--force", "--json"])
    assert (tmp_path / DEFAULT_CONFIG_NAME).read_text(encoding="utf-8") == first


# ----------------------------------------------------------------- config


def test_an_unknown_key_is_an_error_with_a_suggestion(tmp_path: Path) -> None:
    """The whole reason the config is strict."""
    path = _write(tmp_path, {"version": 1, "severity_overides": {"BRK-OP-REMOVED": "WARN"}})
    code, payload, _ = _run(["config", "validate", "--path", str(path), "--json"])
    assert code == EXIT_FINDINGS
    assert "CONFIG-UNKNOWN-KEY" in _ids(payload["findings"])
    assert "did you mean 'severity_overrides'" in json.dumps(payload["findings"])


def test_an_override_for_a_rule_that_does_not_exist_is_reported(tmp_path: Path) -> None:
    """It does nothing, and looks like it does something."""
    path = _write(tmp_path, {"version": 1, "severity_overrides": {"BRK-NOPE": "WARN"}})
    _, payload, _ = _run(["config", "validate", "--path", str(path), "--json"])
    assert "CONFIG-RULE-UNKNOWN" in _ids(payload["findings"])


def test_an_invalid_severity_is_an_error(tmp_path: Path) -> None:
    path = _write(tmp_path, {"version": 1, "severity_overrides": {"BRK-OP-REMOVED": "LOUD"}})
    code, payload, _ = _run(["config", "validate", "--path", str(path), "--json"])
    assert code == EXIT_FINDINGS
    assert "CONFIG-SEVERITY-INVALID" in _ids(payload["findings"])


def test_an_invalid_fail_on_is_an_error(tmp_path: Path) -> None:
    path = _write(tmp_path, {"version": 1, "fail_on": "sometimes"})
    code, payload, _ = _run(["config", "validate", "--path", str(path), "--json"])
    assert code == EXIT_FINDINGS
    assert "CONFIG-FAIL-ON-INVALID" in _ids(payload["findings"])


@pytest.mark.parametrize(
    ("key", "value"),
    [("contracts", "not-a-list"), ("check_semver", "yes"), ("suppressions", 42)],
)
def test_wrong_types_are_errors(tmp_path: Path, key: str, value: Any) -> None:
    path = _write(tmp_path, {"version": 1, key: value})
    code, payload, _ = _run(["config", "validate", "--path", str(path), "--json"])
    assert code == EXIT_FINDINGS
    assert "CONFIG-TYPE" in _ids(payload["findings"])


def test_a_missing_version_is_an_error(tmp_path: Path) -> None:
    path = _write(tmp_path, {"contracts": ["a.yaml"]})
    code, payload, _ = _run(["config", "validate", "--path", str(path), "--json"])
    assert code == EXIT_FINDINGS
    assert "CONFIG-VERSION-MISSING" in _ids(payload["findings"])


def test_a_future_config_version_is_refused(tmp_path: Path) -> None:
    """Reading a format this build does not understand would mis-apply it."""
    path = _write(tmp_path, {"version": CONFIG_SCHEMA_VERSION + 1})
    code, payload, _ = _run(["config", "validate", "--path", str(path), "--json"])
    assert code == EXIT_FINDINGS
    assert "CONFIG-VERSION-UNSUPPORTED" in _ids(payload["findings"])


def test_malformed_yaml_is_refused_rather_than_half_read(tmp_path: Path) -> None:
    path = tmp_path / DEFAULT_CONFIG_NAME
    path.write_text("version: 1\n  bad: [indent\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(path)


def test_config_is_found_by_searching_upward(tmp_path: Path) -> None:
    """A monorepo runs commands from a package while the config lives at the root."""
    _write(tmp_path, {"version": 1})
    nested = tmp_path / "packages" / "service"
    nested.mkdir(parents=True)
    assert find_config(nested) == tmp_path / DEFAULT_CONFIG_NAME


# ----------------------------------------------------------------- schema


def test_the_published_schema_forbids_unknown_keys() -> None:
    """An editor must reject what the tool rejects, or it teaches the wrong thing."""
    assert json_schema()["additionalProperties"] is False


def test_the_published_schema_matches_the_module() -> None:
    """`--check` runs in CI; failing here too is faster feedback."""
    committed = json.loads(
        (_ROOT / "schemas" / "config-v1.schema.json").read_text(encoding="utf-8")
    )
    assert committed == json_schema(), "run scripts/generate_config_schema.py"


def test_every_documented_key_is_one_the_parser_accepts(tmp_path: Path) -> None:
    """The schema and the validator are built from one table; prove they agree."""
    from apiverity.core.config import FIELDS

    by_type: dict[str, Any] = {"array": ["x"], "object": {}, "string": "x", "boolean": True}
    sample: dict[str, Any] = {"version": 1}
    for name, (fragment, _) in FIELDS.items():
        if name == "version":
            continue
        sample[name] = by_type[str(fragment["type"])]
    sample["fail_on"] = "error"

    path = _write(tmp_path, sample)
    _, payload, _ = _run(["config", "validate", "--path", str(path), "--json"])
    assert "CONFIG-UNKNOWN-KEY" not in _ids(payload["findings"])
    assert "CONFIG-TYPE" not in _ids(payload["findings"])
