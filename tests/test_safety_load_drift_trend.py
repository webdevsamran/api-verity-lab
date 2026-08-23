"""Tests for replay safety gating, load profiles, capacity search and drift
baselines/trends."""

from __future__ import annotations

import json
from pathlib import Path

from apiverity.performance.profiles import (
    LoadProfile,
    capacity_search,
    execute,
    schedule,
)
from apiverity.runtime.drift import DriftFinding, DriftReport
from apiverity.runtime.drift_trend import (
    analyze_field_frequency,
    compare_to_baseline,
    export_baseline,
    load_baseline,
    resolved_since_baseline,
)
from apiverity.traffic.replay import ReplayEntry
from apiverity.traffic.safety import (
    build_dry_run_plan,
    check_replay_safety,
    classify_target,
    confirmation_token,
)

# --- Safety gate -------------------------------------------------------------------


class TestSafetyGate:
    def _entries(self, *methods: str) -> list[ReplayEntry]:
        return [ReplayEntry(method=m, path="/x") for m in methods]

    def test_allowlist_enforced(self) -> None:
        decision = check_replay_safety(
            base_url="http://localhost:9000",
            allowed_hosts=["http://other:1"],
            entries=self._entries("GET"),
        )
        assert not decision.approved

    def test_production_refused(self) -> None:
        decision = check_replay_safety(
            base_url="https://api.example.com",
            allowed_hosts=["https://api.example.com"],
            entries=self._entries("GET"),
        )
        assert not decision.approved
        assert "production" in decision.reason

    def test_local_get_approved(self) -> None:
        decision = check_replay_safety(
            base_url="http://localhost:9000",
            allowed_hosts=["http://localhost:9000"],
            entries=self._entries("GET"),
        )
        assert decision.approved

    def test_destructive_requires_allowlist_and_confirmation(self) -> None:
        entries = self._entries("POST", "DELETE")
        base = "http://localhost:9000"
        hosts = [base]
        # no allowlist at all
        d1 = check_replay_safety(base_url=base, allowed_hosts=hosts, entries=entries)
        assert not d1.approved
        # allowlist but wrong confirmation
        d2 = check_replay_safety(
            base_url=base,
            allowed_hosts=hosts,
            entries=entries,
            destructive_allowlist={"POST", "DELETE"},
            confirmation="wrong",
        )
        assert not d2.approved
        # correct token from dry-run plan
        token = confirmation_token(base, {"POST", "DELETE"}, len(entries))
        d3 = check_replay_safety(
            base_url=base,
            allowed_hosts=hosts,
            entries=entries,
            destructive_allowlist={"POST", "DELETE"},
            confirmation=token,
        )
        assert d3.approved

    def test_classification(self) -> None:
        assert classify_target("http://localhost:8080").classification == "local"
        assert classify_target("https://staging.example.org").classification == "staging"
        assert classify_target("https://api.example.com").classification == "production"

    def test_dry_run_plan_shows_urls(self) -> None:
        plan = build_dry_run_plan(
            [ReplayEntry(method="GET", path="/a"), ReplayEntry(method="POST", path="/b")],
            "http://localhost:9000",
        )
        assert [p.method for p in plan] == ["GET", "POST"]
        assert plan[0].url == "http://localhost:9000/a"


# --- Load profiles -------------------------------------------------------------------


class TestLoadProfiles:
    def test_constant_schedule_deterministic(self) -> None:
        p = LoadProfile(kind="constant", duration_seconds=2.0, rate_start=10)
        s1 = schedule(p)
        s2 = schedule(p)
        assert s1 == s2
        assert 15 <= len(s1) <= 25  # ~20 requests at 10 rps over 2s

    def test_ramp_increases_rate(self) -> None:
        p = LoadProfile(kind="ramp", duration_seconds=4.0, rate_start=5, rate_end=50)
        offsets = schedule(p)
        first_half = len([o for o in offsets if o < 2.0])
        second_half = len([o for o in offsets if o >= 2.0])
        assert second_half > first_half

    def test_spike_profile_bursts(self) -> None:
        flat = LoadProfile(kind="constant", duration_seconds=2.0, rate_start=10)
        spike = LoadProfile(
            kind="spike",
            duration_seconds=2.0,
            rate_start=10,
            spike_at=0.5,
            spike_multiplier=6,
            seed=3,
        )
        assert len(schedule(spike)) > len(schedule(flat)) * 1.2

    def test_poisson_differs_from_uniform(self) -> None:
        uniform = LoadProfile(kind="constant", duration_seconds=2.0, rate_start=20, seed=1)
        poisson = LoadProfile(
            kind="constant", duration_seconds=2.0, rate_start=20, poisson=True, seed=1
        )
        assert schedule(uniform) != schedule(poisson)

    def test_execute_collects_metrics(self) -> None:
        calls = {"n": 0}

        def transport(method: str, path: str):
            calls["n"] += 1
            return (200 if calls["n"] % 5 else 500), 12.5

        result = execute(LoadProfile(kind="constant", duration_seconds=1.0, rate_start=20), transport)
        assert result.sent == calls["n"]
        assert result.status_counts.get("2xx") and result.status_counts.get("5xx")
        assert result.p50 > 0

    def test_capacity_search_stops_at_saturation(self) -> None:
        def factory(conc: int):
            def transport(method: str, path: str):
                latency = 100.0 / conc + (200.0 if conc > 8 else 0.0)
                return 200, latency

            return transport

        points = capacity_search(factory, concurrency_levels=(1, 2, 4, 8, 16), requests_per_level=50)
        assert points[0].concurrency == 1
        assert all(p.throughput_rps > 0 for p in points)


# --- Drift trends ----------------------------------------------------------------------


class TestDriftTrend:
    def _report(self, msg: str = "drift") -> DriftReport:
        return DriftReport(
            target="http://localhost:9",
            findings=[DriftFinding(operation_key="GET /a", rule_id="DRIFT-SCHEMA", message=msg)],
        )

    def test_new_vs_known(self) -> None:
        baseline_report = self._report("old drift")
        baseline = load_baseline(export_baseline(baseline_report))
        current = DriftReport(
            target="http://localhost:9",
            findings=[
                DriftFinding(operation_key="GET /a", rule_id="DRIFT-SCHEMA", message="old drift"),
                DriftFinding(operation_key="GET /b", rule_id="DRIFT-STATUS", message="brand new"),
            ],
        )
        trend = compare_to_baseline(current, baseline)
        states = {e.state for e in trend}
        assert states == {"known", "new"}
        resolved = resolved_since_baseline(baseline, current)
        assert resolved == []

    def test_resolved_detection(self) -> None:
        baseline = load_baseline(export_baseline(self._report("fixed now")))
        current = self._report("different")
        resolved = resolved_since_baseline(baseline, current)
        assert len(resolved) == 1


class TestFieldFrequency:
    def test_frequency_analysis(self, tmp_path: Path) -> None:
        corpus = tmp_path / "corpus.jsonl"
        records = [
            {"body": {"id": 1, "status": "ok"}},
            {"body": {"id": 2, "status": "ok", "legacy_field": True}},
            {"body": {"id": 3}},
        ]
        corpus.write_text(chr(10).join(json.dumps(r) for r in records), encoding="utf-8")
        report = analyze_field_frequency(str(corpus))
        assert report.total_records == 3
        assert report.fields["id"].frequency == 1.0
        assert abs(report.fields["legacy_field"].frequency - 1 / 3) < 1e-9
        frequent = report.frequent(min_frequency=0.9)
        assert {f.path for f in frequent} == {"id"}
