"""Plain-English summaries for a pull request description.

`changelog` renders every change grouped by operation, which is right for a
release note and wrong for a PR body, where the reader wants three sentences
and a decision.

Deterministic templates, no model call: a summary a language model writes is
one nobody can diff, nobody can test, and nobody can run in CI without a
network-egress conversation -- and the structured diff already contains
everything the sentences need.
"""

from __future__ import annotations

from apiverity.core.model import Change, ChangeKind, Finding, Severity
from apiverity.rules.summary import summarize


def _finding(rule_id: str, severity: Severity = Severity.ERROR) -> Finding:
    return Finding(rule_id=rule_id, severity=severity, message="x")


def _change(n: int = 1) -> list[Change]:
    return [
        Change(
            id=f"CHG-X-{i}",
            kind=ChangeKind.DESCRIPTION_CHANGED,
            direction="meta",
            operation_key="k",
            description="d",
        )
        for i in range(n)
    ]


def test_a_breaking_change_says_so_first() -> None:
    """The reader decides from the first line."""
    summary = summarize(_change(3), [_finding("BRK-OP-REMOVED")])
    assert summary.verdict.startswith("**This change is breaking.**")
    assert "1 finding at ERROR" in summary.verdict
    assert "3 changes" in summary.verdict


def test_warnings_alone_are_risky_not_breaking() -> None:
    summary = summarize(_change(), [_finding("BRK-ENUM-NARROWED-RESPONSE", Severity.WARN)])
    assert "risky but not breaking" in summary.verdict


def test_changes_with_no_findings_are_compatible() -> None:
    summary = summarize(_change(2), [])
    assert "backward compatible" in summary.verdict


def test_no_changes_says_nothing_changed() -> None:
    summary = summarize([], [])
    assert "No contract changes" in summary.verdict
    assert summary.what_changed == []


def test_findings_of_one_kind_become_one_counted_sentence() -> None:
    """Twenty findings of one kind is one sentence, not twenty."""
    summary = summarize(_change(20), [_finding("BRK-RESP-FIELD-REMOVED") for _ in range(20)])
    assert summary.what_changed == ["Response fields were removed (20)"]


def test_a_single_finding_is_not_given_a_count() -> None:
    summary = summarize(_change(), [_finding("BRK-RESP-FIELD-REMOVED")])
    assert summary.what_changed == ["Response fields were removed"]


def test_the_suggested_version_is_quoted_when_known() -> None:
    """ "Release this as 2.0.0" beats "release behind a major version bump"."""
    summary = summarize(_change(), [_finding("BRK-OP-REMOVED")], suggested_version="2.0.0")
    assert any("2.0.0" in item for item in summary.what_to_do)


def test_without_advice_it_still_says_what_to_do() -> None:
    summary = summarize(_change(), [_finding("BRK-OP-REMOVED")])
    assert any("major version bump" in item for item in summary.what_to_do)


def test_it_offers_the_additive_alternative() -> None:
    """A tool that only blocks gets uninstalled."""
    summary = summarize(_change(), [_finding("BRK-OP-REMOVED")])
    joined = " ".join(summary.what_to_do)
    assert "deprecate" in joined and "optional" in joined


def test_named_consumers_reach_the_summary() -> None:
    summary = summarize(
        _change(), [_finding("BRK-OP-REMOVED")], consumers=["checkout-service", "mobile-v3"]
    )
    assert any("checkout-service" in item for item in summary.what_to_do)


def test_an_unknown_rule_is_named_rather_than_paraphrased() -> None:
    """No invented phrasing for a rule the phrase table does not know.

    The id is accurate and `apiverity explain` will describe it; a guessed
    sentence would not be either.
    """
    summary = summarize(_change(), [_finding("BRK-SOMETHING-NEW")])
    assert summary.what_changed == ["BRK-SOMETHING-NEW fired"]


def test_the_markdown_has_the_same_three_parts_every_time() -> None:
    """A reader skimming twenty pull requests learns the shape once."""
    markdown = summarize(_change(), [_finding("BRK-OP-REMOVED")]).as_markdown()
    assert markdown.startswith("**This change is breaking.**")
    assert "**What changed**" in markdown
    assert "**What to do**" in markdown


def test_it_is_deterministic() -> None:
    """No model call, so the same input must give byte-identical output."""
    findings = [_finding("BRK-OP-REMOVED"), _finding("BRK-PARAM-REMOVED")]
    first = summarize(_change(2), findings).as_markdown()
    second = summarize(_change(2), findings).as_markdown()
    assert first == second
