"""End-to-end validation against bundled fixtures (mock hosted in-process)."""

from __future__ import annotations

import sys
from pathlib import Path

from apiverity.cli.main import main as cli_main
from apiverity.mock import MockServer
from apiverity.specs.loader import detect_and_load

ROOT = Path(__file__).parents[1]
FIX = ROOT / "fixtures"


def run(argv: list[str]) -> int:
    print("$ apiverity " + " ".join(argv))
    return cli_main(argv)


def main() -> None:
    failures = []

    # 1. validate all fixtures
    for spec in [
        "crud/openapi.yaml",
        "versioned/v1.yaml",
        "versioned/v2.yaml",
        "drift/openapi.yaml",
    ]:
        code = run(["validate", str(FIX / "apis" / spec)])
        if code not in (0,):
            failures.append(f"validate {spec} -> {code}")

    # 2. diff + breaking + semver
    code = run(["diff", str(FIX / "apis/versioned/v1.yaml"), str(FIX / "apis/versioned/v2.yaml")])
    if code != 0:
        failures.append(f"diff -> {code}")
    code = run(
        [
            "breaking",
            str(FIX / "apis/versioned/v1.yaml"),
            str(FIX / "apis/versioned/v2.yaml"),
            "--check-semver",
        ]
    )
    if code != 1:  # breaking changes expected
        failures.append(f"breaking -> {code} (expected 1)")

    # 3. changelog
    out = Path("build/changelog.md")
    out.parent.mkdir(exist_ok=True)
    code = run(
        [
            "changelog",
            str(FIX / "apis/versioned/v1.yaml"),
            str(FIX / "apis/versioned/v2.yaml"),
            "--output",
            str(out),
        ]
    )
    if code != 0 or not out.exists():
        failures.append("changelog failed")

    # 4. mock-hosted runtime checks
    service, _, _ = detect_and_load(str(FIX / "apis/crud/openapi.yaml"))
    with MockServer(service, port=8091) as mock:
        base = mock.base_url

        # test engine finds intentional issues? mock is contract-faithful,
        # so most cases pass; negative cases must be rejected with 4xx.
        code = run(["test", str(FIX / "apis/crud/openapi.yaml"), "--base-url", base])
        if code not in (0, 1):
            failures.append(f"test -> {code}")

        # workflow lifecycle
        code = run(["workflow", str(FIX / "workflows/crud-lifecycle.yaml"), "--base-url", base])
        if code != 0:
            failures.append(f"workflow -> {code}")

        # drift against the *drift* fixture served by the CRUD mock
        # (intentional mismatches must be found)
        drift_service, _, _ = detect_and_load(str(FIX / "apis/drift/openapi.yaml"))
        from apiverity.runtime.drift import detect_drift

        report = detect_drift(drift_service, base)
        rules = {f.rule_id for f in report.findings}
        if "DRIFT-STATUS" not in rules:
            failures.append(f"drift did not detect undeclared status: {rules}")

        # performance baseline + regression gate
        baseline_path = Path("build/perf-baseline.json")
        code = run(
            [
                "baseline",
                str(FIX / "apis/crud/openapi.yaml"),
                "--base-url",
                base,
                "-o",
                str(baseline_path),
                "--iterations",
                "30",
            ]
        )
        if code != 0:
            failures.append(f"baseline -> {code}")
        # Tolerance is deliberately generous: localhost timings are noisy and
        # the strict comparison logic is unit-tested in the pytest suite.
        # Here we verify the command wiring and exit codes end-to-end.
        code = run(
            [
                "regression",
                str(FIX / "apis/crud/openapi.yaml"),
                "--base-url",
                base,
                "--baseline",
                str(baseline_path),
                "--iterations",
                "30",
                "--tolerance",
                "400",
                "--policy",
                "GET /users p95 <= 5000ms",
            ]
        )
        if code != 0:
            failures.append(f"regression -> {code}")

    # 5. redaction sanity
    from apiverity.traffic.redact import RedactionConfig, redact_headers, redact_json

    cfg = RedactionConfig()
    hdrs = redact_headers(
        {"Authorization": "Bearer sk-abcdefghijklmnop1234", "X-Custom": "ok"}, cfg
    )
    assert hdrs["Authorization"] == "[REDACTED]", hdrs
    body = redact_json({"password": "hunter2", "note": "token=abc123"}, cfg)
    assert body["password"] == "[REDACTED]" and "[REDACTED]" in body["note"], body
    print("redaction OK")

    print()
    if failures:
        print("E2E FAILURES:")
        for f in failures:
            print(" -", f)
        sys.exit(1)
    print("E2E PASSED")


if __name__ == "__main__":
    main()
