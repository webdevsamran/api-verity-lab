"""Drift baselines, trends and field-frequency analysis.

Compares a current drift report against a stored baseline so newly introduced
undocumented behavior is distinguishable from legacy drift. Also computes
observed field frequencies over sanitized traffic corpora to highlight
optional/undocumented fields.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field

from apiverity.runtime.drift import DriftFinding, DriftReport


@dataclass(frozen=True)
class TrendEntry:
    fingerprint: str  # operation_key + rule_id + message hash
    state: str  # new | known | resolved | legacy


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
