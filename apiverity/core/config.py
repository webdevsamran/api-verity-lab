"""`.apiverity.yaml` — the project config, and the schema that describes it.

Until now there was no project config at all. Every run repeated its options on
the command line, `--severity-override` had to be retyped per invocation, and
there was nowhere to record "these are our contracts" so that CI and a laptop
agree about what is being checked.

Two things make a config file worth having rather than another place to put
mistakes:

**A published schema.** `schemas/config-v1.schema.json` is generated from this
module, so an editor can autocomplete the file and `apiverity config validate`
can reject a typo before it becomes a silently ignored key. A config format
whose only documentation is the code that reads it teaches nothing.

**Refusal to accept what it does not understand.** An unknown key is an error,
not a warning. `severity_overides` (one 'r') is a real typo someone will make,
and a tool that ignores it will cheerfully report that nothing is wrong while
the override the reader believes is active does nothing at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from apiverity.core.model import Finding, Severity

#: The config schema version. Additive changes keep it; anything that changes
#: what an existing key means increments it, like `result-v1`.
CONFIG_SCHEMA_VERSION = 1

DEFAULT_CONFIG_NAME = ".apiverity.yaml"

#: Where a run lands when neither the config nor a profile states a threshold.
DEFAULT_FAIL_ON = "error"

_SEVERITIES = ("ERROR", "WARN", "INFO")

#: Imported by name rather than from `rules.profiles`, because `core` must not
#: depend on `rules`: the config schema is generated from this module and the
#: generator would then pull the whole rule catalogue in to describe one enum.
#: `tests/unit/test_severity_profiles.py` fails if the two lists diverge.
_PROFILES = ("strict", "balanced", "advisory")


@dataclass
class Config:
    """A parsed project config."""

    version: int = CONFIG_SCHEMA_VERSION
    #: Glob patterns naming this project's contracts.
    contracts: list[str] = field(default_factory=list)
    #: One of `strict` / `balanced` / `advisory`, or None for the shipped
    #: defaults. A starting position, under everything below it: nobody writes
    #: sixty-five overrides, so without a name for the position they want, a
    #: team either accepts the defaults or turns the gate off.
    profile: str | None = None
    #: Rule id -> severity, the persistent form of `--severity-override`.
    severity_overrides: dict[str, str] = field(default_factory=dict)
    #: Lowest severity that fails a run: error | warn | never.
    #:
    #: None means the file did not say, which is not the same as saying
    #: `error`: a profile supplies the threshold when nothing states one, and a
    #: default stored here would silently outrank it. `DEFAULT_FAIL_ON` is what
    #: a run falls back to when neither speaks.
    fail_on: str | None = None
    #: Path to a suppressions file, if the project keeps one.
    suppressions: str | None = None
    #: Whether `breaking` should check the version bump by default.
    check_semver: bool = False
    #: Whether `breaking` should recommend the next version by default.
    suggest_version: bool = False
    source_path: str | None = None

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"version": self.version}
        if self.contracts:
            out["contracts"] = self.contracts
        if self.profile:
            out["profile"] = self.profile
        if self.severity_overrides:
            out["severity_overrides"] = self.severity_overrides
        if self.fail_on:
            out["fail_on"] = self.fail_on
        if self.suppressions:
            out["suppressions"] = self.suppressions
        if self.check_semver:
            out["check_semver"] = self.check_semver
        if self.suggest_version:
            out["suggest_version"] = self.suggest_version
        return out


#: Field name -> (JSON Schema fragment, human description).
#:
#: One table, used to build both the parser's validation and the published
#: schema, so the two cannot disagree about what a valid config is.
FIELDS: dict[str, tuple[dict[str, Any], str]] = {
    "version": (
        {"type": "integer", "enum": [CONFIG_SCHEMA_VERSION]},
        "Config schema version. Only 1 exists.",
    ),
    "contracts": (
        {"type": "array", "items": {"type": "string"}},
        "Glob patterns naming this project's contracts, e.g. ['api/**/*.yaml'].",
    ),
    "profile": (
        {"type": "string", "enum": list(_PROFILES)},
        "Severity profile: a starting position that every other setting overrides.",
    ),
    "severity_overrides": (
        {
            "type": "object",
            "additionalProperties": {"type": "string", "enum": list(_SEVERITIES)},
        },
        "Rule id -> severity. The persistent form of --severity-override.",
    ),
    "fail_on": (
        {"type": "string", "enum": ["error", "warn", "never"]},
        "Lowest severity that fails a run. 'never' reports without failing, "
        "which is how you adopt the gate on an API that already has history.",
    ),
    "suppressions": (
        {"type": "string"},
        "Path to a suppressions file.",
    ),
    "check_semver": (
        {"type": "boolean"},
        "Check the version bump against the changes by default.",
    ),
    "suggest_version": (
        {"type": "boolean"},
        "Recommend the next version by default.",
    ),
}


def json_schema() -> dict[str, Any]:
    """The published JSON Schema for `.apiverity.yaml`."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://github.com/webdevsamran/api-verity-lab/schemas/config-v1.schema.json",
        "title": "apiverity project configuration",
        "description": (
            "Project configuration for api-verity-lab. Generated from "
            "apiverity/core/config.py by scripts/generate_config_schema.py -- edit the "
            "module, not this file."
        ),
        "type": "object",
        "required": ["version"],
        # The whole point: a key nobody reads is a setting the reader believes
        # is active.
        "additionalProperties": False,
        "properties": {
            name: {**fragment, "description": description}
            for name, (fragment, description) in FIELDS.items()
        },
    }


class ConfigError(ValueError):
    """The config could not be used as written."""


def _validate(raw: dict[str, Any], path: str) -> list[Finding]:
    findings: list[Finding] = []

    unknown = sorted(set(raw) - set(FIELDS))
    for key in unknown:
        import difflib

        close = difflib.get_close_matches(key, sorted(FIELDS), n=1, cutoff=0.6)
        hint = f"; did you mean {close[0]!r}?" if close else ""
        findings.append(
            Finding(
                rule_id="CONFIG-UNKNOWN-KEY",
                severity=Severity.ERROR,
                message=f"{path}: unknown key {key!r}{hint}",
            )
        )

    version = raw.get("version")
    if version is None:
        findings.append(
            Finding(
                rule_id="CONFIG-VERSION-MISSING",
                severity=Severity.ERROR,
                message=f"{path}: `version` is required; this file is version {CONFIG_SCHEMA_VERSION}",
            )
        )
    elif version != CONFIG_SCHEMA_VERSION:
        findings.append(
            Finding(
                rule_id="CONFIG-VERSION-UNSUPPORTED",
                severity=Severity.ERROR,
                message=(
                    f"{path}: config version {version!r} is not supported; "
                    f"this build understands {CONFIG_SCHEMA_VERSION}"
                ),
            )
        )

    overrides = raw.get("severity_overrides")
    if overrides is not None:
        if not isinstance(overrides, dict):
            findings.append(
                Finding(
                    rule_id="CONFIG-TYPE",
                    severity=Severity.ERROR,
                    message=f"{path}: `severity_overrides` must be a mapping of rule id to severity",
                )
            )
        else:
            from apiverity.rules.breaking import CATALOG

            for rule_id, severity in overrides.items():
                if str(severity).upper() not in _SEVERITIES:
                    findings.append(
                        Finding(
                            rule_id="CONFIG-SEVERITY-INVALID",
                            severity=Severity.ERROR,
                            message=(
                                f"{path}: severity {severity!r} for {rule_id!r} is not one of "
                                f"{', '.join(_SEVERITIES)}"
                            ),
                        )
                    )
                if rule_id not in CATALOG:
                    # An override for a rule that does not exist does nothing,
                    # and looks like it does something.
                    findings.append(
                        Finding(
                            rule_id="CONFIG-RULE-UNKNOWN",
                            severity=Severity.WARN,
                            message=(
                                f"{path}: no rule with id {rule_id!r}; this override has no "
                                "effect. Run `apiverity rules` for the catalog"
                            ),
                        )
                    )

    fail_on = raw.get("fail_on")
    if fail_on is not None and fail_on not in ("error", "warn", "never"):
        findings.append(
            Finding(
                rule_id="CONFIG-FAIL-ON-INVALID",
                severity=Severity.ERROR,
                message=f"{path}: `fail_on` must be one of error, warn, never (got {fail_on!r})",
            )
        )

    for key, expected in (
        ("contracts", list),
        ("check_semver", bool),
        ("suggest_version", bool),
        ("profile", str),
        ("suppressions", str),
    ):
        value = raw.get(key)
        if value is not None and not isinstance(value, expected):
            findings.append(
                Finding(
                    rule_id="CONFIG-TYPE",
                    severity=Severity.ERROR,
                    message=(
                        f"{path}: `{key}` must be {expected.__name__}, got {type(value).__name__}"
                    ),
                )
            )
    return findings


def load_config(path: str | Path) -> tuple[Config, list[Finding]]:
    """Parse and validate a config file."""
    source = Path(path)
    try:
        raw = yaml.safe_load(source.read_text(encoding="utf-8-sig")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"{source}: not valid YAML ({exc})") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{source}: a config file is a mapping at the top level")

    findings = _validate(raw, str(source))
    config = Config(
        version=int(raw.get("version", CONFIG_SCHEMA_VERSION)),
        contracts=list(raw.get("contracts") or []),
        severity_overrides={
            str(k): str(v).upper() for k, v in (raw.get("severity_overrides") or {}).items()
        },
        fail_on=(str(raw["fail_on"]) if raw.get("fail_on") is not None else None),
        profile=raw.get("profile"),
        suppressions=raw.get("suppressions"),
        check_semver=bool(raw.get("check_semver", False)),
        suggest_version=bool(raw.get("suggest_version", False)),
        source_path=str(source),
    )
    return config, findings


def find_config(start: Path | None = None) -> Path | None:
    """Nearest `.apiverity.yaml`, searching upward from `start`.

    Upward, because a monorepo runs commands from a package directory while the
    config that governs it lives at the root.
    """
    current = (start or Path.cwd()).resolve()
    for directory in [current, *current.parents]:
        candidate = directory / DEFAULT_CONFIG_NAME
        if candidate.is_file():
            return candidate
    return None


__all__ = [
    "CONFIG_SCHEMA_VERSION",
    "DEFAULT_CONFIG_NAME",
    "DEFAULT_FAIL_ON",
    "Config",
    "ConfigError",
    "find_config",
    "json_schema",
    "load_config",
]
