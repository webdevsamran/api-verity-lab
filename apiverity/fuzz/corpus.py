"""Deterministic case-corpus export/import for CI regression replay.

A corpus is JSONL: one JSON object per line with a stable ``case_id`` so a
previously failing generated case can be replayed byte-identically in CI.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from apiverity.fuzz.models import TestCase


def case_id(case: TestCase) -> str:
    """Stable ID from operation key, case kind and canonical parameters."""
    basis = {
        "op": case.operation_key,
        "kind": case.kind,
        "params": case.query,
        "body": case.body,
    }
    payload = json.dumps(basis, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def export_corpus(cases: list[TestCase], path: str | Path) -> int:
    """Write cases as JSONL; returns the number of records written."""
    out = Path(path)
    count = 0
    with out.open("w", encoding="utf-8") as fh:
        for c in cases:
            record = {"case_id": case_id(c), **c.model_dump(mode="json")}
            fh.write(json.dumps(record, sort_keys=True, default=str) + chr(10))
            count += 1
    return count


def import_corpus(path: str | Path) -> list[TestCase]:
    """Read a JSONL corpus back into TestCase objects (order preserved)."""
    cases: list[TestCase] = []
    with Path(path).open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            record.pop("case_id", None)
            cases.append(TestCase(**record))
    return cases


def verify_corpus_roundtrip(cases: list[TestCase], path: str | Path) -> bool:
    """Export then import and confirm identical case IDs (determinism proof)."""
    export_corpus(cases, path)
    restored = import_corpus(path)
    return [case_id(c) for c in cases] == [case_id(c) for c in restored]
