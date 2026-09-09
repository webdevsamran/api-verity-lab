"""Count findings in emitted `result-v1` artifacts, by severity threshold.

Used by `action.yml` to decide whether the contract gate fails.

The gate cannot get this from exit codes. `apiverity breaking` returns
`EXIT_FINDINGS` when there is at least one ERROR finding and `EXIT_OK`
otherwise, so an exit-code tally can express neither "fail on warnings" nor
"how many findings were there" -- only "how many contracts had any errors".
An action input named `fail-on: warn` backed by that tally would be an input
that silently does nothing, which is worse than not offering it.

The artifacts already carry per-finding severity and conform to
`schemas/result-v1.schema.json`, so they are the honest source.

    python scripts/count_findings.py <artifacts-dir> <error|warn|never>

Prints `<at_or_above> <errors> <warns>` on one line.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

#: Ordered so a threshold can be compared numerically.
RANK = {"INFO": 0, "WARN": 1, "ERROR": 2}

#: `never` sits above every severity, so nothing ever reaches it.
FLOOR = {"error": RANK["ERROR"], "warn": RANK["WARN"], "never": max(RANK.values()) + 1}


def count(artifacts: Path, fail_on: str) -> tuple[int, int, int]:
    """Return (findings at or above `fail_on`, errors, warnings)."""
    if fail_on not in FLOOR:
        raise SystemExit(f"fail-on must be one of {sorted(FLOOR)}, got {fail_on!r}")
    floor = FLOOR[fail_on]
    at_or_above = errors = warns = 0
    for path in sorted(artifacts.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            # A malformed artifact is a tool failure, not an absence of
            # findings. Saying so beats reporting zero and passing the gate.
            raise SystemExit(f"{path}: unreadable result artifact ({exc})") from exc
        findings = payload.get("findings")
        if not isinstance(findings, list):
            continue
        for finding in findings:
            if not isinstance(finding, dict):
                continue
            severity = str(finding.get("severity", "INFO")).upper()
            errors += severity == "ERROR"
            warns += severity == "WARN"
            # An unrecognised severity ranks 0, so it never trips the gate on
            # its own -- inventing a rank for a word we do not know would be
            # asserting something the artifact did not establish.
            at_or_above += RANK.get(severity, 0) >= floor
    return at_or_above, errors, warns


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        raise SystemExit(f"usage: {argv[0]} <artifacts-dir> <error|warn|never>")
    at_or_above, errors, warns = count(Path(argv[1]), argv[2])
    print(f"{at_or_above} {errors} {warns}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
