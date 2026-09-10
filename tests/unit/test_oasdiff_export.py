"""oasdiff's shape, and the four places a from-memory version of it goes wrong.

Migration cost is the real competitor: a team already gating on oasdiff has
`jq` filters and ignore-lists keyed on its output, and an export that is nearly
the same shape is worse than none, because the filter that stops matching does
so silently.

Everything asserted here was verified 2026-09-10 against oasdiff v1.31.0
(2026-09-05, Apache-2.0). The four:

- **`level` is a number.** `checker/rules/level.go` declares `type Level int`
  and defines no `MarshalJSON`, so `"error"` never appears — it is `3`.
- **The output is a bare array**, not an envelope. Wrapping it would put a
  `.changes` in front of every existing `jq` expression.
- **Absent is not empty.** Every field but `level` is `omitempty`, so a key
  with `""` in it is a different document from one without the key.
- **A near-miss id is not a match.** Where oasdiff splits a check that this
  tool does not, picking one of theirs asserts something never determined.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from apiverity.reports.oasdiff import (
    FOREIGN_PREFIX,
    LEVELS,
    MAPPING,
    NO_EXACT_MATCH,
    STATUS_MAPPING,
    coverage,
    export,
    render,
)
from apiverity.reports.renderers import RENDERERS
from apiverity.rules.breaking import CATALOG

_ROOT = Path(__file__).resolve().parents[2]
_DOC = _ROOT / "docs" / "oasdiff-migration.md"


def _artifact(findings: list[dict[str, Any]], protocol: str = "openapi") -> dict[str, Any]:
    return {"tool": "apiverity", "command": "breaking", "protocol": protocol, "findings": findings}


def _finding(**kwargs: Any) -> dict[str, Any]:
    base = {
        "rule_id": "BRK-OP-REMOVED",
        "severity": "ERROR",
        "message": "operation 'GET /users' was removed",
        "operation_key": "GET /users",
    }
    base.update(kwargs)
    return base


# --------------------------------------------------------------- the shape


def test_the_output_is_a_bare_array_not_an_envelope() -> None:
    """`oasdiff breaking -f json` writes an array. An envelope would put a
    `.changes` in front of every `jq` expression a team already has."""
    rendered = json.loads(render(_artifact([_finding()])))
    assert isinstance(rendered, list)


def test_level_is_a_number_not_the_word() -> None:
    """`type Level int` with no `MarshalJSON`. The word "error" never appears
    in oasdiff's JSON, and an export that wrote it would fail every filter
    keyed on the number."""
    assert LEVELS == {"ERROR": 3, "WARN": 2, "INFO": 1}
    change = export(_artifact([_finding()]))[0]
    assert change["level"] == 3
    assert not isinstance(change["level"], str)


@pytest.mark.parametrize(("severity", "level"), [("ERROR", 3), ("WARN", 2), ("INFO", 1)])
def test_each_severity_maps_to_its_number(severity: str, level: int) -> None:
    change = export(_artifact([_finding(severity=severity)]))[0]
    assert change["level"] == level


def test_an_absent_value_is_an_absent_key() -> None:
    """Every field but `level` is `omitempty` there. A key holding `""` is a
    different document from one without the key, and a consumer distinguishing
    them is reading a difference this export invented."""
    change = export(_artifact([_finding(operation_key=None, message="")]))[0]
    assert "text" not in change
    assert "operation" not in change
    assert "path" not in change
    assert "comment" not in change


def test_the_operation_and_path_are_split_apart() -> None:
    change = export(_artifact([_finding()]))[0]
    assert change["operation"] == "GET"
    assert change["path"] == "/users"


def test_a_key_that_is_not_method_and_path_yields_neither() -> None:
    """A gRPC `Service.Method` is not a verb and a route. Inventing `"GET"` for
    one would be a fabricated field in somebody's dashboard."""
    change = export(_artifact([_finding(operation_key="UserService.GetUser")], protocol="grpc"))[0]
    assert "operation" not in change
    assert "path" not in change


def test_the_source_locations_become_base_and_revision() -> None:
    change = export(
        _artifact(
            [
                _finding(
                    location={"file": "v1.yaml", "line": 12, "column": 3},
                    new_location={"file": "v2.yaml", "line": 14, "column": 3},
                )
            ]
        )
    )[0]
    assert change["baseSource"] == {"file": "v1.yaml", "line": 12, "column": 3}
    assert change["revisionSource"] == {"file": "v2.yaml", "line": 14, "column": 3}


def test_an_unknown_line_is_omitted_rather_than_written_as_zero() -> None:
    """Line zero is not a line. `omitempty` is how oasdiff says "unknown", and
    a literal `0` would point a reader at the top of the file."""
    change = export(_artifact([_finding(location={"file": "v1.yaml", "line": 0, "column": 0})]))[0]
    assert change["baseSource"] == {"file": "v1.yaml"}


def test_a_location_with_no_file_produces_no_source_object() -> None:
    change = export(_artifact([_finding(location={"file": "", "line": 4})]))[0]
    assert "baseSource" not in change


def test_the_hint_becomes_the_comment() -> None:
    change = export(_artifact([_finding(hint="add it back for a release")]))[0]
    assert change["comment"] == "add it back for a release"


def test_changes_are_ordered_the_way_oasdiff_orders_them() -> None:
    """Most severe first, then path, then operation, then id --
    `checker/changes.go`, `CompareChanges`."""
    changes = export(
        _artifact(
            [
                _finding(severity="INFO", operation_key="GET /a"),
                _finding(severity="ERROR", operation_key="GET /z"),
                _finding(severity="WARN", operation_key="GET /b"),
            ]
        )
    )
    assert [c["level"] for c in changes] == [3, 2, 1]


# ------------------------------------------------------------- the mapping


def test_a_mapped_rule_uses_oasdiffs_own_id() -> None:
    change = export(_artifact([_finding(rule_id="BRK-PARAM-REMOVED")]))[0]
    assert change["id"] == "request-parameter-removed"


def test_an_unmapped_rule_is_namespaced_so_it_cannot_be_mistaken_for_theirs() -> None:
    change = export(_artifact([_finding(rule_id="BRK-FIELD-NUMBER-REUSED")]))[0]
    assert change["id"].startswith(FOREIGN_PREFIX)
    assert change["id"] == "x-apiverity-brk-field-number-reused"


def test_a_status_rule_picks_the_success_or_failure_variant_from_the_finding() -> None:
    """oasdiff splits these; the status is in the message, so it is read rather
    than guessed."""
    success = export(
        _artifact(
            [
                _finding(
                    rule_id="BRK-RESP-STATUS-REMOVED",
                    message="response status '200' was removed",
                )
            ]
        )
    )[0]
    other = export(
        _artifact(
            [
                _finding(
                    rule_id="BRK-RESP-STATUS-REMOVED",
                    message="response status '404' was removed",
                )
            ]
        )
    )[0]
    assert success["id"] == "response-success-status-removed"
    assert other["id"] == "response-non-success-status-removed"


def test_no_rule_maps_to_two_different_oasdiff_ids() -> None:
    assert not (set(MAPPING) & set(STATUS_MAPPING))


def test_no_rule_is_both_mapped_and_listed_as_unmappable() -> None:
    """The two tables would then disagree about the same rule, and the
    generated migration page would list it twice."""
    assert not (set(MAPPING) & set(NO_EXACT_MATCH))
    assert not (set(STATUS_MAPPING) & set(NO_EXACT_MATCH))


def test_every_mapped_and_excused_rule_is_a_real_rule() -> None:
    """A mapping for a rule that does not exist is a row nobody can reach, and
    it would sit in the published table looking like coverage."""
    invented = sorted((set(MAPPING) | set(STATUS_MAPPING) | set(NO_EXACT_MATCH)) - set(CATALOG))
    assert invented == []


def test_a_non_openapi_contract_is_namespaced_whatever_the_rule() -> None:
    """oasdiff reads OpenAPI. A removed gRPC RPC really is an endpoint
    removal, and saying so in their vocabulary would make a consumer's tooling
    report an OpenAPI removal that never happened."""
    change = export(
        _artifact([_finding(rule_id="BRK-OP-REMOVED")], protocol="grpc"),
    )[0]
    assert change["id"] == "x-apiverity-brk-op-removed"


def test_the_protocol_is_read_from_either_key_the_artifacts_use() -> None:
    """`validate` writes `protocol`; the diff commands write
    `protocol_version`. Reading only one would namespace every `breaking`
    export, which is the command this is for."""
    artifact = {"findings": [_finding()], "protocol_version": "openapi"}
    assert export(artifact)[0]["id"] == "api-removed-without-deprecation"


# ------------------------------------------------------- what is not written


def test_no_fingerprint_is_written() -> None:
    """oasdiff hashes its own change identity. A value computed differently
    would look like a fingerprint, compare unequal to theirs, and break the
    ignore-lists this export exists to preserve."""
    change = export(_artifact([_finding()]))[0]
    assert "fingerprint" not in change


def test_no_invented_attributes_or_section() -> None:
    change = export(_artifact([_finding()]))[0]
    assert "attributes" not in change
    assert "section" not in change
    assert "disclaimers" not in change


def test_the_coverage_report_says_which_version_it_was_checked_against() -> None:
    """A compatibility claim with no date and no version is not checkable."""
    detail = coverage()
    assert detail["oasdiff_version_checked"] == "v1.31.0"
    assert detail["checked_on"] == "2026-09-10"


# ------------------------------------------------------- the wiring and doc


def test_the_format_is_reachable_from_report() -> None:
    assert "oasdiff" in RENDERERS
    assert json.loads(RENDERERS["oasdiff"](_artifact([_finding()]))) != []


def test_an_artifact_with_no_findings_renders_an_empty_array() -> None:
    """Not `null`, and not a crash. A clean run through an existing pipeline
    has to produce something that pipeline can read."""
    assert export({"findings": [], "protocol": "openapi"}) == []
    assert json.loads(render({"protocol": "openapi"})) == []


def test_the_migration_document_is_not_stale() -> None:
    result = subprocess.run(
        [sys.executable, str(_ROOT / "scripts" / "generate_oasdiff_map.py"), "--check"],
        capture_output=True,
        text=True,
        cwd=_ROOT,
    )
    assert result.returncode == 0, result.stderr


def test_the_document_lists_every_rule_somewhere() -> None:
    """A rule that appears in neither table is a filter that stops matching
    with nothing written down about it."""
    text = _DOC.read_text(encoding="utf-8")
    missing = [rule for rule in CATALOG if f"`{rule}`" not in text]
    assert missing == [], f"docs/oasdiff-migration.md does not mention {missing}"
