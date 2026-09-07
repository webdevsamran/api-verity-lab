"""Report fidelity: SARIF regions, self-contained HTML, honest JUnit (#22).

These drive the renderers with findings produced by a real diff of two real
specs rather than hand-built dicts, because the thing most likely to be wrong
is the plumbing between the parser's `SourceLocation` and the renderer -- and
a hand-built finding would supply exactly the fields the renderer expects and
prove nothing.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import pytest

from apiverity.diff.engine import diff_services
from apiverity.reports.renderers import RENDERERS, html, junit, markdown, sarif
from apiverity.rules.breaking import evaluate_breaking
from apiverity.specs.loader import detect_and_load

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "apis" / "versioned"


@pytest.fixture(scope="module")
def payload() -> dict[str, Any]:
    old, _, _ = detect_and_load(str(FIXTURES / "v1.yaml"))
    new, _, _ = detect_and_load(str(FIXTURES / "v2.yaml"))
    findings = evaluate_breaking(diff_services(old, new))
    assert findings, "the fixture pair must produce findings for these tests to mean anything"
    return {
        "command": "diff",
        "spec": str(FIXTURES / "v2.yaml"),
        "version": "0.1.0",
        "findings": [f.model_dump(mode="json") for f in findings],
    }


# --------------------------------------------------------------------- sarif


def test_sarif_carries_regions_from_the_parser(payload: dict[str, Any]) -> None:
    """The point of #22: line and column exist and used to be discarded."""
    results = json.loads(sarif(payload))["runs"][0]["results"]
    regions = [
        r["locations"][0]["physicalLocation"]["region"]
        for r in results
        if r.get("locations") and "region" in r["locations"][0]["physicalLocation"]
    ]
    assert regions, "no finding carried a region; SourceLocation is being dropped again"
    assert len(regions) >= len(results) - 1, (
        f"only {len(regions)} of {len(results)} findings have a region"
    )
    for region in regions:
        assert region["startLine"] >= 1
        assert region.get("startColumn", 1) >= 1


def test_sarif_omits_a_region_rather_than_emitting_line_zero() -> None:
    """SourceLocation defaults line to 0, and `startLine: 0` is invalid SARIF.

    GitHub rejects the entire upload on a schema violation, so one unlocated
    finding must not take the rest of the report down with it.
    """
    data = {
        "findings": [
            {
                "rule_id": "BRK-OP-REMOVED",
                "severity": "ERROR",
                "message": "no line known",
                "location": {"file": "spec.yaml", "line": 0, "column": 0, "pointer": "/paths"},
            }
        ]
    }
    location = json.loads(sarif(data))["runs"][0]["results"][0]["locations"][0]
    assert "region" not in location["physicalLocation"]
    assert location["physicalLocation"]["artifactLocation"]["uri"] == "spec.yaml"
    assert location["logicalLocations"][0]["fullyQualifiedName"] == "/paths"


def test_sarif_prefers_the_new_location(payload: dict[str, Any]) -> None:
    """A reviewer wants the line in the spec they are changing."""
    finding = {
        "rule_id": "BRK-ENUM-NARROWED-RESPONSE",
        "severity": "ERROR",
        "message": "m",
        "location": {"file": "v1.yaml", "line": 10, "column": 1},
        "new_location": {"file": "v2.yaml", "line": 20, "column": 2},
    }
    physical = json.loads(sarif({"findings": [finding]}))["runs"][0]["results"][0]["locations"][0][
        "physicalLocation"
    ]
    assert physical["artifactLocation"]["uri"] == "v2.yaml"
    assert physical["region"]["startLine"] == 20


def test_sarif_declares_the_rules_it_uses(payload: dict[str, Any]) -> None:
    run = json.loads(sarif(payload))["runs"][0]
    rules = run["tool"]["driver"]["rules"]
    assert rules, "no rule metadata; a SARIF viewer has nothing to describe an alert with"
    ids = [r["id"] for r in rules]
    assert ids == sorted(ids)
    for result in run["results"]:
        if "ruleIndex" in result:
            assert rules[result["ruleIndex"]]["id"] == result["ruleId"]
    assert any("shortDescription" in r for r in rules)


def test_sarif_fingerprints_are_stable_across_message_changes() -> None:
    """Messages embed concrete values, so keying alerts on them churns.

    A tightened constraint whose numbers change is the *same* problem in the
    same place; GitHub should update that alert, not retire it and raise a new
    one.
    """
    base = {
        "rule_id": "BRK-CONSTRAINT-TIGHTENED",
        "severity": "ERROR",
        "operation_key": "GET /users",
        "location": {"file": "v2.yaml", "line": 10, "column": 3, "pointer": "/paths/~1users"},
    }
    first = json.loads(sarif({"findings": [{**base, "message": "minimum 1 -> 10"}]}))
    second = json.loads(sarif({"findings": [{**base, "message": "minimum 1 -> 25"}]}))
    moved = json.loads(
        sarif(
            {
                "findings": [
                    {
                        **base,
                        "message": "minimum 1 -> 10",
                        "location": {**base["location"], "pointer": "/paths/~1orders"},
                    }
                ]
            }
        )
    )

    def fp(doc: dict[str, Any]) -> str:
        return str(doc["runs"][0]["results"][0]["partialFingerprints"]["apiverityFindingV1"])

    assert fp(first) == fp(second), "the same problem got a new identity when its numbers changed"
    assert fp(first) != fp(moved), "a different location must not share an identity"


def test_sarif_is_valid_against_the_published_schema(payload: dict[str, Any]) -> None:
    """Structural checks a viewer actually enforces."""
    doc = json.loads(sarif(payload))
    assert doc["version"] == "2.1.0"
    run = doc["runs"][0]
    assert run["tool"]["driver"]["name"] == "apiverity"
    for result in run["results"]:
        assert result["level"] in ("error", "warning", "note")
        assert isinstance(result["message"]["text"], str)
        for location in result.get("locations", []):
            uri = location["physicalLocation"]["artifactLocation"]["uri"]
            assert "\\" not in uri, f"SARIF uris must be forward-slashed, got {uri!r}"


# ---------------------------------------------------------------------- html


def test_html_is_fully_self_contained(payload: dict[str, Any]) -> None:
    """A report is usually opened from a CI artifact with no network."""
    doc = html(payload)
    for pattern in (r"<link\b", r"@import", r"@font-face", r"https?://[^\"'\s]+\.(?:css|js|woff)"):
        assert not re.search(pattern, doc, re.IGNORECASE), f"external reference: {pattern}"
    assert "<style>" in doc and "<script>" in doc


def test_html_escapes_content_from_the_spec(payload: dict[str, Any]) -> None:
    """Messages carry field names straight out of a user's document."""
    hostile = {
        "findings": [
            {
                "rule_id": "<img src=x onerror=alert(1)>",
                "severity": "ERROR",
                "message": "field '</td></tr><script>alert(2)</script>' changed",
                "hint": "a & b < c",
            }
        ]
    }
    doc = html(hostile)
    assert "<script>alert(2)</script>" not in doc
    assert "<img src=x" not in doc
    assert "&lt;script&gt;" in doc
    assert "a &amp; b &lt; c" in doc


def test_html_filter_state_lives_in_the_url_hash(payload: dict[str, Any]) -> None:
    doc = html(payload)
    assert "window.location.hash = 'sev=' +" in doc
    assert "hashchange" in doc
    assert 'data-severity="ERROR"' in doc
    assert 'data-sev="ALL"' in doc


def test_html_shows_the_location_column(payload: dict[str, Any]) -> None:
    doc = html(payload)
    assert "<th>Location</th>" in doc
    assert re.search(r"<code class=\"loc\"[^>]*>[^<]+:\d+", doc), "no file:line rendered"


# ------------------------------------------------------------------ markdown


def test_markdown_groups_severities_into_collapsible_sections(
    payload: dict[str, Any],
) -> None:
    doc = markdown(payload)
    assert "<details open>" in doc, "ERROR should not require a click to discover"
    assert "</details>" in doc
    assert "<summary><b>ERROR</b>" in doc


def test_markdown_escapes_pipes_so_a_table_cannot_be_split() -> None:
    """A field named `a|b` would silently corrupt every row after it."""
    doc = markdown(
        {"findings": [{"rule_id": "BRK-X", "severity": "ERROR", "message": "field 'a|b' removed"}]}
    )
    row = next(line for line in doc.splitlines() if "BRK-X" in line)
    assert r"a\|b" in row, f"the pipe was not escaped: {row!r}"
    # Count only the pipes markdown will treat as delimiters -- an escaped one
    # is still a `|` character, which is what makes this easy to get wrong.
    delimiters = row.replace(r"\|", "").count("|")
    assert delimiters == 3, f"row split into {delimiters - 1} columns: {row!r}"


def test_markdown_still_lists_the_summary_keys(payload: dict[str, Any]) -> None:
    doc = markdown(payload)
    assert "- **command**: diff" in doc


# --------------------------------------------------------------------- junit


def test_junit_emits_a_testcase_per_finding(payload: dict[str, Any]) -> None:
    """It used to declare tests="N" over an empty suite: every consumer read 0."""
    root = ET.fromstring(junit(payload))
    cases = root.findall("testcase")
    assert len(cases) == len(payload["findings"])
    assert root.get("tests") == str(len(cases))
    failures = [c for c in cases if c.find("failure") is not None]
    assert root.get("failures") == str(len(failures))
    assert failures, "the fixture pair has breaking findings; none became a failure"


def test_junit_is_well_formed_with_hostile_content() -> None:
    doc = junit(
        {
            "findings": [
                {
                    "rule_id": "BRK-X",
                    "severity": "ERROR",
                    "message": 'quote " and <tag> & amp',
                    "operation_key": "GET /a",
                }
            ]
        }
    )
    root = ET.fromstring(doc)  # raises if the escaping is wrong
    failure = root.find("testcase/failure")
    assert failure is not None
    assert failure.get("message") == 'quote " and <tag> & amp'


def test_junit_without_findings_falls_back_to_counters() -> None:
    root = ET.fromstring(junit({"total": 12, "failed": 3}))
    assert root.get("tests") == "12"
    assert root.get("failures") == "3"
    assert root.findall("testcase") == []


# ------------------------------------------------------------------ dispatch


def test_cli_report_uses_the_shared_renderers(tmp_path: Path, payload: dict[str, Any]) -> None:
    """`apiverity report` carried its own copy of every format, and they had
    already diverged -- its markdown had lost the findings table. One bundle
    must not produce two different reports depending on how it is asked for."""
    import argparse

    from apiverity.cli.commands.artifacts import cmd_report

    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "result.json").write_text(json.dumps(payload), encoding="utf-8")

    for name, renderer in RENDERERS.items():
        args = argparse.Namespace(bundle=str(bundle), format=name)
        assert cmd_report(args) == 0, f"format {name} failed through the CLI"
        assert renderer(payload), f"renderer {name} produced nothing"


def test_cli_report_rejects_an_unknown_format_by_listing_the_real_ones(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import argparse

    from apiverity.cli.commands.artifacts import cmd_report

    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "result.json").write_text("{}", encoding="utf-8")
    assert cmd_report(argparse.Namespace(bundle=str(bundle), format="pdf")) == 2
    err = capsys.readouterr().err
    assert "unknown format 'pdf'" in err
    assert "sarif" in err and "markdown" in err
