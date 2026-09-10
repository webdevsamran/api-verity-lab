"""The pull request comment, and the one thing that makes it worth posting.

A gate that only says no gets switched off. So this renderer leads with the
non-breaking route to the same change and treats the objection as the evidence
for it -- which is a different document from the markdown report, not the same
one with another heading.

Three properties are load-bearing and each is tested here rather than assumed:
one comment per pull request (a marker the workflow can find, so it edits
instead of adding), one block per *rule* (forty rows followed by the same
paragraph forty times is noise), and a body that fits GitHub's size limit while
saying what it dropped.
"""

from __future__ import annotations

from typing import Any

from apiverity.reports.renderers import (
    PR_COMMENT_BUDGET,
    PR_MARKER,
    RENDERERS,
    pr_comment,
)
from apiverity.rules.breaking import CATALOG
from apiverity.rules.summary import _phrase_for


def _finding(rule_id: str, severity: str = "ERROR", **extra: Any) -> dict[str, Any]:
    finding: dict[str, Any] = {
        "rule_id": rule_id,
        "severity": severity,
        "message": f"{rule_id} happened",
    }
    finding.update(extra)
    return finding


def _payload(*findings: dict[str, Any], **extra: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "tool": "apiverity",
        "command": "breaking",
        "old_spec": "openapi/v1.yaml",
        "new_spec": "openapi/v2.yaml",
        "findings": list(findings),
    }
    data.update(extra)
    return data


# ------------------------------------------------------------------ verdict


def test_a_clean_run_says_so_rather_than_staying_silent() -> None:
    """A gate is evidence when it passes, not only when it fails."""
    body = pr_comment(_payload())
    assert "Clear" in body
    assert "No breaking changes found." in body


def test_an_error_blocks_and_a_warning_only_asks_for_review() -> None:
    assert "Blocked" in pr_comment(_payload(_finding("BRK-RESP-FIELD-REMOVED")))
    assert "Needs review" in pr_comment(_payload(_finding("BRK-HEADER-REMOVED", severity="WARN")))


# ------------------------------------------------------------- the marker


def test_the_comment_carries_a_marker_the_workflow_can_find() -> None:
    """One comment per pull request, edited in place.

    A bot with twelve comments on a busy branch gets muted, and a muted gate
    is the same as no gate. The workflow finds its own previous comment by
    this marker, so it has to be present, first, and exactly once.
    """
    body = pr_comment(_payload(_finding("BRK-RESP-FIELD-REMOVED")))
    assert body.startswith(PR_MARKER)
    assert body.count(PR_MARKER) == 1


# ------------------------------------------------- the alternative leads


def test_the_alternative_is_shown_before_the_objection() -> None:
    body = pr_comment(
        _payload(
            _finding(
                "BRK-RESP-FIELD-REMOVED",
                metadata={"instead": "Deprecate it with a sunset date instead."},
            )
        )
    )
    instead = body.index("Deprecate it with a sunset date instead.")
    changed = body.index("BRK-RESP-FIELD-REMOVED happened")
    assert instead < changed


def test_a_hint_is_never_shown_as_an_alternative() -> None:
    """A hint says *why* it breaks, which is the opposite instruction.

    `enum values removed: ['guest']` under "Instead:" tells an author to do
    the thing the finding just objected to.
    """
    body = pr_comment(
        _payload(_finding("BRK-ENUM-NARROWED-REQUEST", hint="enum values removed: ['guest']"))
    )
    assert "**Instead:**" not in body


def test_findings_are_grouped_by_rule_not_repeated_per_finding() -> None:
    """The alternative appears once for forty findings, not forty times."""
    alternative = "Add it as optional and default it server-side."
    body = pr_comment(
        _payload(
            *[
                _finding(
                    "BRK-REQ-FIELD-ADDED-REQUIRED",
                    message=f"field {i} was added",
                    metadata={"instead": alternative},
                )
                for i in range(40)
            ]
        )
    )
    assert body.count(alternative) == 1
    assert "40 findings" in body
    assert "field 39 was added" in body


def test_rules_are_ordered_worst_and_widest_first() -> None:
    body = pr_comment(
        _payload(
            _finding("BRK-HEADER-REMOVED", severity="WARN"),
            _finding("BRK-RESP-FIELD-REMOVED"),
            _finding("BRK-RESP-FIELD-REMOVED", message="another"),
            _finding("BRK-REQ-BODY-REMOVED"),
        )
    )
    order = [
        body.index("`BRK-RESP-FIELD-REMOVED`"),
        body.index("`BRK-REQ-BODY-REMOVED`"),
        body.index("`BRK-HEADER-REMOVED`"),
    ]
    assert order == sorted(order), "errors before warnings, and the widest rule first"


# ------------------------------------------------------------- the budget


def test_a_huge_diff_fits_and_says_what_it_dropped() -> None:
    """Silent truncation reads as "that was everything"."""
    long_message = "a very long finding message " * 40
    body = pr_comment(
        _payload(
            *[_finding(f"BRK-RULE-{i:04d}", message=f"{i}: {long_message}") for i in range(400)]
        )
    )
    assert len(body) <= 65_536
    assert len(body) <= PR_COMMENT_BUDGET + 2_000
    assert "omitted to fit GitHub's comment size limit" in body


def test_nothing_is_dropped_when_it_all_fits() -> None:
    body = pr_comment(_payload(_finding("BRK-RESP-FIELD-REMOVED")))
    assert "omitted to fit" not in body


# ------------------------------------------------------------- the summary


def test_the_summary_block_is_rendered_rather_than_rewritten() -> None:
    """`breaking --summary` already produces the three parts a reviewer wants.

    Writing a second version of it here is how the two would drift, which is
    the defect that split this module's markdown from the CLI's in the first
    place.
    """
    body = pr_comment(
        _payload(
            _finding("BRK-RESP-FIELD-REMOVED"),
            summary={
                "verdict": "**This change is breaking.**",
                "what_changed": ["response fields were removed"],
                "what_to_do": ["Release this as **2.0.0**, not a patch."],
            },
        )
    )
    assert "**This change is breaking.**" in body
    assert "- response fields were removed" in body
    assert "Release this as **2.0.0**, not a patch." in body


def test_the_version_is_not_stated_twice() -> None:
    """The summary's `what_to_do` opens with it; repeating it reads as a
    template nobody looked at."""
    body = pr_comment(
        _payload(
            _finding("BRK-RESP-FIELD-REMOVED"),
            version_advice={"suggested_version": "2.0.0", "required_bump": "major"},
            summary={
                "verdict": "**Breaking.**",
                "what_changed": [],
                "what_to_do": ["Release this as **2.0.0**, not a patch."],
            },
        )
    )
    assert body.count("2.0.0") == 1


def test_the_version_is_stated_when_there_is_no_summary() -> None:
    body = pr_comment(
        _payload(
            _finding("BRK-RESP-FIELD-REMOVED"),
            version_advice={"suggested_version": "2.0.0", "required_bump": "major"},
        )
    )
    assert "Release this as **2.0.0** (a major bump)." in body


# ---------------------------------------------------------------- registry


def test_the_format_is_reachable_from_apiverity_report() -> None:
    """A renderer nothing dispatches to is a renderer nobody can run."""
    assert RENDERERS["pr-comment"] is pr_comment


# ------------------------------------------ every rule has a phrase (guard)


def test_every_rule_in_the_catalogue_has_a_plain_english_phrase() -> None:
    """The summary exists for the reader who will not look a rule up.

    Twenty-four of sixty-five rules fell through to "BRK-HEADER-REMOVED
    fired", which is accurate and tells that reader nothing. This guard is
    what stops the next rule shipping the same way; the fallback stays for a
    plugin's rule, which this catalogue does not know about.
    """
    unphrased = sorted(r for r in CATALOG if _phrase_for(r).endswith(" fired"))
    assert unphrased == [], f"rules with no summary phrase: {unphrased}"


def test_a_specific_phrase_is_not_shadowed_by_a_general_prefix() -> None:
    """`_phrase_for` takes the first prefix that matches.

    So `BRK-CONSTRAINT-TIGHTENED` sitting above `BRK-CONSTRAINT-LOOSENED`
    would give both the same sentence -- and the second one says the opposite
    of the first.
    """
    pairs = [
        ("BRK-CONSTRAINT-TIGHTENED", "BRK-CONSTRAINT-LOOSENED"),
        ("BRK-PARAM-ADDED-REQUIRED", "BRK-PARAM-ADDED-OPTIONAL"),
        ("BRK-REQ-BODY-ADDED-REQUIRED", "BRK-REQ-BODY-ADDED-OPTIONAL"),
        ("BRK-RESP-FIELD-REMOVED", "BRK-RESP-FIELD-ADDED"),
        ("BRK-ENUM-NARROWED-REQUEST", "BRK-ENUM-WIDENED"),
    ]
    for a, b in pairs:
        assert _phrase_for(a) != _phrase_for(b), f"{a} and {b} share a phrase"


def test_an_unknown_rule_still_names_itself() -> None:
    """A plugin's rule is not in this catalogue, and must not be swallowed."""
    phrase = _phrase_for("XYZ-SOMETHING-A-PLUGIN-EMITTED")
    assert "XYZ-SOMETHING-A-PLUGIN-EMITTED" in phrase
