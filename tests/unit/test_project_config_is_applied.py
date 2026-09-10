"""`.apiverity.yaml` was parsed, schema-checked, and applied to nothing.

`load_config` had exactly one caller: `apiverity config`, the command that
prints it. So a project that ran `apiverity init`, wrote severity overrides and
a `fail_on` threshold, and watched `apiverity config validate` say the file was
fine, got the catalogue defaults on every run and no indication of it. The
config module's own docstring described a feature the rest of the tool did not
have: "`--severity-override` had to be retyped per invocation" -- it still did.

`apiverity/rules/suppressions.py` was in the same state, one step further gone:
scoped suppressions with an owner, a reason and an expiry, imported by no
module in the package at all.

These tests run the CLI and read the exit code and the artifact, because the
defect was invisible at every level above that. Each setting gets one.
"""

from __future__ import annotations

import contextlib
import io
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import yaml

from apiverity.cli.commands.common import EXIT_FINDINGS, EXIT_OK
from apiverity.cli.main import main

_ROOT = Path(__file__).resolve().parents[2]
_V1 = str(_ROOT / "fixtures/apis/versioned/v1.yaml")
_V2 = str(_ROOT / "fixtures/apis/versioned/v2.yaml")


def _run(argv: list[str]) -> tuple[int, dict[str, Any]]:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = main(argv)
    text = buffer.getvalue()
    try:
        return code, json.loads(text)
    except ValueError:
        return code, {}


def _config(tmp_path: Path, **settings: Any) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / ".apiverity.yaml"
    path.write_text(yaml.safe_dump({"version": 1, **settings}), encoding="utf-8")
    return path


def _breaking_pair(tmp_path: Path, old_version: str, new_version: str) -> tuple[str, str]:
    """A contract pair with one breaking change and versions the caller picks.

    Written rather than reused: the shipped fixture pair bumps 1.2.0 -> 2.0.0,
    which *satisfies* semver, so it can prove that `--check-semver` produced no
    finding and not that it ran.
    """

    def spec(version: str, fields: dict[str, Any]) -> dict[str, Any]:
        return {
            "openapi": "3.1.0",
            "info": {"title": "Semver Fixture", "version": version},
            "paths": {
                "/things": {
                    "get": {
                        "operationId": "listThings",
                        "responses": {
                            "200": {
                                "description": "ok",
                                "content": {
                                    "application/json": {
                                        "schema": {"type": "object", "properties": fields}
                                    }
                                },
                            }
                        },
                    }
                }
            },
        }

    tmp_path.mkdir(parents=True, exist_ok=True)
    before = tmp_path / "before.yaml"
    after = tmp_path / "after.yaml"
    before.write_text(
        yaml.safe_dump(spec(old_version, {"id": {"type": "string"}, "name": {"type": "string"}})),
        encoding="utf-8",
    )
    after.write_text(
        yaml.safe_dump(spec(new_version, {"id": {"type": "string"}})), encoding="utf-8"
    )
    return str(before), str(after)


def _rules(payload: dict[str, Any]) -> dict[str, str]:
    return {f["rule_id"]: f["severity"] for f in payload.get("findings", [])}


# ------------------------------------------------------ the baseline case


def test_without_a_config_the_gate_fails_on_errors(tmp_path: Path) -> None:
    """The control. Every assertion below is a change from this."""
    code, payload = _run(["--no-config", "breaking", _V1, _V2, "--json"])
    assert code == EXIT_FINDINGS
    assert any(f["severity"] == "ERROR" for f in payload["findings"])


# --------------------------------------------------------- severity_overrides


def test_a_severity_override_in_the_config_is_applied(tmp_path: Path) -> None:
    before = _rules(_run(["--no-config", "breaking", _V1, _V2, "--json"])[1])
    rule = next(r for r, sev in before.items() if sev == "ERROR")

    path = _config(tmp_path, severity_overrides={rule: "INFO"})
    _code, payload = _run(["--config", str(path), "breaking", _V1, _V2, "--json"])
    assert _rules(payload)[rule] == "INFO"


def test_the_command_line_wins_over_the_config(tmp_path: Path) -> None:
    """The more specific statement.

    Someone typing `--severity-override X=INFO` for one run is not editing the
    project's policy, and a config that silently outranked the flag would make
    the flag the thing that does nothing.
    """
    before = _rules(_run(["--no-config", "breaking", _V1, _V2, "--json"])[1])
    rule = next(r for r, sev in before.items() if sev == "ERROR")

    path = _config(tmp_path, severity_overrides={rule: "INFO"})
    _code, payload = _run(
        [
            "--config",
            str(path),
            "breaking",
            _V1,
            _V2,
            "--severity-override",
            f"{rule}=WARN",
            "--json",
        ]
    )
    assert _rules(payload)[rule] == "WARN"


# ------------------------------------------------------------------ fail_on


def test_fail_on_never_reports_without_blocking(tmp_path: Path) -> None:
    """The documented adoption path, which reached no code.

    "A gate that fails on its first run against an API that already has history
    gets removed rather than adopted" is the comment `apiverity init` writes
    into the file. Until now the setting it describes did nothing.
    """
    path = _config(tmp_path, fail_on="never")
    code, payload = _run(["--config", str(path), "breaking", _V1, _V2, "--json"])
    assert code == EXIT_OK
    assert any(f["severity"] == "ERROR" for f in payload["findings"]), (
        "reported, not silenced -- the findings are still in the artifact"
    )


def test_fail_on_warn_blocks_on_a_warning(tmp_path: Path) -> None:
    path = _config(tmp_path, fail_on="warn")
    code, payload = _run(["--config", str(path), "breaking", _V1, _V2, "--json"])
    severities = {f["severity"] for f in payload["findings"]}
    assert "WARN" in severities
    assert code == EXIT_FINDINGS


def test_fail_on_warn_blocks_a_run_that_has_only_warnings(tmp_path: Path) -> None:
    """The case that distinguishes `warn` from `error`.

    With errors present, both thresholds fail and the setting proves nothing.
    """
    overrides = {
        rule: "WARN"
        for rule, sev in _rules(_run(["--no-config", "breaking", _V1, _V2, "--json"])[1]).items()
        if sev == "ERROR"
    }
    at_error = _config(tmp_path / "error", fail_on="error", severity_overrides=overrides)
    at_warn = _config(tmp_path / "warn", fail_on="warn", severity_overrides=overrides)
    assert _run(["--config", str(at_error), "breaking", _V1, _V2, "--json"])[0] == EXIT_OK
    assert _run(["--config", str(at_warn), "breaking", _V1, _V2, "--json"])[0] == EXIT_FINDINGS


# ------------------------------------------------------------- suppressions


def _suppression(tmp_path: Path, rule_id: str, **overrides: Any) -> Path:
    path = tmp_path / "suppressions.json"
    entry = {
        "rule_id": rule_id,
        "owner": "platform-team",
        "reason": "agreed with the two consumers on 2026-09-01",
        # Relative to today, because the maximum lifetime is. This helper said
        # `2099-01-01` until that maximum existed -- the format's own test
        # fixture was a permanent ignore, which is how easily one is written.
        "expires": (date.today() + timedelta(days=30)).isoformat(),
    }
    entry.update(overrides)
    path.write_text(json.dumps({"suppressions": [entry]}), encoding="utf-8")
    return path


def test_a_suppressed_finding_stops_failing_the_run(tmp_path: Path) -> None:
    before = _rules(_run(["--no-config", "breaking", _V1, _V2, "--json"])[1])
    errors = [r for r, sev in before.items() if sev == "ERROR"]

    suppressions = _suppression(tmp_path, errors[0])
    overrides = dict.fromkeys(errors[1:], "WARN")
    path = _config(
        tmp_path,
        suppressions=suppressions.name,
        severity_overrides=overrides,
    )
    code, payload = _run(["--config", str(path), "breaking", _V1, _V2, "--json"])
    assert errors[0] not in _rules(payload)
    assert code == EXIT_OK


def test_a_suppressed_finding_is_still_reported(tmp_path: Path) -> None:
    """Dropped from the gate, never from the record.

    A gate that silences findings on the say-so of a file, without saying
    which, is a gate nobody can audit -- and the owner and reason the
    suppressions format demands exist precisely to be read later.
    """
    before = _rules(_run(["--no-config", "breaking", _V1, _V2, "--json"])[1])
    rule = next(r for r, sev in before.items() if sev == "ERROR")

    suppressions = _suppression(tmp_path, rule)
    path = _config(tmp_path, suppressions=suppressions.name)
    _code, payload = _run(["--config", str(path), "breaking", _V1, _V2, "--json"])

    record = payload["suppressions"]
    assert record["declared"] == 1
    entry = next(s for s in record["suppressed"] if s["rule_id"] == rule)
    assert entry["owner"] == "platform-team"
    assert "2026-09-01" in entry["reason"]


def test_an_expired_suppression_becomes_a_finding(tmp_path: Path) -> None:
    """The mechanism that stops an ignore-list becoming permanent.

    It existed, fully written, in a module nothing imported.
    """
    before = _rules(_run(["--no-config", "breaking", _V1, _V2, "--json"])[1])
    rule = next(r for r, sev in before.items() if sev == "ERROR")

    suppressions = _suppression(tmp_path, rule, expires="2020-01-01")
    path = _config(tmp_path, suppressions=suppressions.name)
    _code, payload = _run(["--config", str(path), "breaking", _V1, _V2, "--json"])

    fired = _rules(payload)
    assert "SUPPRESSION-EXPIRED" in fired
    assert rule in fired, "an expired suppression suppresses nothing"


def test_suppressions_apply_to_validate_too(tmp_path: Path) -> None:
    """Not a `breaking`-only feature. A project's ignore-list is the project's."""
    _code, payload = _run(["--no-config", "validate", _V2, "--json"])
    rule = payload["findings"][0]["rule_id"]

    suppressions = _suppression(tmp_path, rule)
    path = _config(tmp_path, suppressions=suppressions.name)
    _code, payload = _run(["--config", str(path), "validate", _V2, "--json"])
    assert rule not in _rules(payload)
    assert payload["suppressions"]["declared"] == 1


def test_a_suppressions_path_resolves_against_the_config_not_the_cwd(tmp_path: Path) -> None:
    """A CI job running from the repository root and a developer running from a
    service directory have to resolve it the same way."""
    nested = tmp_path / "services" / "orders"
    nested.mkdir(parents=True)
    before = _rules(_run(["--no-config", "breaking", _V1, _V2, "--json"])[1])
    rule = next(r for r, sev in before.items() if sev == "ERROR")

    suppressions = _suppression(nested, rule)
    path = nested / ".apiverity.yaml"
    path.write_text(
        yaml.safe_dump({"version": 1, "suppressions": suppressions.name}), encoding="utf-8"
    )
    _code, payload = _run(["--config", str(path), "breaking", _V1, _V2, "--json"])
    assert payload["suppressions"]["declared"] == 1


# -------------------------------------------------------- boolean defaults


def test_check_semver_can_be_turned_on_from_the_config(tmp_path: Path) -> None:
    """A breaking change released as a patch, with the check off and then on."""
    before, after = _breaking_pair(tmp_path / "specs", "1.0.0", "1.0.1")

    off = _run(["--no-config", "breaking", before, after, "--json"])[1]
    assert not [f for f in off["findings"] if f["rule_id"].startswith("SEMVER-")]

    path = _config(tmp_path, check_semver=True)
    _code, on = _run(["--config", str(path), "breaking", before, after, "--json"])
    assert [f for f in on["findings"] if f["rule_id"].startswith("SEMVER-")]


def test_suggest_version_can_be_turned_on_from_the_config(tmp_path: Path) -> None:
    path = _config(tmp_path, suggest_version=True)
    _code, payload = _run(["--config", str(path), "breaking", _V1, _V2, "--json"])
    assert "version_advice" in payload


# --------------------------------------------------------------- escape hatch


def test_no_config_ignores_a_config_that_exists(tmp_path: Path, monkeypatch) -> None:
    """A run that must not inherit project policy has to have a way to say so."""
    import apiverity.core.config as config_module

    path = _config(tmp_path, fail_on="never")
    monkeypatch.setattr(config_module, "find_config", lambda start=None: path)

    assert _run(["breaking", _V1, _V2, "--json"])[0] == EXIT_OK
    assert _run(["--no-config", "breaking", _V1, _V2, "--json"])[0] == EXIT_FINDINGS


def test_a_config_that_does_not_exist_is_a_usage_error(tmp_path: Path) -> None:
    """Not a silent fallback to defaults.

    The parser refuses unknown keys precisely so a mistyped setting cannot be
    ignored; falling back to defaults on a mistyped *path* would undo that at
    the last step.
    """
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        try:
            main(["--config", str(tmp_path / "nope.yaml"), "breaking", _V1, _V2, "--json"])
        except SystemExit as exit_code:
            assert exit_code.code == 2
        else:
            raise AssertionError("a missing config was accepted")
