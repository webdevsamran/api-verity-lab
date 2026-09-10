"""Behaviour that changed while the contract stayed valid.

Every other check here asks whether reality matches the document. This one asks
whether reality matches itself. The three cases it exists for are all
contract-valid, which is precisely why nothing else catches them: an optional
field that stops being populated, an enum value that stops appearing, a null
rate that jumps. The schema is satisfied in each, the drift check is silent,
and the consumer is broken.

The hardest thing to get right is not detection -- it is *silence*. A field
seen three times and then twice has not changed behaviour, it has been observed
badly, and a check that reported both would be worse than no check. So half of
what follows is about the comparisons this refuses to make.
"""

from __future__ import annotations

from typing import Any

from apiverity.core.model import (
    Operation,
    Protocol,
    Response,
    SchemaNode,
    Service,
)
from apiverity.runtime.semantic import (
    DISTINCT_VALUE_CAP,
    MIN_SAMPLES,
    compare_profiles,
    profile_corpus,
)


def _service() -> Service:
    return Service(
        title="fixture",
        version="1.0.0",
        protocol=Protocol.OPENAPI,
        operations=[
            Operation(
                operation_id="listThings",
                method="GET",
                path="/things",
                responses=[
                    Response(
                        status="200",
                        content={"application/json": SchemaNode(type="object")},
                    )
                ],
            )
        ],
    )


def _entry(body: Any) -> dict[str, Any]:
    """One `import_har` entry, in the flat shape the traffic importer emits."""
    return {
        "method": "GET",
        "url": "https://api.test/things",
        "status": 200,
        "response_body": body,
    }


def _corpus(bodies: list[Any], source: str) -> Any:
    return profile_corpus(_service(), [_entry(b) for b in bodies], source=source)


def _compare(before: list[Any], after: list[Any], **kwargs: Any):
    return compare_profiles(_corpus(before, "before"), _corpus(after, "after"), **kwargs)


def _rules(report: Any) -> dict[str, str]:
    return {f.rule_id: f.message for f in report.findings}


N = MIN_SAMPLES


# --------------------------------------------------------------- profiling


def test_a_profile_records_presence_null_and_values() -> None:
    profile = _corpus(
        [{"id": "1", "tier": "free"}, {"id": "2", "tier": None}, {"id": "3"}],
        "c",
    )
    fields = profile.operations["GET /things"].fields
    assert fields["$.id"].present == 3
    assert fields["$.tier"].present == 2
    assert fields["$.tier"].nulls == 1
    assert fields["$.tier"].values == ["free"]


def test_array_positions_collapse_into_one_field() -> None:
    """Index 0 and index 4 are the same field.

    Keying on the index would make a list of fifty look like fifty fields, none
    of which has enough observations to say anything about.
    """
    profile = _corpus([{"items": [{"status": "a"}, {"status": "b"}]}], "c")
    fields = profile.operations["GET /things"].fields
    assert "$.items[].status" in fields
    assert sorted(fields["$.items[].status"].values) == ["a", "b"]


def test_one_response_counts_once_however_many_array_elements() -> None:
    """Otherwise a list of fifty makes one response look like fifty."""
    profile = _corpus([{"items": [{"x": 1} for _ in range(50)]}], "c")
    field = profile.operations["GET /things"].fields["$.items[].x"]
    assert field.present == 1
    assert field.observations == 1


def test_a_high_cardinality_field_stops_tracking_values() -> None:
    """A profile that recorded every id would be a copy of the corpus, which is
    the thing this exists to avoid having to keep."""
    profile = _corpus([{"id": str(i)} for i in range(DISTINCT_VALUE_CAP + 5)], "c")
    field = profile.operations["GET /things"].fields["$.id"]
    assert field.unbounded is True
    assert field.values == []


def test_a_response_with_no_body_still_counts_as_an_observation() -> None:
    """Excluding it would inflate every presence rate in the profile."""
    profile = _corpus([{"id": "1"}, None, "plain text"], "c")
    op = profile.operations["GET /things"]
    assert op.responses == 3
    assert op.fields["$.id"].observations == 3
    assert op.fields["$.id"].presence_rate < 0.4


# ----------------------------------------------------- the abandoned field


def test_a_field_that_stops_being_populated_is_an_error() -> None:
    """The case this whole module exists for.

    `email` is optional, so the schema is satisfied, `validate` is happy,
    corpus drift is silent -- and every consumer reading it gets nothing.
    """
    before = [{"id": str(i), "email": f"{i}@test"} for i in range(N)]
    after = [{"id": str(i)} for i in range(N)]
    fired = _rules(_compare(before, after))
    assert "SEMANTIC-FIELD-ABANDONED" in fired
    assert "every consumer reading it now gets nothing" in fired["SEMANTIC-FIELD-ABANDONED"]


def test_a_field_that_became_intermittent_is_a_warning() -> None:
    before = [{"id": str(i), "email": "x"} for i in range(N)]
    after = [{"id": str(i), **({"email": "x"} if i < 4 else {})} for i in range(N)]
    assert "SEMANTIC-FIELD-INTERMITTENT" in _rules(_compare(before, after))


def test_a_new_field_is_reported_as_a_note() -> None:
    before = [{"id": str(i)} for i in range(N)]
    after = [{"id": str(i), "tier": "free"} for i in range(N)]
    fired = _rules(_compare(before, after))
    assert fired["SEMANTIC-FIELD-APPEARED"]


def test_an_unchanged_service_reports_nothing() -> None:
    bodies = [{"id": str(i), "tier": "free"} for i in range(N)]
    report = _compare(bodies, bodies)
    assert report.findings == []
    assert report.compared > 0


def test_ordinary_wobble_is_not_reported() -> None:
    """Real traffic is not uniform, and a check that fires on noise is one
    people learn to ignore."""
    before = [{"id": str(i), "note": "x"} for i in range(N)]
    after = [{"id": str(i), **({"note": "x"} if i else {})} for i in range(N)]
    assert _compare(before, after).findings == []


# ---------------------------------------------------------------- values


def test_a_value_that_stopped_appearing_is_reported() -> None:
    """The dead-branch case. `archived` is still in the enum, and nothing has
    returned it since the migration."""
    before = [{"status": ["pending", "active", "archived"][i % 3]} for i in range(N)]
    after = [{"status": ["pending", "active"][i % 2]} for i in range(N)]
    fired = _rules(_compare(before, after))
    assert "SEMANTIC-VALUE-GONE" in fired
    assert "archived" in fired["SEMANTIC-VALUE-GONE"]


def test_a_new_value_is_reported() -> None:
    before = [{"status": "active"} for _ in range(N)]
    after = [{"status": ["active", "suspended"][i % 2]} for i in range(N)]
    fired = _rules(_compare(before, after))
    assert "suspended" in fired["SEMANTIC-VALUE-NEW"]


def test_an_unbounded_field_is_not_compared_by_value() -> None:
    """Every id is new every time. Reporting that would be reporting that ids
    are ids."""
    before = [{"id": f"a{i}"} for i in range(max(N, DISTINCT_VALUE_CAP + 5))]
    after = [{"id": f"b{i}"} for i in range(max(N, DISTINCT_VALUE_CAP + 5))]
    fired = _rules(_compare(before, after))
    assert "SEMANTIC-VALUE-GONE" not in fired
    assert "SEMANTIC-VALUE-NEW" not in fired


# ------------------------------------------------------------- null rates


def test_a_null_rate_that_jumped_is_reported() -> None:
    before = [{"tier": "free" if i else None} for i in range(N)]
    after = [{"tier": None if i else "free"} for i in range(N)]
    fired = _rules(_compare(before, after))
    assert "SEMANTIC-NULL-RATE-ROSE" in fired


def test_a_null_rate_that_fell_is_not_reported() -> None:
    """More data than before is not a regression."""
    before = [{"tier": None} for _ in range(N)]
    after = [{"tier": "free"} for _ in range(N)]
    assert "SEMANTIC-NULL-RATE-ROSE" not in _rules(_compare(before, after))


# ------------------------------------------------------ refusing to speak


def test_too_few_responses_produces_no_finding() -> None:
    """Three responses then two is not evidence of anything.

    This is the assertion that makes the rest of the module trustworthy: a
    check that reported a change from a handful of samples would be confidently
    wrong most of the time.
    """
    before = [{"id": "1", "email": "x"} for _ in range(3)]
    after = [{"id": "1"} for _ in range(2)]
    report = _compare(before, after)
    assert report.findings == []
    assert report.skipped_for_samples > 0


def test_what_could_not_be_compared_is_counted() -> None:
    """ "Nothing changed" and "we could not tell" are different answers, and
    only one of them is reassuring."""
    report = _compare([{"a": 1}], [{"a": 1}])
    assert report.compared == 0
    assert report.skipped_for_samples > 0


def test_the_sample_threshold_is_adjustable() -> None:
    before = [{"id": "1", "email": "x"} for _ in range(4)]
    after = [{"id": "1"} for _ in range(4)]
    assert _compare(before, after).findings == []
    assert _compare(before, after, min_samples=3).findings


def test_an_operation_absent_from_the_earlier_corpus_is_skipped() -> None:
    """There is no "before" to compare against, and treating an absence as a
    zero would report every field of a newly-exercised operation as new."""
    report = compare_profiles(_corpus([], "before"), _corpus([{"a": 1}] * N, "after"))
    assert report.findings == []


def test_every_finding_carries_the_evidence_behind_it() -> None:
    """So a reader can judge the claim instead of trusting it."""
    before = [{"id": str(i), "email": "x"} for i in range(N)]
    after = [{"id": str(i)} for i in range(N)]
    finding = next(
        f for f in _compare(before, after).findings if f.rule_id == "SEMANTIC-FIELD-ABANDONED"
    )
    assert finding.before["present"] == N
    assert finding.after["present"] == 0
    assert finding.before["observations"] == N


# ------------------------------------------------------- the shipped pair


def test_the_shipped_corpora_show_a_change_nothing_else_reports() -> None:
    """The fixture pair is the claim, run.

    `fixtures/traffic/users-march.har` and `users-april.har` are the same
    operation a month apart. `email` stops being populated and `archived`
    stops appearing -- both legal under the contract, so `drift --corpus`
    reports nothing at all on the later one. If that ever stops being true the
    fixture has lost its point, and this test says so.
    """
    from pathlib import Path

    from apiverity.runtime.corpus_drift import analyze_corpus
    from apiverity.specs.loader import detect_and_load
    from apiverity.traffic.redact import RedactionConfig, import_har

    root = Path(__file__).resolve().parents[2]
    service, _findings, _plugin = detect_and_load(str(root / "fixtures/apis/crud/openapi.yaml"))

    def load(name: str) -> Any:
        return import_har(
            str(root / "fixtures/traffic" / name),
            RedactionConfig(),
            include_response_bodies=True,
        )

    march, april = load("users-march.har"), load("users-april.har")

    # The premise: the contract is satisfied by the later corpus.
    assert analyze_corpus(service, april, forbid_undeclared_fields=True).findings == []

    report = compare_profiles(
        profile_corpus(service, march, source="march"),
        profile_corpus(service, april, source="april"),
    )
    fired = {f.rule_id for f in report.findings}
    assert "SEMANTIC-FIELD-ABANDONED" in fired
    assert "SEMANTIC-VALUE-GONE" in fired
