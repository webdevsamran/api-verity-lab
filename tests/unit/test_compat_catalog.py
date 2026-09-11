"""The diff lane's rules, and the two things they could not do before.

`apiverity explain BRK-RESP-FIELD-REMOVED` has worked since the beginning.
`apiverity explain COMPAT-MEDIA-REMOVED` answered *"no rule with id ..."* — for
a rule `breaking` emits — and `--severity-override COMPAT-MEDIA-REMOVED=INFO`
was accepted and applied to nothing.

Both were found by `scripts/generate_landing_pages.py`, which lists the rules
observed firing on each protocol and had six of them with nothing to say.
"""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
from typing import Any

import pytest

from apiverity.cli.main import main
from apiverity.diff.compat_catalog import (
    COMPAT_CATALOG,
    GRAPHQL_COMPAT_CATALOG,
    PROTO_CATALOG,
)
from apiverity.rules.check_catalog import catalog as check_catalog

_ROOT = Path(__file__).resolve().parents[2]
_FIXTURES = _ROOT / "fixtures"

_FAMILIES = {
    "COMPAT": COMPAT_CATALOG,
    "GQL": GRAPHQL_COMPAT_CATALOG,
    "PROTO": PROTO_CATALOG,
}


def _run(argv: list[str]) -> tuple[int, dict[str, Any]]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = main([*argv, "--json"])
    return code, json.loads(out.getvalue())


# -- the entries ----------------------------------------------------------


@pytest.mark.parametrize("prefix", sorted(_FAMILIES))
def test_every_entry_is_in_the_merged_catalogue(prefix: str) -> None:
    """A family module nothing merges is a file, and `explain` would still say
    the rule does not exist."""
    merged = check_catalog()
    for rule_id in _FAMILIES[prefix]:
        assert rule_id in merged


@pytest.mark.parametrize("prefix", sorted(_FAMILIES))
def test_every_entry_says_what_to_do(prefix: str) -> None:
    """A rule that says only "no" gets switched off, and takes its neighbours
    with it. `instead` is the half that keeps it."""
    for rule_id, spec in _FAMILIES[prefix].items():
        assert spec.rule_id == rule_id
        assert len(spec.description.strip()) > 20, rule_id
        assert len(spec.instead.strip()) > 20, rule_id
        assert spec.produced_by in {"breaking", "validate", "drift"}, rule_id
        assert spec.family != "Security", f"{rule_id} is filed under the default family"


def test_the_entries_cover_exactly_what_the_analysers_emit() -> None:
    """Both directions. A rule emitted with no entry is the defect this fixes;
    an entry nothing emits is documentation for something that cannot happen."""
    import ast

    emitted: set[str] = set()
    for name in (
        "apiverity/diff/compat.py",
        "apiverity/diff/protocol_compat.py",
        "apiverity/specs/grpc/__init__.py",
        "apiverity/specs/graphql/operations.py",
    ):
        tree = ast.parse((_ROOT / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            value = node.value
            if value.split("-")[0] in _FAMILIES and "-" in value and value == value.upper():
                emitted.add(value)

    catalogued = set().union(*(set(family) for family in _FAMILIES.values()))
    assert not emitted - catalogued, f"emitted and not catalogued: {sorted(emitted - catalogued)}"
    assert not catalogued - emitted, f"catalogued and not emitted: {sorted(catalogued - emitted)}"


# -- explain --------------------------------------------------------------


@pytest.mark.parametrize(
    "rule_id",
    [
        "COMPAT-MEDIA-REMOVED",
        "PROTO-WIRE-TYPE-CHANGED",
        "GQL-FIELD-REMOVED",
        "GQL-DRIFT-MISSING-FIELD",
    ],
)
def test_explain_answers_for_a_rule_the_tool_emits(rule_id: str) -> None:
    code, payload = _run(["explain", rule_id])
    assert code == 0
    assert payload["rule_id"] == rule_id
    assert payload["description"]
    assert payload["instead"]
    # Not "Other", which is what every one of these got before they had a
    # prefix in the guide -- an answer that tells the reader nothing about
    # where the rule lives.
    assert payload["group"] != "Other"
    assert payload["documentation"] == "docs/check-rules.md"


# -- the override that did nothing ----------------------------------------


def test_a_severity_override_reaches_a_compat_finding() -> None:
    """`analyze_compat` decides severity per finding and never saw the override
    map, so a project that wrote `COMPAT-SERVER-REMOVED: ERROR` got a setting
    that validated, read as applied, and changed nothing."""
    argv = [
        "breaking",
        str(_FIXTURES / "apis/crud/openapi.yaml"),
        str(_FIXTURES / "apis/versioned/v2.yaml"),
    ]
    _, before = _run(argv)
    baseline = {
        f["rule_id"]: f["severity"]
        for f in before["findings"]
        if f["rule_id"].startswith("COMPAT-")
    }
    assert baseline, "this fixture pair no longer produces a COMPAT finding to override"

    target = next(rule for rule, severity in baseline.items() if severity != "ERROR")
    _, after = _run([*argv, "--severity-override", f"{target}=ERROR"])
    got = {
        f["rule_id"]: f["severity"] for f in after["findings"] if f["rule_id"].startswith("COMPAT-")
    }
    assert got[target] == "ERROR"
    # And only the one named moved.
    assert {k: v for k, v in got.items() if k != target} == {
        k: v for k, v in baseline.items() if k != target
    }


def test_a_config_override_for_a_check_rule_is_not_reported_as_unknown(tmp_path: Path) -> None:
    """The validation checked the breaking catalogue alone, so every `SEC-*`,
    `COMPAT-*` and `PROTO-*` override was reported as naming a rule that does
    not exist. Those rules do exist; the override simply did nothing, which is
    a different sentence and now a fixed one."""
    from apiverity.core.config import load_config

    path = tmp_path / ".apiverity.yaml"
    path.write_text(
        "severity_overrides:\n"
        "  COMPAT-MEDIA-ADDED: WARN\n"
        "  SEC-AUTH-MISSING: INFO\n"
        "  BRK-OP-REMOVED: WARN\n"
        "  NOT-A-RULE-AT-ALL: WARN\n",
        encoding="utf-8",
    )
    _, findings = load_config(path)
    unknown = [f for f in findings if f.rule_id == "CONFIG-RULE-UNKNOWN"]
    assert len(unknown) == 1
    assert "NOT-A-RULE-AT-ALL" in unknown[0].message
