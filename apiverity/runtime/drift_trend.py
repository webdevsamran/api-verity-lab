"""Drift baselines, trends and field-frequency analysis.

Compares a current drift report against a stored baseline so newly introduced
undocumented behavior is distinguishable from legacy drift. Also computes
observed field frequencies over sanitized traffic corpora to highlight
optional/undocumented fields.

Why a baseline is the difference between a gate and a wish
-----------------------------------------------------------
Point `drift` at a service that has been running for three years and it
reports forty findings, all of them true and none of them today's problem. The
gate goes red on the first run, somebody sets it to advisory, and it never
comes back. A baseline records what was already wrong, so the gate can fail on
what is *newly* wrong -- which is the only thing a pull request can be held
responsible for.

Fingerprints are over the unified finding shape rather than over one mode's
model, so a baseline taken from a live probe and one taken from a recorded
corpus are the same kind of file. That is only possible because every drift
mode now writes the same shape.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from apiverity.runtime.drift import DriftFinding, DriftReport


@dataclass(frozen=True)
class TrendEntry:
    fingerprint: str  # operation_key + rule_id + message hash
    state: str  # new | known | resolved | legacy


def fingerprint(finding: Mapping[str, Any]) -> str:
    """A stable id for one finding, over the shape every mode writes.

    Operation, rule and message. Not severity: a finding whose grade was
    overridden is the same finding, and a baseline that forgot it because
    somebody changed a threshold would re-report it as new.
    """
    basis = "|".join(
        (
            str(finding.get("operation_key") or finding.get("tool") or ""),
            str(finding.get("rule_id") or ""),
            str(finding.get("message") or ""),
        )
    )
    import hashlib

    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


def classify(
    findings: list[dict[str, Any]], baseline: set[str]
) -> tuple[list[dict[str, Any]], list[str]]:
    """Mark each finding new or known, and name what the baseline lost.

    A finding in the baseline and absent now is drift that was fixed, and
    saying so is the half of the report that makes the other half credible.
    """
    marked: list[dict[str, Any]] = []
    seen: set[str] = set()
    for finding in findings:
        digest = fingerprint(finding)
        seen.add(digest)
        marked.append({**finding, "state": "known" if digest in baseline else "new"})
    return marked, sorted(baseline - seen)


def export(findings: list[dict[str, Any]], *, target: str) -> dict[str, Any]:
    """A baseline file for the findings a run produced."""
    return {
        "baseline_version": 1,
        "target": target,
        "fingerprints": sorted({fingerprint(f) for f in findings}),
        "finding_count": len(findings),
    }


def read_baseline(data: Mapping[str, Any]) -> set[str]:
    raw = data.get("fingerprints", [])
    if not isinstance(raw, (list, tuple, set)):
        return set()
    return {str(item) for item in raw}


def _fingerprint(f: DriftFinding) -> str:
    basis = f"{f.operation_key}|{f.rule_id}|{f.message}"
    import hashlib

    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


def compare_to_baseline(
    current: DriftReport,
    baseline_fingerprints: set[str],
) -> list[TrendEntry]:
    """Classify each current finding against the baseline fingerprints."""
    out: list[TrendEntry] = []
    for f in current.findings:
        fp = _fingerprint(f)
        out.append(TrendEntry(fp, "known" if fp in baseline_fingerprints else "new"))
    return out


def resolved_since_baseline(baseline_fingerprints: set[str], current: DriftReport) -> list[str]:
    """Baseline findings no longer present — drift that was fixed."""
    current_fps = {_fingerprint(f) for f in current.findings}
    return sorted(baseline_fingerprints - current_fps)


def export_baseline(report: DriftReport) -> dict[str, object]:
    """Serializable baseline for storage alongside contract versions."""
    return {
        "target": report.target,
        "fingerprints": sorted(_fingerprint(f) for f in report.findings),
        "finding_count": len(report.findings),
    }


def load_baseline(data: dict[str, object]) -> set[str]:
    raw = data.get("fingerprints", [])
    if not isinstance(raw, (list, tuple, set)):
        return set()
    return {str(item) for item in raw}


# --- Field frequency over traffic corpora ------------------------------------------


@dataclass
class FieldFrequency:
    path: str  # JSON-path-like location, e.g. "items[].status"
    count: int = 0
    total: int = 0

    @property
    def frequency(self) -> float:
        return self.count / self.total if self.total else 0.0


@dataclass
class FrequencyReport:
    total_records: int = 0
    fields: dict[str, FieldFrequency] = field(default_factory=dict)

    def frequent(self, min_frequency: float = 0.5) -> list[FieldFrequency]:
        return [
            f
            for f in self.fields.values()
            if f.total == self.total_records and f.frequency >= min_frequency
        ]


def _walk(value: object, prefix: str, counter: Counter[str], total: int) -> None:
    if isinstance(value, dict):
        for k, v in value.items():
            key = f"{prefix}.{k}" if prefix else k
            counter[key] += 1
            _walk(v, key, counter, total)
    elif isinstance(value, list):
        for item in value[:50]:  # bounded sampling per record
            _walk(item, f"{prefix}[]", counter, total)


def analyze_field_frequency(corpus_path: str) -> FrequencyReport:
    """Analyze a JSONL corpus of sanitized response bodies.

    Each line is either a JSON object (a response body) or
    ``{"body": ...}``. Never reads raw network captures here; inputs must
    already be redacted upstream.
    """
    report = FrequencyReport()
    counter: Counter[str] = Counter()
    with open(corpus_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            body = record.get("body", record) if isinstance(record, dict) else record
            report.total_records += 1
            _walk(body, "", counter, report.total_records)
    for key, count in counter.items():
        report.fields[key] = FieldFrequency(path=key, count=count, total=report.total_records)
    return report
