"""Every rule that objects has to say what to ship instead.

A gate that only says no gets switched off. "A response field was removed;
readers of it break" is correct and leaves the reader where they started: they
still want the field gone, and nothing has told them how to get there without
breaking anyone.

The value of the table is that a reader can rely on it being complete. A rule
with no guidance, in a list where every other rule has some, reads as a rule
nobody thought about -- so the completeness is a test rather than a habit.
"""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
from typing import Any

import pytest

from apiverity.core.model import Change, ChangeKind
from apiverity.rules.alternatives import ALTERNATIVES, alternative_for, contextual
from apiverity.rules.breaking import CATALOG

_ROOT = Path(__file__).resolve().parents[2]
_V1 = str(_ROOT / "fixtures/apis/versioned/v1.yaml")
_V2 = str(_ROOT / "fixtures/apis/versioned/v2.yaml")


def _run(argv: list[str]) -> tuple[int, dict[str, Any]]:
    from apiverity.cli.main import main

    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        code = main(argv)
    text = out.getvalue()
    return code, (json.loads(text) if text.strip().startswith("{") else {})


# --------------------------------------------------------------- completeness


def test_every_rule_in_the_catalogue_has_an_alternative() -> None:
    missing = sorted(set(CATALOG) - set(ALTERNATIVES))
    assert not missing, f"rules with nothing to suggest: {missing}"


def test_the_semver_rules_are_covered_too() -> None:
    """They live in another module and a reader does not care which."""
    assert {
        "SEMVER-MAJOR-REQUIRED",
        "SEMVER-MINOR-REQUIRED",
        "SEMVER-NO-BUMP",
        "SEMVER-DECREASE",
        "SEMVER-UNPARSEABLE",
    } <= set(ALTERNATIVES)


def test_no_alternative_describes_a_rule_that_does_not_exist() -> None:
    from apiverity.rules.semver import SemverPolicy  # noqa: F401 - imported for the ids below

    known = set(CATALOG) | {
        "SEMVER-MAJOR-REQUIRED",
        "SEMVER-MINOR-REQUIRED",
        "SEMVER-NO-BUMP",
        "SEMVER-DECREASE",
        "SEMVER-UNPARSEABLE",
    }
    invented = sorted(set(ALTERNATIVES) - known)
    assert not invented, f"advice for rules nothing emits: {invented}"


@pytest.mark.parametrize("rule_id", sorted(ALTERNATIVES))
def test_every_alternative_is_a_sentence_not_a_placeholder(rule_id: str) -> None:
    text = ALTERNATIVES[rule_id]
    assert len(text) > 30, f"{rule_id} says almost nothing"
    assert text[0].isupper() and text.rstrip().endswith("."), f"{rule_id} is not a sentence"


def test_a_rule_describing_something_safe_says_so_rather_than_inventing_advice() -> None:
    """Advice attached to a non-problem trains a reader to skim."""
    for rule_id in ("BRK-OP-ADDED", "BRK-RPC-ADDED", "BRK-RESP-FIELD-ADDED"):
        assert ALTERNATIVES[rule_id].startswith("Nothing to do")


def test_an_unsound_comparison_says_to_fix_the_run_not_the_change() -> None:
    """A truncated manifest is not a change with a smaller version of itself."""
    assert "fix the *capture*" in ALTERNATIVES["BRK-MCP-MANIFEST-TRUNCATED"]


def test_an_unknown_rule_has_no_alternative_rather_than_a_generic_one() -> None:
    assert alternative_for("BRK-NOT-A-RULE") is None


# ----------------------------------------------------------------- contextual


def test_a_narrowed_enum_names_the_value_to_keep_accepting() -> None:
    change = Change(
        id="CHG-1",
        kind=ChangeKind.ENUM_CHANGED,
        direction="request",
        operation_key="POST /users",
        description="enum narrowed",
        old_value=["admin", "guest"],
        new_value=["admin"],
    )
    text = contextual("BRK-ENUM-NARROWED-REQUEST", change)
    assert text is not None
    assert "'guest'" in text


def test_a_tightened_constraint_names_the_bound_that_moved() -> None:
    change = Change(
        id="CHG-2",
        kind=ChangeKind.PARAMETER_CONSTRAINT_CHANGED,
        direction="request",
        operation_key="GET /users",
        description="maximum tightened",
        old_value=100,
        new_value=50,
    )
    text = contextual("BRK-CONSTRAINT-TIGHTENED", change)
    assert text is not None
    assert "100 -> 50" in text


def test_everything_else_is_left_as_the_general_sentence() -> None:
    """Interpolating for its own sake makes a good sentence worse."""
    change = Change(
        id="CHG-3",
        kind=ChangeKind.OPERATION_REMOVED,
        direction="meta",
        operation_key="DELETE /users/{id}",
        description="removed",
    )
    assert contextual("BRK-OP-REMOVED", change) == ALTERNATIVES["BRK-OP-REMOVED"]


def test_no_change_means_the_general_sentence() -> None:
    assert contextual("BRK-OP-REMOVED", None) == ALTERNATIVES["BRK-OP-REMOVED"]


# ------------------------------------------------------------------- wiring


def test_explain_shows_what_to_ship_instead() -> None:
    _, payload = _run(["explain", "BRK-RESP-FIELD-REMOVED", "--json"])
    assert payload["instead"] == ALTERNATIVES["BRK-RESP-FIELD-REMOVED"]


def test_explain_answers_for_a_semver_rule_that_is_not_in_the_catalogue() -> None:
    """ "No such rule" for an id the tool really emits is the wrong answer."""
    code, payload = _run(["explain", "SEMVER-MAJOR-REQUIRED", "--json"])
    assert code == 0
    assert payload["instead"] == ALTERNATIVES["SEMVER-MAJOR-REQUIRED"]


def test_breaking_attaches_the_alternative_when_asked() -> None:
    _, payload = _run(["breaking", _V1, _V2, "--suggest-fix", "--json"])
    by_rule = {f["rule_id"]: f for f in payload["findings"]}
    assert by_rule["BRK-OP-REMOVED"]["metadata"]["instead"].startswith("Keep the operation")


def test_breaking_says_nothing_extra_unless_asked() -> None:
    """One more sentence per finding is a lot when there are forty."""
    _, payload = _run(["breaking", _V1, _V2, "--json"])
    assert all("instead" not in (f.get("metadata") or {}) for f in payload["findings"])


def test_the_attached_alternative_is_the_contextual_one() -> None:
    _, payload = _run(["breaking", _V1, _V2, "--suggest-fix", "--json"])
    finding = next(f for f in payload["findings"] if f["rule_id"] == "BRK-ENUM-NARROWED-REQUEST")
    assert "'guest'" in finding["metadata"]["instead"]


def test_the_published_catalogue_carries_the_column() -> None:
    """`--check` runs in CI; failing here too is faster feedback."""
    text = (_ROOT / "docs" / "rule-catalog.md").read_text(encoding="utf-8")
    assert "| Rule | Severity | Fires when | Instead |" in text
    assert ALTERNATIVES["BRK-OP-REMOVED"] in text
