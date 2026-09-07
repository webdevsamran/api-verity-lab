"""Drift against a recorded corpus (#21).

The distinction these exist to protect is between "this contract is wrong" and
"something hiccupped once". A corpus of a thousand entries against a service
missing one declared header produces a thousand identical findings; without
aggregation that is a wall of text, and the finding that occurred twice is
invisible in it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from apiverity.core.model import (
    Operation,
    Protocol,
    Response,
    SchemaNode,
    Server,
    Service,
)
from apiverity.runtime.corpus_drift import analyze_corpus, match_operation
from apiverity.traffic.redact import RedactionConfig, import_har


def _user_schema() -> SchemaNode:
    return SchemaNode(
        type="object",
        required=["id", "role"],
        properties={
            "id": SchemaNode(type="string"),
            "role": SchemaNode(type="string"),
        },
    )


def _service(**overrides: Any) -> Service:
    ops = overrides.pop(
        "operations",
        [
            Operation(
                method="GET",
                path="/users/{id}",
                responses=[
                    Response(
                        status="200",
                        content={"application/json": _user_schema()},
                        headers={"X-Request-Id": SchemaNode(type="string")},
                    )
                ],
            )
        ],
    )
    return Service(
        title="T",
        version="1.0.0",
        protocol=Protocol.OPENAPI,
        servers=[Server(url="https://api.example.com")],
        operations=ops,
        **overrides,
    )


def _entry(
    path: str,
    *,
    method: str = "GET",
    status: int = 200,
    body: Any = None,
    mime: str = "application/json",
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "method": method,
        "url": f"https://api.example.com{path}",
        "status": status,
        "response_mime": mime,
        "response_headers": headers if headers is not None else {"X-Request-Id": "r"},
        "response_body": body,
        "response_body_dropped": None if body is not None else "no body recorded",
    }


# ------------------------------------------------------------- route matching


def test_a_concrete_path_matches_its_template() -> None:
    service = _service()
    assert match_operation(service, "GET", "/users/42") is not None
    assert match_operation(service, "GET", "/users") is None
    assert match_operation(service, "POST", "/users/42") is None


def test_a_literal_path_wins_over_a_template() -> None:
    """`/users/me` and `/users/{id}` both match `/users/me`.

    Picking the template would report every drift finding against the wrong
    operation, which is worse than not matching at all: the report looks
    right.
    """
    literal = Operation(method="GET", path="/users/me", responses=[Response(status="200")])
    template = Operation(method="GET", path="/users/{id}", responses=[Response(status="200")])
    service = _service(operations=[template, literal])
    matched = match_operation(service, "GET", "/users/me")
    assert matched is not None and matched.path == "/users/me"


def test_matching_is_case_insensitive_on_the_method_only() -> None:
    service = _service()
    assert match_operation(service, "get", "/users/42") is not None
    assert match_operation(service, "GET", "/USERS/42") is None


# --------------------------------------------------------------- aggregation


def test_identical_findings_collapse_into_one_with_a_count() -> None:
    entries = [_entry(f"/users/{i}", body={"id": str(i)}) for i in range(50)]
    report = analyze_corpus(_service(), entries)
    missing = [f for f in report.findings if f.rule_id == "DRIFT-MISSING-FIELD"]
    assert len(missing) == 1, "50 identical findings should be one finding, not 50"
    assert missing[0].occurrences == 50
    assert missing[0].observations == 50
    assert missing[0].frequency == 1.0


def test_examples_are_capped_rather_than_reproducing_the_corpus() -> None:
    entries = [_entry(f"/users/{i}", body={"id": str(i)}) for i in range(50)]
    finding = analyze_corpus(_service(), entries).findings[0]
    assert 0 < len(finding.examples) <= 3


def test_systematic_and_one_off_are_distinguished() -> None:
    """The whole point of counting."""
    good = [_entry(f"/users/{i}", body={"id": str(i), "role": "a"}) for i in range(98)]
    bad = [_entry(f"/users/{i}", body={"id": str(i)}) for i in (98, 99)]
    missing_header = [
        _entry(f"/users/{i}", body={"id": str(i), "role": "a"}, headers={}) for i in range(100, 200)
    ]
    report = analyze_corpus(_service(), good + bad + missing_header)

    rare = next(f for f in report.findings if f.rule_id == "DRIFT-MISSING-FIELD")
    assert rare.occurrences == 2
    assert rare.one_off, f"2 in {rare.observations} should read as a one-off"
    assert not rare.systematic

    header = next(f for f in report.findings if f.rule_id == "DRIFT-HEADER")
    assert header.occurrences == 100
    assert not header.systematic, "100 of 200 is neither systematic nor a one-off"

    only_missing = analyze_corpus(_service(), missing_header)
    always = next(f for f in only_missing.findings if f.rule_id == "DRIFT-HEADER")
    assert always.systematic and always.frequency == 1.0


def test_findings_are_ordered_by_how_often_they_happened() -> None:
    entries = [_entry(f"/users/{i}", body={"id": str(i)}, headers={}) for i in range(10)]
    entries += [_entry("/users/x", status=418, body={"id": "x", "role": "a"})]
    findings = analyze_corpus(_service(), entries).findings
    assert [f.occurrences for f in findings] == sorted(
        [f.occurrences for f in findings], reverse=True
    )


# ------------------------------------------------------- content negotiation


def test_the_schema_matches_the_media_type_actually_returned() -> None:
    """Two media types, two different schemas, and the returned one decides.

    Picking whichever schema `content` yielded first meant a response that was
    entirely correct for the type it declared got reported as a violation of a
    schema for a type it never claimed to be. The two schemas here are
    deliberately incompatible, so choosing the wrong one cannot pass.
    """
    op = Operation(
        method="GET",
        path="/report",
        responses=[
            Response(
                status="200",
                content={
                    "application/json": SchemaNode(
                        type="object",
                        required=["rows"],
                        properties={"rows": SchemaNode(type="array")},
                    ),
                    "application/vnd.summary+json": SchemaNode(
                        type="object",
                        required=["total"],
                        properties={"total": SchemaNode(type="integer")},
                    ),
                },
            )
        ],
    )
    service = _service(operations=[op])

    summary = _entry("/report", body={"total": 7}, mime="application/vnd.summary+json", headers={})
    assert analyze_corpus(service, [summary]).findings == [], (
        "a valid vnd.summary+json body was checked against the wrong schema"
    )

    rows = _entry("/report", body={"rows": []}, mime="application/json", headers={})
    assert analyze_corpus(service, [rows]).findings == []

    # And the negative: the right schema really is being applied.
    wrong = _entry("/report", body={"rows": []}, mime="application/vnd.summary+json", headers={})
    assert any(
        f.rule_id == "DRIFT-MISSING-FIELD" for f in analyze_corpus(service, [wrong]).findings
    )


def test_a_body_the_importer_could_not_parse_is_not_a_schema_violation() -> None:
    """A CSV response arrives with `response_body=None`, not as a bad object."""
    op = Operation(
        method="GET",
        path="/report",
        responses=[
            Response(
                status="200",
                content={
                    "application/json": _user_schema(),
                    "text/csv": SchemaNode(type="string"),
                },
            )
        ],
    )
    csv = _entry("/report", body=None, mime="text/csv", headers={})
    report = analyze_corpus(_service(operations=[op]), [csv])
    assert not [f for f in report.findings if f.rule_id == "DRIFT-SCHEMA"]
    assert not [f for f in report.findings if f.rule_id == "DRIFT-CONTENT-TYPE"]
    assert report.quality.bodies_unavailable == 1


def test_a_vendor_json_type_falls_back_to_the_json_schema() -> None:
    entry = _entry("/users/1", body={"id": "1"}, mime="application/vnd.api+json")
    report = analyze_corpus(_service(), [entry])
    assert any(f.rule_id == "DRIFT-MISSING-FIELD" for f in report.findings), (
        "a +json type must still be validated, not silently skipped"
    )


def test_a_charset_parameter_does_not_defeat_the_match() -> None:
    entry = _entry("/users/1", body={"id": "1"}, mime="application/json; charset=utf-8")
    report = analyze_corpus(_service(), [entry])
    assert not [f for f in report.findings if f.rule_id == "DRIFT-CONTENT-TYPE"]


def test_an_undeclared_media_type_is_reported() -> None:
    entry = _entry("/users/1", body=None, mime="application/xml")
    report = analyze_corpus(_service(), [entry])
    assert any(f.rule_id == "DRIFT-CONTENT-TYPE" for f in report.findings)


# ---------------------------------------------------------------- status codes


def test_a_wildcard_declaration_covers_its_range() -> None:
    """`4XX` is legal OpenAPI; matching only exact strings reported every 404."""
    op = Operation(
        method="GET",
        path="/users/{id}",
        responses=[Response(status="200"), Response(status="4XX")],
    )
    report = analyze_corpus(_service(operations=[op]), [_entry("/users/1", status=404)])
    assert not [f for f in report.findings if f.rule_id == "DRIFT-STATUS"]


def test_an_undeclared_status_is_still_reported() -> None:
    op = Operation(method="GET", path="/users/{id}", responses=[Response(status="200")])
    report = analyze_corpus(_service(operations=[op]), [_entry("/users/1", status=503)])
    assert any(f.rule_id == "DRIFT-STATUS" for f in report.findings)


# ------------------------------------------------------------ corpus quality


def test_quality_reports_what_the_corpus_could_not_answer() -> None:
    """ "3 findings" from 5000 entries means something very different when
    4900 of them were skipped, and a reader who is not told cannot tell."""
    entries = [_entry("/users/1", body={"id": "1", "role": "a"})]
    entries += [_entry("/nowhere", body={})] * 4
    entries += [{"method": "", "url": "", "status": None}] * 2
    quality = analyze_corpus(_service(), entries).quality

    assert quality.entries == 7
    assert quality.analysed == 1
    assert quality.skipped_unmatched == 4
    assert quality.skipped_malformed == 2
    assert quality.unmatched_paths == ["GET /nowhere"]
    assert 0.14 < quality.coverage < 0.15


def test_quality_says_when_bodies_were_not_available() -> None:
    """Redaction is the default, so a clean schema result usually means
    "nothing was checked" rather than "nothing was wrong"."""
    entries = [_entry(f"/users/{i}", body=None) for i in range(5)]
    quality = analyze_corpus(_service(), entries).quality
    assert quality.bodies_unavailable == 5
    assert sum(quality.body_drop_reasons.values()) == 5


def test_quality_names_operations_the_corpus_never_touched() -> None:
    op = Operation(method="DELETE", path="/users/{id}", responses=[Response(status="204")])
    service = _service(
        operations=[
            *_service().operations,
            op,
        ]
    )
    quality = analyze_corpus(service, [_entry("/users/1", body={"id": "1", "role": "a"})]).quality
    assert quality.uncovered_operations == ["DELETE /users/{id}"]


def test_an_empty_corpus_is_not_a_clean_bill_of_health() -> None:
    report = analyze_corpus(_service(), [])
    assert report.findings == []
    assert report.quality.entries == 0
    assert report.quality.coverage == 0.0
    assert report.quality.uncovered_operations, "every operation is uncovered"


# ------------------------------------------------------------------ HAR import


def _har(entries: list[dict[str, Any]]) -> dict[str, Any]:
    return {"log": {"version": "1.2", "entries": entries}}


def _har_entry(mime: str, text: str, *, post: dict[str, Any] | None = None) -> dict[str, Any]:
    request: dict[str, Any] = {
        "method": "GET",
        "url": "https://api.example.com/users/1",
        "queryString": [],
        "headers": [],
    }
    if post:
        request["postData"] = post
    return {
        "request": request,
        "response": {"status": 200, "headers": [], "content": {"mimeType": mime, "text": text}},
    }


def test_a_non_json_body_does_not_take_down_the_import(tmp_path: Path) -> None:
    """`json.loads` on every postData raised, losing the whole corpus to one
    HTML error page or form submission."""
    har = tmp_path / "c.har"
    har.write_text(
        json.dumps(
            _har(
                [
                    _har_entry(
                        "text/html",
                        "<html>oops</html>",
                        post={"mimeType": "text/html", "text": "<html>form</html>"},
                    ),
                    _har_entry("application/json", '{"id":"1"}'),
                ]
            )
        ),
        encoding="utf-8",
    )
    entries = import_har(str(har), RedactionConfig(), include_response_bodies=True)
    assert len(entries) == 2
    assert entries[0]["request_body"] is None
    assert "not JSON" in str(entries[0]["request_body_dropped"])
    assert entries[1]["response_body"] == {"id": "1"}


def test_truncated_json_is_reported_as_a_reason_not_an_exception(tmp_path: Path) -> None:
    har = tmp_path / "c.har"
    har.write_text(
        json.dumps(_har([_har_entry("application/json", '{"id": "1"')])), encoding="utf-8"
    )
    entries = import_har(str(har), RedactionConfig(), include_response_bodies=True)
    assert entries[0]["response_body"] is None
    assert "not parseable" in str(entries[0]["response_body_dropped"])


def test_response_bodies_stay_out_unless_asked_for(tmp_path: Path) -> None:
    """A HAR of a real service holds real user data, and corpora get committed."""
    har = tmp_path / "c.har"
    har.write_text(
        json.dumps(_har([_har_entry("application/json", '{"id":"1"}')])), encoding="utf-8"
    )
    default = import_har(str(har), RedactionConfig())
    assert default[0]["response_body"] is None
    assert default[0]["response_body_dropped"] == "response bodies not imported"

    opted_in = import_har(str(har), RedactionConfig(), include_response_bodies=True)
    assert opted_in[0]["response_body"] == {"id": "1"}


def test_redaction_still_applies_to_imported_bodies(tmp_path: Path) -> None:
    har = tmp_path / "c.har"
    har.write_text(
        json.dumps(
            _har([_har_entry("application/json", '{"id":"1","token":"sk-abcdef1234567890"}')])
        ),
        encoding="utf-8",
    )
    entries = import_har(str(har), RedactionConfig(), include_response_bodies=True)
    assert entries[0]["response_body"]["token"] == "[REDACTED]"


# ------------------------------------------------------------------------ CLI


def test_drift_refuses_both_a_corpus_and_a_live_target(tmp_path: Path) -> None:
    import argparse

    from apiverity.cli.commands.runtime import cmd_drift

    spec = tmp_path / "s.yaml"
    spec.write_text(
        'openapi: "3.0.3"\ninfo: {title: T, version: "1.0.0"}\npaths: {}\n', encoding="utf-8"
    )
    args = argparse.Namespace(
        spec=str(spec), base_url="http://x", corpus="c.har", timeout=1.0, json=False
    )
    assert cmd_drift(args) == 2


def test_drift_requires_one_of_them(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    import argparse

    from apiverity.cli.commands.runtime import cmd_drift

    spec = tmp_path / "s.yaml"
    spec.write_text(
        'openapi: "3.0.3"\ninfo: {title: T, version: "1.0.0"}\npaths: {}\n', encoding="utf-8"
    )
    args = argparse.Namespace(spec=str(spec), base_url=None, corpus=None, timeout=1.0, json=False)
    assert cmd_drift(args) == 2
    assert "--base-url or --corpus" in capsys.readouterr().err


def test_drift_reports_an_unreadable_corpus_clearly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import argparse

    from apiverity.cli.commands.runtime import cmd_drift

    spec = tmp_path / "s.yaml"
    spec.write_text(
        'openapi: "3.0.3"\ninfo: {title: T, version: "1.0.0"}\npaths: {}\n', encoding="utf-8"
    )
    args = argparse.Namespace(
        spec=str(spec),
        base_url=None,
        corpus=str(tmp_path / "missing.har"),
        include_response_bodies=False,
        allow_undeclared_fields=False,
        timeout=1.0,
        json=False,
    )
    assert cmd_drift(args) == 2
    assert "could not read corpus" in capsys.readouterr().err
