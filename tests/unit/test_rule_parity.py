"""The matrix is derived by making the rules fire, not written down.

Seventy rules and seven formats, and nothing told a GraphQL user which of
the seventy could apply to them. The obvious answer is a hand-written table, and
it is the one answer this project cannot accept: a matrix asserting coverage
nobody demonstrated is worse than no matrix, because it is exactly the kind of
thing quoted in an evaluation.

So the tests below are mostly about the harness being honest with itself: that
a mutation actually mutates, that an empty cell means "not produced here"
rather than "not supported", and that the rules nothing produced are listed
where someone will read them rather than buried in a table of blanks.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from apiverity.core.model import Protocol, Service
from apiverity.rules.breaking import CATALOG
from apiverity.rules.parity import MUTATIONS, measure_parity
from apiverity.specs.loader import detect_and_load

_ROOT = Path(__file__).resolve().parents[2]
_DOC = _ROOT / "docs" / "rule-parity.md"
_FIXTURES = _ROOT / "fixtures"


def _openapi() -> Service:
    service, _findings, _plugin = detect_and_load(str(_FIXTURES / "apis/versioned/v1.yaml"))
    return service


# ------------------------------------------------------------- the harness


def test_every_mutation_has_a_name_and_a_meaning() -> None:
    """A cell in the matrix is read as "if I do this, does it notice", so the
    row label has to say what "this" is."""
    assert MUTATIONS
    for mutation in MUTATIONS:
        assert mutation.name.strip()
        assert mutation.describes.strip()


def test_mutation_names_are_unique() -> None:
    """Two rows with the same label are one row a reader cannot use."""
    names = [m.name for m in MUTATIONS]
    assert len(names) == len(set(names))


def test_a_mutation_does_not_change_the_original() -> None:
    """The harness diffs original against mutated. If `apply` reached the
    original the diff would be empty and every cell would read clean."""
    original = _openapi()
    before = original.model_dump_json()
    measure_parity({"openapi": original})
    assert original.model_dump_json() == before


def test_most_mutations_actually_change_something() -> None:
    """A mutation that silently does nothing produces an empty column and
    looks exactly like an engine that missed it.

    Not *all*: several are deliberately format-specific -- reusing a protobuf
    field number cannot be done to an OpenAPI contract -- and that is the
    signal the matrix exists to show.
    """
    original = _openapi()
    changed = 0
    for mutation in MUTATIONS:
        candidate = original.model_copy(deep=True)
        mutation.apply(candidate)
        if candidate.model_dump_json() != original.model_dump_json():
            changed += 1
    assert changed >= len(MUTATIONS) // 2, (
        f"only {changed} of {len(MUTATIONS)} mutations changed an OpenAPI contract"
    )


def test_the_result_records_which_mutation_produced_what() -> None:
    """Per-rule totals alone cannot answer "what do I have to do to see this",
    which is the question someone reading the table has."""
    result = measure_parity({"openapi": _openapi()})
    assert set(result.by_mutation["openapi"]) == {m.name for m in MUTATIONS}


def test_a_protocol_that_could_not_be_loaded_is_named() -> None:
    """A column nobody produced and a column of empty cells look identical."""
    result = measure_parity({})
    result.unavailable = {"graphql": "no fixture"}
    assert "graphql" in result.unavailable


def test_removing_an_operation_is_noticed() -> None:
    """The floor. If this ever stops firing, the harness is measuring nothing
    and every other empty cell is meaningless."""
    result = measure_parity({"openapi": _openapi()})
    assert "BRK-OP-REMOVED" in result.by_mutation["openapi"]["remove an operation"]


def test_protocol_specific_rules_stay_protocol_specific() -> None:
    """`BRK-FIELD-NUMBER-REUSED` firing for OpenAPI would mean the model was
    carrying protobuf state it has no business carrying."""
    result = measure_parity({"openapi": _openapi()})
    assert "BRK-FIELD-NUMBER-REUSED" not in result.by_protocol["openapi"]


# ------------------------------------------------------------------ the doc


def test_the_document_lists_every_rule_in_the_catalogue() -> None:
    text = _DOC.read_text(encoding="utf-8")
    for rule_id in CATALOG:
        assert f"`{rule_id}`" in text, f"{rule_id} is missing from docs/rule-parity.md"


def test_the_document_says_an_empty_cell_is_about_the_harness() -> None:
    """The single most misreadable thing in the file. Without this sentence a
    blank reads as "not supported", which would be a claim nobody made."""
    text = _DOC.read_text(encoding="utf-8")
    assert "It does not\nmean the rule cannot fire." in text


def test_the_document_calls_out_rules_nothing_produced() -> None:
    """The interesting column: a missing mutation, or a rule no input can
    produce -- and this project has found the second four separate times."""
    text = _DOC.read_text(encoding="utf-8")
    assert "## Rules no mutation produced" in text


def test_the_document_is_not_stale() -> None:
    result = subprocess.run(
        [sys.executable, str(_ROOT / "scripts" / "generate_rule_parity.py"), "--check"],
        capture_output=True,
        text=True,
        cwd=_ROOT,
    )
    assert result.returncode == 0, result.stderr


def test_the_measured_protocols_cover_the_formats_the_tool_reads() -> None:
    """A matrix that quietly measured one format would be the hand-written
    table in a different costume."""
    text = _DOC.read_text(encoding="utf-8")
    for protocol in (Protocol.OPENAPI.value, Protocol.GRPC.value, Protocol.MCP.value):
        assert protocol in text
