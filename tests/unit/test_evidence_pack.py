"""An evidence pack: records, not verdicts.

The temptation this module exists to resist is printing `SOC 2 CC8: PASS`.
Mapping a technical record to a clause of a regulation is a judgement about an
organisation, not about a file, and an auditor who found a tool making that
judgement would be right to distrust everything else in the pack.

So most of these tests check refusals: no scoring, no invented citations, and
a subject that says "not recorded" rather than guessing.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import re
from pathlib import Path
from typing import Any

import pytest

from apiverity.cli.commands.common import EXIT_OK, EXIT_USAGE
from apiverity.cli.main import main
from apiverity.reports.evidence import (
    PRACTICES,
    practices_for,
    read_artifact,
    render_pack,
    write_pack,
)

_STAMP = "2026-09-09T12:00:00Z"


def _artifact(command: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "tool": "apiverity",
        "tool_version": "0.0.0",
        "command": command,
        "contract_hash": "0" * 64,
        "findings": [{"rule_id": "X-Y", "severity": "ERROR", "message": "m"}],
    }
    payload.update(extra)
    return payload


def _write(tmp_path: Path, name: str, payload: dict[str, Any]) -> str:
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def _run(argv: list[str]) -> tuple[int, dict[str, Any], str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    text = out.getvalue()
    return code, (json.loads(text) if text.strip().startswith("{") else {}), err.getvalue()


# ------------------------------------------------------------- the citations


def test_every_reference_says_what_it_does_not_establish() -> None:
    """A citation with no limit reads as a claim that the clause is satisfied."""
    silent = [(p.id, ref.regime) for p in PRACTICES for ref in p.references if not ref.note.strip()]
    assert not silent, f"references with no stated limit: {silent}"


def test_every_reference_names_its_source() -> None:
    assert all(ref.source for practice in PRACTICES for ref in practice.references)


def test_no_practice_is_listed_without_a_reference() -> None:
    assert all(practice.references for practice in PRACTICES)


def test_iso_annex_a10_is_never_cited() -> None:
    """Its title could not be established, so it is absent rather than guessed."""
    cited = " ".join(ref.reference for p in PRACTICES for ref in p.references)
    assert "A.10" not in cited


def test_the_record_keeping_reference_refuses_the_obvious_overclaim() -> None:
    """A governance log is not the AI system's own log, and the pack says so."""
    ref = next(
        ref
        for practice in PRACTICES
        for ref in practice.references
        if "Articles 12 and 19" in ref.reference
    )
    assert "does not satisfy either" in ref.note


# ---------------------------------------------------------------- practices


def test_only_practices_with_evidence_behind_them_are_listed() -> None:
    """An empty row invites the reader to imagine it was done badly."""
    listed = {p.id for p in practices_for({"validate"})}
    assert "exposure" in listed
    assert "change-control" not in listed


def test_the_record_practice_always_applies() -> None:
    """It is about the pack itself, so it needs no particular command."""
    assert "record" in {p.id for p in practices_for(set())}


# ------------------------------------------------------------------ the pack


def test_the_pack_says_it_is_not_a_compliance_assessment() -> None:
    text = render_pack([], generated_at=_STAMP, tool_version="0.0.0")
    assert "It is not a compliance assessment" in text
    assert "the mapping is" in text


def test_the_pack_never_grades_a_control() -> None:
    """No verdict against a clause, anywhere in the rendering.

    The word `PASS` does appear once -- in the sentence explaining why the pack
    does not print it -- so the assertion is about a verdict *attached to a
    citation*, which is the thing that would be a lie.
    """
    text = render_pack([], generated_at=_STAMP, tool_version="0.0.0")
    # Table rows are where a verdict column would live, and a citation sits in
    # every one of them. The prose above the tables does say `CC8: PASS` once,
    # naming the thing it refuses to do; that sentence is the point, not a leak.
    verdicts = [
        line
        for line in text.splitlines()
        if line.startswith("|") and re.search(r"\b(PASS|FAIL|COMPLIANT|SATISFIED|MET)\b", line)
    ]
    assert not verdicts, verdicts
    assert text.count("PASS") == 1
    assert "would be" in next(line for line in text.splitlines() if "PASS" in line)


def test_the_pack_carries_the_date_it_was_made() -> None:
    assert _STAMP in render_pack([], generated_at=_STAMP, tool_version="0.0.0")


def test_the_pack_explains_why_it_is_not_reproducible() -> None:
    text = render_pack([], generated_at=_STAMP, tool_version="0.0.0")
    assert "an evidence record with no date is not evidence" in text


# ---------------------------------------------------------------- assembly


def test_a_pack_is_verifiable_with_the_existing_verify_command(tmp_path: Path) -> None:
    source = _write(tmp_path, "a.json", _artifact("validate", spec="api.yaml"))
    out = tmp_path / "pack"
    write_pack([source], out, generated_at=_STAMP, tool_version="0.0.0")

    code, payload, _ = _run(["verify", str(out), "--json"])
    assert code == EXIT_OK
    assert payload["verified"] is True
    assert payload["files_checked"] == len(list(out.iterdir())) - 1


def test_the_pack_is_flat_because_verify_reads_flat(tmp_path: Path) -> None:
    """A subdirectory would sit unverified inside a pack reporting itself verified."""
    source = _write(tmp_path, "a.json", _artifact("validate", spec="api.yaml"))
    out = tmp_path / "pack"
    write_pack([source], out, generated_at=_STAMP, tool_version="0.0.0")
    assert not [child for child in out.iterdir() if child.is_dir()]


def test_every_record_is_hashed_with_what_was_written(tmp_path: Path) -> None:
    source = _write(tmp_path, "a.json", _artifact("validate", spec="api.yaml"))
    out = tmp_path / "pack"
    (packed,) = write_pack([source], out, generated_at=_STAMP, tool_version="0.0.0")
    written = (out / packed.filename).read_bytes()
    assert hashlib.sha256(written).hexdigest() == packed.sha256


def test_a_compliance_view_is_rendered_for_every_record(tmp_path: Path) -> None:
    source = _write(tmp_path, "a.json", _artifact("validate", spec="api.yaml"))
    out = tmp_path / "pack"
    write_pack([source], out, generated_at=_STAMP, tool_version="0.0.0")
    names = {p.name for p in out.iterdir()}
    assert {"01-validate-owasp-mcp.md", "01-validate-owasp-asi.md", "01-validate-owasp-api.md"} <= (
        names
    )


def test_a_comparison_records_both_sides_as_its_subject(tmp_path: Path) -> None:
    source = _write(
        tmp_path, "b.json", _artifact("breaking", old_spec="v1.yaml", new_spec="v2.yaml")
    )
    out = tmp_path / "pack"
    (packed,) = write_pack([source], out, generated_at=_STAMP, tool_version="0.0.0")
    assert packed.subject == "v1.yaml -> v2.yaml"


def test_a_subject_is_never_invented(tmp_path: Path) -> None:
    source = _write(tmp_path, "c.json", _artifact("rules"))
    out = tmp_path / "pack"
    (packed,) = write_pack([source], out, generated_at=_STAMP, tool_version="0.0.0")
    assert packed.subject == "not recorded by this artifact"


def test_an_exported_bundle_directory_is_accepted(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "result.json").write_text(json.dumps(_artifact("validate")), encoding="utf-8")
    assert read_artifact(bundle)["command"] == "validate"


# --------------------------------------------------------------------- CLI


def test_the_command_reports_where_to_verify(tmp_path: Path) -> None:
    source = _write(tmp_path, "a.json", _artifact("validate", spec="api.yaml"))
    out = tmp_path / "pack"
    code, payload, _ = _run(["evidence", source, "-o", str(out), "--as-of", _STAMP, "--json"])
    assert code == EXIT_OK
    assert payload["records"] == 1
    assert payload["errors_across_records"] == 1
    assert payload["verify_with"].startswith("apiverity verify")


def test_a_missing_artifact_is_a_usage_error(tmp_path: Path) -> None:
    code, _, err = _run(["evidence", str(tmp_path / "nope.json"), "-o", str(tmp_path / "p")])
    assert code == EXIT_USAGE
    assert "not found" in err


def test_the_same_inputs_and_stamp_produce_the_same_pack(tmp_path: Path) -> None:
    """Only the date is allowed to vary; fixing it must fix everything."""
    source = _write(tmp_path, "a.json", _artifact("validate", spec="api.yaml"))
    first, second = tmp_path / "p1", tmp_path / "p2"
    write_pack([source], first, generated_at=_STAMP, tool_version="0.0.0")
    write_pack([source], second, generated_at=_STAMP, tool_version="0.0.0")
    assert (first / "SHA256SUMS").read_text(encoding="utf-8") == (
        (second / "SHA256SUMS").read_text(encoding="utf-8")
    )


@pytest.mark.parametrize("regime", ["SOC 2", "ISO/IEC 42001", "DORA", "EU AI Act"])
def test_each_named_regime_appears_somewhere(regime: str) -> None:
    assert any(ref.regime == regime for practice in PRACTICES for ref in practice.references)
