"""Generate real frontend demo data by running bundled fixtures through apiverity."""
from __future__ import annotations

import json
from pathlib import Path

from apiverity.cli.main import main as cli_main
from apiverity.mock import MockServer
from apiverity.specs.loader import detect_and_load

ROOT = Path(__file__).parents[1]
FIX = ROOT / "fixtures"
OUT = ROOT / "web" / "public" / "demo-data.json"


def cli_json(argv):
    import io
    import contextlib

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = cli_main(argv)
    assert code in (0, 1), f"{argv} -> {code}"  # 1 = findings present (expected)
    return json.loads(buf.getvalue())


def main() -> None:
    from apiverity.diff.engine import diff_services
    from apiverity.rules.breaking import evaluate_breaking

    v1, v2 = FIX / "apis/versioned/v1.yaml", FIX / "apis/versioned/v2.yaml"
    old, _, _ = detect_and_load(str(v1))
    new, _, _ = detect_and_load(str(v2))
    changes = diff_services(old, new)
    findings = evaluate_breaking(changes)

    crud = FIX / "apis/crud/openapi.yaml"
    service, _, _ = detect_and_load(str(crud))
    drift_service, _, _ = detect_and_load(str(FIX / "apis/drift/openapi.yaml"))

    from apiverity.fuzz.runner import build_cases, run_cases
    from apiverity.runtime.drift import detect_drift
    from apiverity.coverage import measure_coverage

    with MockServer(service, port=8095) as mock:
        base = mock.base_url
        cases = build_cases(service, seed=42)
        results = run_cases(service, base, cases)
        drift = detect_drift(drift_service, base)

    from apiverity.performance.engine import measure

    perf = measure(service, base, iterations=15)

    exercised = {r.operation_key for r in results}
    statuses: dict[str, set[int]] = {}
    for r in results:
        if r.actual_status:
            statuses.setdefault(r.operation_key, set()).add(r.actual_status)
    coverage = measure_coverage(service, exercised_operations=exercised,
                                statuses_by_operation=statuses)

    payload = {
        "meta": {
            "tool": "apiverity",
            "generated_from": "fixtures/apis (crud, versioned v1->v2, drift)",
            "label": "EXAMPLE RUN — generated locally from bundled fixture APIs",
        },
        "diff": {"old_version": old.version, "new_version": new.version,
                 "changes": [c.model_dump() for c in changes]},
        "breaking": {"findings": [f.model_dump() for f in findings]},
        "test": {"total": len(results),
                 "passed": sum(1 for r in results if r.status == "pass"),
                 "failed": sum(1 for r in results if r.status != "pass"),
                 "results": [r.model_dump() for r in results]},
        "drift": {"findings": [f.model_dump() for f in drift.findings]},
        "performance": {"operations": json.loads(perf.model_dump_json())["operations"]},
        "coverage": {"overall_percent": coverage.overall_percent(),
                     "operations": json.loads(coverage.model_dump_json())["operations"]},
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()