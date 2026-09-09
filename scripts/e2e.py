"""End-to-end validation against bundled fixtures (mock hosted in-process)."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from apiverity.cli.commands.common import EXIT_FINDINGS, EXIT_OK
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
        # 3.2 constructs go through the same commands as everything else.
        "openapi32/catalog.yaml",
    ]:
        code = run(["validate", str(FIX / "apis" / spec)])
        if code not in (0,):
            failures.append(f"validate {spec} -> {code}")

    # 1b. MCP manifests go through the same commands as every other format.
    #     Deliberately from fixtures/mcp/ rather than fixtures/apis/: the
    #     contract gate in .github/workflows/api-verity.yml selects changed
    #     specs with ^(fixtures/apis|openapi|specs|contracts)/ and runs
    #     `apiverity validate` on each, which would choke on the negative
    #     fixtures that exist precisely to be unrecognised.
    for manifest in ["tools_v1.json", "tools_v2.json"]:
        code = run(["validate", str(FIX / "mcp" / manifest)])
        if code != 0:
            failures.append(f"validate mcp/{manifest} -> {code}")
    code = run(["breaking", str(FIX / "mcp/tools_v1.json"), str(FIX / "mcp/tools_v2.json")])
    if code != EXIT_FINDINGS:
        failures.append(f"breaking mcp -> {code} (expected {EXIT_FINDINGS})")

    # 1c. A baseline written from one manifest must match itself and refuse
    #     the next version. Exit 1 here is the gate working, not a failure.
    with tempfile.TemporaryDirectory(prefix="apiverity-e2e-") as scratch:
        lock = str(Path(scratch) / "mcp.lock")
        for label, argv, expected in (
            ("write", ["mcp-lock", "write", str(FIX / "mcp/tools_v1.json"), "--lock", lock], 0),
            ("check", ["mcp-lock", "check", str(FIX / "mcp/tools_v1.json"), "--lock", lock], 0),
            (
                "check (moved)",
                ["mcp-lock", "check", str(FIX / "mcp/tools_v2.json"), "--lock", lock],
                EXIT_FINDINGS,
            ),
        ):
            code = run(argv)
            if code != expected:
                failures.append(f"mcp-lock {label} -> {code} (expected {expected})")

    # 1d. An evidence pack must verify against its own SHA256SUMS with the
    #     command that already exists for bundles. A pack whose checksums are
    #     decorative is the defect `apiverity verify` was written to fix.
    with tempfile.TemporaryDirectory(prefix="apiverity-e2e-") as scratch:
        record = Path(scratch) / "record.json"
        pack = Path(scratch) / "pack"
        import contextlib
        import io

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            cli_main(["validate", str(FIX / "apis/versioned/v1.yaml"), "--json"])
        record.write_text(buffer.getvalue(), encoding="utf-8")

        for label, argv, expected in (
            ("evidence", ["evidence", str(record), "-o", str(pack)], EXIT_OK),
            ("verify", ["verify", str(pack)], EXIT_OK),
        ):
            code = run(argv)
            if code != expected:
                failures.append(f"{label} -> {code} (expected {expected})")

    # 1e. A recorded corpus goes through the same command as a live probe and
    #     must produce the same finding shape.
    code = run(
        [
            "drift",
            str(FIX / "apis/crud/openapi.yaml"),
            "--corpus",
            str(FIX / "traffic/crud.har"),
        ]
    )
    if code != EXIT_FINDINGS:
        failures.append(f"drift --corpus -> {code} (expected {EXIT_FINDINGS})")

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
        # This step checks the command *wires up*: it loads a baseline, runs a
        # comparison and returns a code from the documented contract. It must
        # not check whether the numbers came out fast.
        #
        # It used to fail the build on any non-zero exit. EXIT_FINDINGS means
        # "a regression was detected", which is the command working correctly,
        # and on a contended CI runner a mock server on localhost genuinely
        # does go from 1.7ms to 16ms -- past even the 400% tolerance chosen to
        # be generous. That made a correctness gate depend on runner load, and
        # a gate that reddens for reasons nobody can act on is a gate someone
        # eventually deletes. The comparison logic itself is unit-tested.
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
        if code not in (EXIT_OK, EXIT_FINDINGS):
            failures.append(
                f"regression -> {code} (expected 0 or 1; anything else is a "
                "usage, unreachable or internal error)"
            )

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
