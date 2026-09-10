"""Three names instead of sixty-five overrides.

A team that wants to be stricter than the catalogue has had exactly one route:
write an override per rule. Nobody does that. They accept the defaults or they
turn the gate off, and the second is the outcome the whole tool exists to
prevent.

A profile is a starting position, so the tests that matter most here are the
precedence ones: a profile that outranked an explicit setting would take a
decision a team had already written down and quietly reverse it.
"""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from apiverity.cli.commands.common import EXIT_FINDINGS, EXIT_OK
from apiverity.cli.main import main
from apiverity.core.model import Severity
from apiverity.rules.breaking import CATALOG
from apiverity.rules.profiles import (
    DESCRIPTIONS,
    PROFILES,
    UnknownProfileError,
    fail_on,
    severity_overrides,
    summary,
)

_ROOT = Path(__file__).resolve().parents[2]
_V1 = str(_ROOT / "fixtures/apis/versioned/v1.yaml")
_V2 = str(_ROOT / "fixtures/apis/versioned/v2.yaml")


def _run(argv: list[str]) -> tuple[int, dict[str, Any]]:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = main(argv)
    try:
        return code, json.loads(buffer.getvalue())
    except ValueError:
        return code, {}


def _severities(payload: dict[str, Any]) -> dict[str, str]:
    return {f["rule_id"]: f["severity"] for f in payload.get("findings", [])}


def _config(tmp_path: Path, **settings: Any) -> str:
    path = tmp_path / ".apiverity.yaml"
    path.write_text(yaml.safe_dump({"version": 1, **settings}), encoding="utf-8")
    return str(path)


# ------------------------------------------------------------ the table


def test_every_profile_is_described() -> None:
    """A name with no sentence attached is a name nobody can choose between."""
    assert set(PROFILES) == set(DESCRIPTIONS)
    assert all(DESCRIPTIONS[name].strip() for name in PROFILES)


def test_the_config_schema_and_the_profile_list_agree() -> None:
    """`core` cannot import `rules`, so the enum is duplicated on purpose.

    The generated config schema would otherwise pull the whole rule catalogue
    in to describe three strings. This is the test that keeps the copy honest.
    """
    from apiverity.core.config import _PROFILES

    assert tuple(_PROFILES) == tuple(PROFILES)


def test_an_unknown_profile_names_the_known_ones() -> None:
    with pytest.raises(UnknownProfileError) as caught:
        severity_overrides("paranoid")
    for name in PROFILES:
        assert name in str(caught.value)


def test_the_summary_reports_what_each_profile_actually_does() -> None:
    """Generated into `docs/rule-catalog.md`, so it cannot describe a profile
    that behaves differently."""
    rows = {name: (threshold, raised) for name, threshold, _desc, raised in summary()}
    assert rows["strict"][0] == "error"
    assert rows["advisory"][0] == "never"
    assert rows["strict"][1] > 0, "strict has to change something to mean anything"
    assert rows["balanced"][1] == 0


# ----------------------------------------------------------- what they do


def test_strict_raises_every_warning_and_nothing_else() -> None:
    overrides = severity_overrides("strict")
    warns = {rid for rid, spec in CATALOG.items() if spec.severity is Severity.WARN}
    assert set(overrides) == warns
    assert set(overrides.values()) == {"ERROR"}


def test_strict_is_derived_from_the_catalogue_not_written_out() -> None:
    """A hand-listed profile silently omits the rule added tomorrow.

    Which is worse than no profile: a setting that quietly does not cover a
    rule is one that is believed.
    """
    warns = [rid for rid, spec in CATALOG.items() if spec.severity is Severity.WARN]
    assert len(severity_overrides("strict")) == len(warns)


def test_advisory_does_not_rewrite_severities() -> None:
    """It changes the threshold, not what each finding *is*.

    Rewriting every ERROR to WARN would make the artifact disagree with the
    catalogue about the severity of the same change -- and an artifact is read
    long after the run that produced it.
    """
    assert severity_overrides("advisory") == {}
    assert fail_on("advisory") == "never"


# ------------------------------------------------------ end to end


def test_strict_blocks_where_balanced_reports() -> None:
    default_code, default_payload = _run(["--no-config", "breaking", _V1, _V2, "--json"])
    strict_code, strict_payload = _run(
        ["--no-config", "--profile", "strict", "breaking", _V1, _V2, "--json"]
    )
    assert "WARN" in set(_severities(default_payload).values())
    assert "WARN" not in set(_severities(strict_payload).values())
    assert (default_code, strict_code) == (EXIT_FINDINGS, EXIT_FINDINGS)


def test_advisory_reports_the_same_findings_without_blocking() -> None:
    plain_code, plain = _run(["--no-config", "breaking", _V1, _V2, "--json"])
    advisory_code, advisory = _run(
        ["--no-config", "--profile", "advisory", "breaking", _V1, _V2, "--json"]
    )
    assert plain_code == EXIT_FINDINGS
    assert advisory_code == EXIT_OK
    assert _severities(plain) == _severities(advisory), "same findings, same severities"


def test_a_profile_can_be_set_in_the_config(tmp_path: Path) -> None:
    path = _config(tmp_path, profile="advisory")
    code, _payload = _run(["--config", path, "breaking", _V1, _V2, "--json"])
    assert code == EXIT_OK


# ------------------------------------------------------------ precedence


def test_an_explicit_override_beats_the_profile(tmp_path: Path) -> None:
    """A team on `strict` that has agreed one rule is advisory writes that rule
    down, and the profile must not put it back."""
    strict = _run(["--no-config", "--profile", "strict", "breaking", _V1, _V2, "--json"])[1]
    raised = next(
        rid
        for rid in _severities(strict)
        if rid in CATALOG and CATALOG[rid].severity is Severity.WARN
    )

    path = _config(tmp_path, profile="strict", severity_overrides={raised: "INFO"})
    _code, payload = _run(["--config", path, "breaking", _V1, _V2, "--json"])
    assert _severities(payload)[raised] == "INFO"


def test_the_command_line_beats_both(tmp_path: Path) -> None:
    strict = _run(["--no-config", "--profile", "strict", "breaking", _V1, _V2, "--json"])[1]
    raised = next(
        rid
        for rid in _severities(strict)
        if rid in CATALOG and CATALOG[rid].severity is Severity.WARN
    )

    path = _config(tmp_path, profile="strict", severity_overrides={raised: "INFO"})
    _code, payload = _run(
        ["--config", path, "breaking", _V1, _V2, "--severity-override", f"{raised}=WARN", "--json"]
    )
    assert _severities(payload)[raised] == "WARN"


def test_an_explicit_fail_on_beats_the_profiles_threshold(tmp_path: Path) -> None:
    """`advisory` with `fail_on: warn` is a real position, not a contradiction:
    "we want warnings to block, but not yet the catalogue's error list"."""
    path = _config(tmp_path, profile="advisory", fail_on="error")
    code, _payload = _run(["--config", path, "breaking", _V1, _V2, "--json"])
    assert code == EXIT_FINDINGS


def test_the_flag_beats_the_configs_profile(tmp_path: Path) -> None:
    path = _config(tmp_path, profile="advisory")
    code, _payload = _run(
        ["--config", path, "--profile", "balanced", "breaking", _V1, _V2, "--json"]
    )
    assert code == EXIT_FINDINGS


# ------------------------------------------------------------- discovery


def test_rules_lists_the_profiles_on_request() -> None:
    _code, payload = _run(["--no-config", "rules", "--profiles", "--json"])
    assert [p["profile"] for p in payload["profiles"]] == list(PROFILES)


def test_rules_reports_the_severity_this_run_would_apply() -> None:
    """`apiverity rules` is where someone checks what a rule will do before
    writing an override.

    Printing the shipped severity while a profile quietly changes it would make
    this command the thing that misleads.
    """
    _code, payload = _run(["--no-config", "--profile", "strict", "rules", "--json"])
    assert payload["profile"] == "strict"
    changed = [r for r in payload["rules"] if r["severity"] != r["catalog_severity"]]
    assert len(changed) == len(severity_overrides("strict"))
    assert all(r["severity"] == "ERROR" and r["catalog_severity"] == "WARN" for r in changed)


def test_rules_without_a_profile_reports_the_catalogue() -> None:
    _code, payload = _run(["--no-config", "rules", "--json"])
    assert "profile" not in payload
    assert all(r["severity"] == r["catalog_severity"] for r in payload["rules"])
