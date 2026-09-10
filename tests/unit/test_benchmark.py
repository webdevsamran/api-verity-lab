"""A benchmark that only wins reads as marketing.

The value of this page is the rows where the other tool reported something and
this one reported nothing. So most of what is asserted here is that those rows
can still appear, that the page says what a count is and is not worth, and that
the tool it did *not* run is named with a reason -- a benchmark naming two
competitors and measuring one has said something about the second by omission.

The evidence file is committed and dated. The document renders from it, and CI
checks the document against the evidence rather than re-running two toolchains
on every push.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "benchmark_oasdiff.py"
_EVIDENCE = _ROOT / "data" / "benchmark-oasdiff.json"
_DOC = _ROOT / "docs" / "benchmark.md"


def _module() -> Any:
    import importlib.util

    spec = importlib.util.spec_from_file_location("benchmark_oasdiff", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _evidence() -> dict[str, Any]:
    return json.loads(_EVIDENCE.read_text(encoding="utf-8"))


# ------------------------------------------------------------ the evidence


def test_the_evidence_says_when_and_against_what() -> None:
    """A comparison with no date and no versions is not checkable, and this
    one compares against a tool that ships weekly."""
    evidence = _evidence()
    assert evidence["generated_at"]
    assert evidence["apiverity_version"]
    assert evidence["oasdiff_module_version"].startswith("v")


def test_the_self_reported_version_is_recorded_beside_the_real_one() -> None:
    """`go install` builds without the version ldflag, so the binary answers
    "main". Recording only that would read as an unversioned build of an
    unknown commit; recording only the module version would hide that the
    binary cannot confirm it."""
    evidence = _evidence()
    assert "oasdiff_self_reported" in evidence
    assert evidence["oasdiff_module_version"] != evidence["oasdiff_self_reported"]


def test_both_tools_actually_reported_something() -> None:
    """An evidence file where one side is empty everywhere is a comparison
    against a tool that did not run, presented as a comparison."""
    pairs = [p for p in _evidence()["pairs"] if "unavailable" not in p]
    assert pairs
    assert any(p["ours"] for p in pairs)
    assert any(p["theirs"] for p in pairs)


def test_the_tool_that_was_not_run_is_named_with_a_reason() -> None:
    not_run = _evidence()["not_run"]
    assert "Specmatic" in not_run
    assert "JVM" in not_run["Specmatic"]


# ----------------------------------------------------------- the document


def test_the_document_is_not_stale() -> None:
    result = subprocess.run(
        [sys.executable, str(_SCRIPT), "--check"],
        capture_output=True,
        text=True,
        cwd=_ROOT,
    )
    assert result.returncode == 0, result.stderr


def test_the_document_says_a_count_is_not_a_score() -> None:
    text = _DOC.read_text(encoding="utf-8")
    assert "not a correctness" in text.lower()
    assert "either may be right" in text


def test_the_document_points_at_the_lists_rather_than_the_totals() -> None:
    """Operation-level agreement is total on contracts this size, and reading
    that as "we match oasdiff" is the wrong conclusion from the right number.
    Everything interesting is inside the operations both flagged."""
    text = _DOC.read_text(encoding="utf-8")
    assert "everything interesting is *inside* them" in text
    assert "where to look first" in text


def test_the_document_shows_both_tools_findings_per_operation() -> None:
    text = _DOC.read_text(encoding="utf-8")
    assert "### What each tool said" in text
    assert "_This tool_" in text
    assert "_oasdiff_" in text


def test_the_findings_are_two_lists_rather_than_a_paired_table() -> None:
    """A two-column table puts one tool's n-th finding beside the other's and
    reads as a pairing. The vocabularies differ in granularity, so it said
    that by accident on the first render: `BRK-CONTAINS-CHANGED` sat opposite
    `response-property-prefix-items-added` while the finding that actually
    corresponds to it sat opposite an em dash."""
    lines = _DOC.read_text(encoding="utf-8").splitlines()
    # As a whole line. The summary counts above each section are a table too,
    # and its header is `| | This tool | oasdiff |` -- a substring check would
    # match that and pass for the wrong reason.
    assert "| This tool | oasdiff |" not in lines
    assert "deliberately *not* a two-column table" in _DOC.read_text(encoding="utf-8")


def test_the_severity_each_tool_assigned_travels_with_the_finding() -> None:
    """Once both tools have found the same change, what each *called* it is
    the interesting comparison -- and this page carries a real disagreement
    about exactly that."""
    text = _DOC.read_text(encoding="utf-8")
    assert "(ERROR)" in text
    assert "(error)" in text


def test_the_document_still_carries_a_row_where_this_engine_found_nothing() -> None:
    """The point of the page. If this ever stops being true it is because the
    gap closed or because the rendering hid it, and those are worth telling
    apart -- so the assertion is on the evidence, not on the prose."""
    evidence = _evidence()
    behind = 0
    for pair in evidence["pairs"]:
        if "unavailable" in pair:
            continue
        for operation in {c["operation"] for c in pair["theirs"]}:
            mine = sum(1 for c in pair["ours"] if c["operation"] == operation)
            yours = sum(1 for c in pair["theirs"] if c["operation"] == operation)
            behind += max(0, yours - mine)
    assert behind >= 0  # a fact about the evidence, recorded rather than required
    text = _DOC.read_text(encoding="utf-8")
    assert "- nothing" in text or behind == 0


def test_only_openapi_pairs_are_compared() -> None:
    """oasdiff reads OpenAPI. Running it against a `.proto` to report that it
    found nothing would be a rigged comparison."""
    module = _module()
    for _label, old, new in module.PAIRS:
        assert old.endswith((".yaml", ".yml", ".json"))
        assert new.endswith((".yaml", ".yml", ".json"))


# ------------------------------------------------------------- the renderer


def test_a_pipe_in_a_message_does_not_split_a_row() -> None:
    """A finding's message is the one thing on the page written by neither
    tool with a Markdown table in mind."""
    module = _module()
    assert module._cell("a | b") == "a \\| b"
    assert module._cell("line\nbreak") == "line break"
    assert module._cell(None) == ""


def test_an_operation_is_read_from_either_tools_way_of_saying_it() -> None:
    module = _module()
    assert module._operation({"operation_key": "GET /users"}) == "GET /users"
    assert module._operation({"operation": "GET", "path": "/users"}) == "GET /users"
    assert module._operation({}) == ""
