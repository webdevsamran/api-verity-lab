"""When drift started, not just how often it happened.

`import_har` dropped `startedDateTime` before any analyser saw it, so every
corpus report was an unordered bag of requests. It could say a declared header
was missing from four hundred responses and not whether that began last
Tuesday -- and "the contract has always been wrong" and "something changed on
Tuesday" have different owners and different fixes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from apiverity.core.model import (
    Operation,
    OperationKind,
    Protocol,
    Response,
    SchemaNode,
    Service,
)
from apiverity.runtime.corpus_drift import analyze_corpus
from apiverity.traffic.redact import import_har


def _service() -> Service:
    return Service(
        title="t",
        version="1",
        protocol=Protocol.OPENAPI,
        operations=[
            Operation(
                kind=OperationKind.HTTP,
                method="GET",
                path="/users",
                operation_id="list",
                responses=[
                    Response(
                        status="200",
                        content={"application/json": SchemaNode(type="object")},
                        headers={"x-request-id": SchemaNode(type="string")},
                    )
                ],
            )
        ],
    )


def _entry(at: str | None, status: int = 200) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "method": "GET",
        "url": "https://api.example.com/users",
        "status": status,
        "response_mime": "application/json",
        "response_body": {},
        "response_headers": {},
    }
    if at is not None:
        entry["started_at"] = at
    return entry


def _har(tmp_path: Path, *stamps: str) -> str:
    log = {
        "log": {
            "entries": [
                {
                    "startedDateTime": stamp,
                    "time": 12.5,
                    "request": {
                        "method": "GET",
                        "url": "https://api.example.com/users",
                        "headers": [],
                        "queryString": [],
                    },
                    "response": {"status": 200, "headers": [], "content": {}},
                }
                for stamp in stamps
            ]
        }
    }
    path = tmp_path / "traffic.har"
    path.write_text(json.dumps(log), encoding="utf-8")
    return str(path)


# ------------------------------------------------------------------- import


def test_the_har_timestamp_survives_import(tmp_path: Path) -> None:
    (entry,) = import_har(_har(tmp_path, "2026-03-01T09:15:00.000Z"))
    assert entry["started_at"] == "2026-03-01T09:15:00.000Z"
    assert entry["elapsed_ms"] == 12.5


def test_the_timestamp_is_carried_verbatim_not_reparsed(tmp_path: Path) -> None:
    """A HAR writes an instant with an offset the recorder chose; keep it."""
    (entry,) = import_har(_har(tmp_path, "2026-03-01T09:15:00.000+02:00"))
    assert entry["started_at"] == "2026-03-01T09:15:00.000+02:00"


# --------------------------------------------------------------- aggregation


def test_a_finding_carries_the_span_it_was_seen_over() -> None:
    entries = [_entry("2026-03-01T00:00:00Z"), _entry("2026-03-04T00:00:00Z")]
    report = analyze_corpus(_service(), entries)
    header = next(f for f in report.findings if f.rule_id == "DRIFT-HEADER")
    assert header.first_seen == "2026-03-01T00:00:00Z"
    assert header.last_seen == "2026-03-04T00:00:00Z"
    assert header.occurrences == 2


def test_entries_out_of_order_still_produce_the_right_span() -> None:
    """A HAR is not guaranteed sorted, and min/max does not care."""
    entries = [_entry("2026-03-09T00:00:00Z"), _entry("2026-03-02T00:00:00Z")]
    header = next(
        f for f in analyze_corpus(_service(), entries).findings if f.rule_id == "DRIFT-HEADER"
    )
    assert (header.first_seen, header.last_seen) == (
        "2026-03-02T00:00:00Z",
        "2026-03-09T00:00:00Z",
    )


def test_a_corpus_without_timestamps_reports_none_rather_than_a_guess() -> None:
    report = analyze_corpus(_service(), [_entry(None), _entry(None)])
    header = next(f for f in report.findings if f.rule_id == "DRIFT-HEADER")
    assert header.first_seen is None and header.last_seen is None
    assert report.quality.timestamped_entries == 0


def test_the_report_records_the_span_of_the_whole_corpus() -> None:
    entries = [_entry("2026-03-01T00:00:00Z"), _entry("2026-03-05T00:00:00Z"), _entry(None)]
    quality = analyze_corpus(_service(), entries).quality
    assert quality.first_seen == "2026-03-01T00:00:00Z"
    assert quality.last_seen == "2026-03-05T00:00:00Z"
    assert quality.timestamped_entries == 2


def test_a_partially_timestamped_corpus_says_how_many_carried_one() -> None:
    """Otherwise a span computed from two of five hundred entries looks total."""
    entries = [_entry("2026-03-01T00:00:00Z")] + [_entry(None) for _ in range(4)]
    quality = analyze_corpus(_service(), entries).quality
    assert quality.timestamped_entries == 1
    assert quality.entries == 5


def test_two_different_findings_keep_their_own_spans() -> None:
    entries = [
        _entry("2026-03-01T00:00:00Z", status=200),
        _entry("2026-03-08T00:00:00Z", status=418),
    ]
    by_rule = {f.rule_id: f for f in analyze_corpus(_service(), entries).findings}
    assert by_rule["DRIFT-HEADER"].first_seen == "2026-03-01T00:00:00Z"
    assert by_rule["DRIFT-STATUS"].first_seen == "2026-03-08T00:00:00Z"
