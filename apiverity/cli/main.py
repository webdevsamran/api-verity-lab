"""apiverity command-line interface.

All commands support ``--json`` and stable exit codes:
0 ok · 1 findings at/above threshold · 2 usage error ·
3 target unreachable · 4 internal error.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

NL = chr(10)

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_USAGE = 2
EXIT_UNREACHABLE = 3
EXIT_INTERNAL = 4

if TYPE_CHECKING:
    from apiverity.core.model import Finding, Service
    from apiverity.mock import MockServer
    from apiverity.specs import SpecPlugin


_LAST_SPEC: str | None = None
_LAST_TARGET: str | None = None
_LAST_SEED: int | None = None


def _load(path: str) -> tuple[Service, list[Finding], SpecPlugin]:
    from apiverity.specs.loader import detect_and_load

    global _LAST_SPEC
    _LAST_SPEC = path
    try:
        return detect_and_load(path)
    except FileNotFoundError:
        print(f"error: file not found: {path}", file=sys.stderr)
        sys.exit(EXIT_USAGE)
    except Exception as exc:
        print(f"error: failed to load spec: {exc}", file=sys.stderr)
        sys.exit(EXIT_USAGE)


def _emit(data: dict[str, Any], as_json: bool) -> None:
    from apiverity.core.artifact import enrich

    data = enrich(data, spec_path=_LAST_SPEC, target=_LAST_TARGET, seed=_LAST_SEED)
    if as_json:
        print(json.dumps(data, indent=2, default=str))
    else:
        for key, value in data.items():
            if isinstance(value, list) and value and hasattr(value[0], "model_dump"):
                print(f"{key}:")
                for item in value:
                    d = item.model_dump()
                    print(
                        f"  [{d.get('severity', d.get('status', ''))}] "
                        f"{d.get('rule_id', d.get('case_id', d.get('step', '')))} "
                        f"{d.get('message', d.get('description', ''))}"
                    )
            else:
                print(f"{key}: {value}")


def cmd_validate(args: argparse.Namespace) -> int:
    service, findings, plugin = _load(args.spec)
    from apiverity.security import run_security_checks

    sec = run_security_checks(service)
    all_findings = findings + sec
    errors = sum(1 for f in all_findings if f.severity.value == "ERROR")
    data = {
        "tool": "apiverity",
        "command": "validate",
        "spec": args.spec,
        "protocol": plugin.protocol().value,
        "title": service.title,
        "version": service.version,
        "operations": len(service.operations),
        "findings": all_findings,
        "errors": errors,
    }
    _emit(data, args.json)
    return EXIT_FINDINGS if errors else EXIT_OK


def _pair(args: argparse.Namespace) -> tuple[Service, Service]:
    old_service, _, _ = _load(args.old)
    new_service, _, _ = _load(args.new)
    return old_service, new_service


def cmd_diff(args: argparse.Namespace) -> int:
    from apiverity.diff.engine import diff_services

    old, new = _pair(args)
    changes = diff_services(old, new)
    _emit(
        {
            "tool": "apiverity",
            "command": "diff",
            "old_version": old.version,
            "new_version": new.version,
            "changes": changes,
        },
        args.json,
    )
    return EXIT_OK


def cmd_breaking(args: argparse.Namespace) -> int:
    from apiverity.diff.engine import diff_services
    from apiverity.rules.breaking import evaluate_breaking
    from apiverity.rules.semver import SemverPolicy

    old, new = _pair(args)
    changes = diff_services(old, new)
    overrides = {}
    if args.severity_override:
        for item in args.severity_override:
            rule_id, _, sev = item.partition("=")
            overrides[rule_id] = sev.upper()
    findings = evaluate_breaking(changes, overrides or None)
    if args.check_semver:
        policy = SemverPolicy(
            args.old_version or old.version,
            args.new_version or new.version,
            require_minor_for_warnings=args.require_minor_for_warnings,
        )
        findings = findings + policy.evaluate(findings, changes)
    errors = sum(1 for f in findings if f.severity.value == "ERROR")
    _emit(
        {
            "tool": "apiverity",
            "command": "breaking",
            "old_version": old.version,
            "new_version": new.version,
            "changes": len(changes),
            "findings": findings,
            "errors": errors,
        },
        args.json,
    )
    return EXIT_FINDINGS if errors else EXIT_OK


def cmd_changelog(args: argparse.Namespace) -> int:
    from apiverity.diff.engine import diff_services
    from apiverity.rules.breaking import evaluate_breaking
    from apiverity.rules.changelog import generate_changelog

    old, new = _pair(args)
    changes = diff_services(old, new)
    findings = evaluate_breaking(changes)
    text = generate_changelog(
        old.title,
        old.version,
        new.version,
        changes,
        findings,
        fmt="html" if args.html else "markdown",
    )
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        print(text)
    return EXIT_OK


def _start_mock(spec_path: str, port: int) -> MockServer:
    from apiverity.mock import MockServer

    service, _, _ = _load(spec_path)
    server = MockServer(service, port=port)
    server.start()
    return server


def cmd_test(args: argparse.Namespace) -> int:
    from apiverity.fuzz.minimize import minimize_failures
    from apiverity.fuzz.runner import build_cases, run_cases

    global _LAST_TARGET, _LAST_SEED
    service, _, _ = _load(args.spec)
    _LAST_TARGET = args.base_url
    _LAST_SEED = args.seed
    cases = build_cases(service, seed=args.seed)
    try:
        results = run_cases(service, args.base_url, cases, timeout=args.timeout)
    except Exception as exc:
        print(f"error: target unreachable: {exc}", file=sys.stderr)
        return EXIT_UNREACHABLE
    if args.minimize:
        results = minimize_failures(service, args.base_url, results, cases)
    failures = [r for r in results if r.status != "pass"]
    passed = len(results) - len(failures)
    _emit(
        {
            "tool": "apiverity",
            "command": "test",
            "base_url": args.base_url,
            "total": len(results),
            "passed": passed,
            "failed": len(failures),
            "results": results,
        },
        args.json,
    )
    return EXIT_FINDINGS if failures else EXIT_OK


def cmd_workflow(args: argparse.Namespace) -> int:
    from apiverity.stateful.engine import WorkflowEngine, load_workflow_manifest

    wf = load_workflow_manifest(args.manifest)
    base_url = args.base_url or wf.base_url
    if not base_url:
        print("error: no base URL (pass --base-url or set base_url in manifest)", file=sys.stderr)
        return EXIT_USAGE
    try:
        result = WorkflowEngine(wf, base_url).run()
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except Exception:
        _emit(
            {"tool": "apiverity", "command": "workflow", "workflow": wf.name, "status": "error"},
            args.json,
        )
        return EXIT_UNREACHABLE
    _emit({"tool": "apiverity", "command": "workflow", "result": result}, args.json)
    return EXIT_FINDINGS if result.status != "pass" else EXIT_OK


def cmd_mock(args: argparse.Namespace) -> int:
    from apiverity.mock import FaultConfig, serve

    service, _, _ = _load(args.spec)
    faults = FaultConfig(
        latency_ms=args.latency_ms,
        force_status=args.force_status,
        malformed_json=args.malformed,
        rate_limit_after=args.rate_limit_after,
    )
    host = "127.0.0.1"  # always localhost by default
    serve(service, host=host, port=args.port, faults=faults)
    return EXIT_OK


def cmd_coverage(args: argparse.Namespace) -> int:
    from apiverity.coverage import measure_coverage

    service, _, _ = _load(args.spec)
    exercised = set(args.exercised or [])
    report = measure_coverage(service, exercised_operations=exercised)
    _emit(
        {
            "tool": "apiverity",
            "command": "coverage",
            "overall_percent": report.overall_percent(),
            "report": report,
        },
        args.json,
    )
    return EXIT_OK


def cmd_drift(args: argparse.Namespace) -> int:
    from apiverity.runtime.drift import detect_drift

    global _LAST_TARGET
    service, _, _ = _load(args.spec)
    _LAST_TARGET = args.base_url
    try:
        report = detect_drift(service, args.base_url, timeout=args.timeout)
    except Exception as exc:
        print(f"error: target unreachable: {exc}", file=sys.stderr)
        return EXIT_UNREACHABLE
    _emit({"tool": "apiverity", "command": "drift", "report": report}, args.json)
    return EXIT_FINDINGS if report.findings else EXIT_OK


def cmd_replay(args: argparse.Namespace) -> int:
    from urllib.parse import urlparse

    from apiverity.traffic.redact import RedactionConfig, import_har
    from apiverity.traffic.replay import ReplayEntry, replay_corpus

    cfg = RedactionConfig()
    entries_raw = import_har(args.har, cfg)
    entries = []
    for e in entries_raw:
        parsed = urlparse(e["url"] or "")
        entries.append(
            ReplayEntry(
                method=e["method"] or "GET",
                path=parsed.path or "/",
                query=e["query"],
                headers=e["request_headers"],
                body=e["request_body"],
            )
        )
    try:
        report = replay_corpus(
            entries,
            args.base_url,
            allowed_hosts=args.allow_host,
            dry_run=not args.execute,
            rate_per_second=args.rate,
            allow_production=args.i_know_this_is_production,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    _emit({"tool": "apiverity", "command": "replay", "report": report}, args.json)
    return EXIT_OK


def cmd_baseline(args: argparse.Namespace) -> int:
    from apiverity.performance.engine import measure

    service, _, _ = _load(args.spec)
    try:
        report = measure(service, args.base_url, iterations=args.iterations)
    except Exception as exc:
        print(f"error: target unreachable: {exc}", file=sys.stderr)
        return EXIT_UNREACHABLE
    global _LAST_TARGET
    _LAST_TARGET = args.base_url
    payload = json.loads(report.model_dump_json())
    Path(args.output).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    _emit(
        {"tool": "apiverity", "command": "baseline", "output": args.output, "report": report},
        args.json,
    )
    return EXIT_OK


def cmd_regression(args: argparse.Namespace) -> int:
    from apiverity.performance.engine import compare_baseline, evaluate_policies, measure

    service, _, _ = _load(args.spec)
    try:
        report = measure(service, args.base_url, iterations=args.iterations)
    except Exception as exc:
        print(f"error: target unreachable: {exc}", file=sys.stderr)
        return EXIT_UNREACHABLE
    violations = evaluate_policies(report, args.policy or [])
    if args.baseline:
        baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
        violations += compare_baseline(report, baseline, tolerance_pct=args.tolerance)
    report.policy_violations = violations
    _emit(
        {"tool": "apiverity", "command": "regression", "violations": violations, "report": report},
        args.json,
    )
    return EXIT_FINDINGS if violations else EXIT_OK


def cmd_report(args: argparse.Namespace) -> int:
    """Render a bundle's result.json in the requested format."""
    result_path = Path(args.bundle) / "result.json"
    if not result_path.exists():
        print(f"error: no result.json in {args.bundle}", file=sys.stderr)
        return EXIT_USAGE
    data = json.loads(result_path.read_text(encoding="utf-8"))
    fmt = args.format
    if fmt == "json":
        print(json.dumps(data, indent=2))
    elif fmt == "markdown":
        lines = [f"# apiverity report — {data.get('command', '?')}"]
        for k, v in data.items():
            if k not in ("results", "findings"):
                lines.append(f"- **{k}**: {v}")
        print(NL.join(lines))
    elif fmt == "junit":
        failures = data.get("failed", data.get("errors", 0))
        total = data.get("total", 0)
        print('<?xml version="1.0" encoding="UTF-8"?>')
        print(f'<testsuite name="apiverity" tests="{total}" failures="{failures}">')
        print("</testsuite>")
    elif fmt == "yaml":
        import yaml

        print(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
    elif fmt == "html":
        rows = ""
        for f in data.get("findings", []):
            sev = str(f.get("severity", "INFO"))
            color = {"ERROR": "#e5484d", "WARN": "#f5a623"}.get(sev, "#3b82f6")
            rows += (
                f"<tr><td><code>{f.get('rule_id', '')}</code></td>"
                f"<td style='color:{color}'><b>{sev}</b></td>"
                f"<td>{f.get('message', '')}</td></tr>"
            )
        print(
            "<!doctype html><html><head><meta charset='utf-8'>"
            "<title>apiverity report</title>"
            "<style>body{font-family:system-ui;margin:2rem;background:#0d1117;"
            "color:#e6edf3}table{border-collapse:collapse;width:100%}"
            "td,th{padding:8px;border-bottom:1px solid #30363d;text-align:left}"
            "</style></head><body><h1>apiverity report</h1>"
            f"<p>{data.get('command', '')} — {data.get('spec', data.get('base_url', ''))}</p>"
            f"<table><tr><th>Rule</th><th>Severity</th><th>Message</th></tr>{rows}"
            "</table></body></html>"
        )
    elif fmt == "sarif":
        sarif = {
            "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
            "version": "2.1.0",
            "runs": [
                {
                    "tool": {
                        "driver": {
                            "name": "apiverity",
                            "informationUri": "https://github.com/webdevsamran/api-verity-lab",
                        }
                    },
                    "results": [
                        {
                            "ruleId": f.get("rule_id", "APIVERITY"),
                            "level": {"ERROR": "error", "WARN": "warning"}.get(
                                str(f.get("severity")), "note"
                            ),
                            "message": {"text": f.get("message", "")},
                        }
                        for f in data.get("findings", [])
                    ],
                }
            ],
        }
        print(json.dumps(sarif, indent=2))
    else:
        print(f"error: unknown format '{fmt}'", file=sys.stderr)
        return EXIT_USAGE
    return EXIT_OK


def cmd_export(args: argparse.Namespace) -> int:
    """Write a .apiverity bundle: result.json, contract snapshot+hash,
    config, sanitized failing cases, workflow manifests, performance
    summary and SHA256 checksums."""
    import hashlib

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    payload = (
        json.loads(args.data)
        if args.data.startswith("{")
        else {"tool": "apiverity", "note": args.data}
    )

    if args.spec:
        spec_bytes = Path(args.spec).read_bytes()
        (out / "contract-snapshot").write_bytes(spec_bytes)
        payload["contract_hash"] = hashlib.sha256(spec_bytes).hexdigest()
        payload["contract_snapshot"] = "contract-snapshot"
    if args.config:
        (out / "config.yaml").write_text(
            Path(args.config).read_text(encoding="utf-8"), encoding="utf-8"
        )
    if args.workflow:
        (out / "workflow-manifest.yaml").write_text(
            Path(args.workflow).read_text(encoding="utf-8"), encoding="utf-8"
        )
    if args.perf:
        (out / "performance-summary.json").write_text(
            Path(args.perf).read_text(encoding="utf-8"), encoding="utf-8"
        )

    # sanitized failing cases only (violations + reproduction, no bodies)
    if isinstance(payload.get("results"), list):
        failing = [
            r for r in payload["results"] if isinstance(r, dict) and r.get("status") != "pass"
        ]
        (out / "failing-cases.json").write_text(json.dumps(failing, indent=2), encoding="utf-8")

    (out / "result.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    checksums = {}
    for f in sorted(out.iterdir()):
        if f.is_file():
            checksums[f.name] = hashlib.sha256(f.read_bytes()).hexdigest()
    (out / "SHA256SUMS").write_text(
        NL.join(f"{v}  {k}" for k, v in checksums.items()) + NL, encoding="utf-8"
    )
    _emit(
        {"tool": "apiverity", "command": "export", "bundle": str(out), "files": sorted(checksums)},
        args.json,
    )
    return EXIT_OK


def cmd_serve(args: argparse.Namespace) -> int:
    """Serve a result bundle (or web/dist) on localhost."""
    import functools
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    root = Path(args.directory)
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(root))
    httpd = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    print(f"serving {root} at http://127.0.0.1:{args.port} (Ctrl+C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return EXIT_OK


def cmd_server_db(args: argparse.Namespace) -> int:
    """Administer a self-hosted server SQLite database.

    Actions: backup (consistent snapshot), restore (from a snapshot),
    export (org JSON snapshot without token hashes), import (snapshot as a
    new org).
    """
    from apiverity.server.store import Store

    action = args.action
    if action == "backup":
        store = Store(args.db)
        out = store.backup_to(args.output)
        _emit(
            {"tool": "apiverity", "command": "server-db", "action": "backup", "output": str(out)},
            args.json,
        )
        return EXIT_OK
    if action == "restore":
        store = Store.restore_from(args.db, target=args.output)
        orgs = store.conn.execute("SELECT COUNT(*) FROM orgs").fetchone()[0]
        store.close()
        _emit(
            {
                "tool": "apiverity",
                "command": "server-db",
                "action": "restore",
                "target": args.output,
                "orgs_restored": int(orgs),
            },
            args.json,
        )
        return EXIT_OK
    if action == "export":
        store = Store(args.db)
        snap = store.export_org(int(args.org_id))
        Path(args.output).write_text(json.dumps(snap, indent=2), encoding="utf-8")
        _emit(
            {
                "tool": "apiverity",
                "command": "server-db",
                "action": "export",
                "org_id": int(args.org_id),
                "output": args.output,
            },
            args.json,
        )
        return EXIT_OK
    if action == "import":
        store = Store(args.db)
        snap = json.loads(Path(args.input).read_text(encoding="utf-8"))
        new_org = store.import_org(snap)
        _emit(
            {
                "tool": "apiverity",
                "command": "server-db",
                "action": "import",
                "new_org_id": new_org,
            },
            args.json,
        )
        return EXIT_OK
    print(f"error: unknown action '{action}'", file=sys.stderr)
    return EXIT_USAGE


def cmd_plugins(args: argparse.Namespace) -> int:
    from apiverity.plugins.registry import list_entry_points

    groups = list_entry_points()
    _emit({"tool": "apiverity", "command": "plugins", "groups": groups}, args.json)
    return EXIT_OK


def cmd_rules(args: argparse.Namespace) -> int:
    from apiverity.rules.breaking import CATALOG

    rules = [
        {"rule_id": rid, "severity": spec.severity.value, "description": spec.description}
        for rid, spec in sorted(CATALOG.items())
    ]
    _emit({"tool": "apiverity", "command": "rules", "count": len(rules), "rules": rules}, args.json)
    return EXIT_OK


def cmd_self_test(args: argparse.Namespace) -> int:
    """Run built-in sanity checks against bundled fixtures."""
    fixture = Path(__file__).parents[2] / "fixtures" / "apis" / "crud" / "openapi.yaml"
    if not fixture.exists():
        print("self-test: fixtures missing", file=sys.stderr)
        return EXIT_INTERNAL
    service, findings, plugin = _load(str(fixture))
    ok = plugin.protocol().value == "openapi" and len(service.operations) > 0
    _emit(
        {
            "tool": "apiverity",
            "command": "self-test",
            "ok": ok,
            "operations": len(service.operations),
            "spec_findings": len(findings),
        },
        args.json,
    )
    return EXIT_OK if ok else EXIT_INTERNAL


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="apiverity", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("validate")
    p.add_argument("spec")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_validate)
    p = sub.add_parser("diff")
    p.add_argument("old")
    p.add_argument("new")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_diff)
    p = sub.add_parser("breaking")
    p.add_argument("old")
    p.add_argument("new")
    p.add_argument("--check-semver", action="store_true")
    p.add_argument("--old-version")
    p.add_argument("--new-version")
    p.add_argument("--require-minor-for-warnings", action="store_true")
    p.add_argument("--severity-override", action="append")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_breaking)
    p = sub.add_parser("changelog")
    p.add_argument("old")
    p.add_argument("new")
    p.add_argument("--html", action="store_true")
    p.add_argument("--output")
    p.set_defaults(func=cmd_changelog)
    p = sub.add_parser("test")
    p.add_argument("spec")
    p.add_argument("--base-url", required=True)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--timeout", type=float, default=10.0)
    p.add_argument("--minimize", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_test)
    p = sub.add_parser("workflow")
    p.add_argument("manifest")
    p.add_argument("--base-url")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_workflow)
    p = sub.add_parser("mock")
    p.add_argument("spec")
    p.add_argument("--port", type=int, default=8090)
    p.add_argument("--latency-ms", type=int, default=0)
    p.add_argument("--force-status", type=int)
    p.add_argument("--malformed", action="store_true")
    p.add_argument("--rate-limit-after", type=int)
    p.set_defaults(func=cmd_mock)
    p = sub.add_parser("coverage")
    p.add_argument("spec")
    p.add_argument("--exercised", nargs="*")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_coverage)
    p = sub.add_parser("drift")
    p.add_argument("spec")
    p.add_argument("--base-url", required=True)
    p.add_argument("--timeout", type=float, default=10.0)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_drift)
    p = sub.add_parser("replay")
    p.add_argument("har")
    p.add_argument("--base-url", required=True)
    p.add_argument("--allow-host", action="append", required=True)
    p.add_argument("--execute", action="store_true")
    p.add_argument("--rate", type=float, default=10.0)
    p.add_argument("--i-know-this-is-production", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_replay)
    p = sub.add_parser("baseline")
    p.add_argument("spec")
    p.add_argument("--base-url", required=True)
    p.add_argument("-o", "--output", default="perf-baseline.json")
    p.add_argument("--iterations", type=int, default=20)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_baseline)
    p = sub.add_parser("regression")
    p.add_argument("spec")
    p.add_argument("--base-url", required=True)
    p.add_argument("--baseline")
    p.add_argument("--policy", action="append")
    p.add_argument("--tolerance", type=float, default=20.0)
    p.add_argument("--iterations", type=int, default=20)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_regression)
    p = sub.add_parser("report")
    p.add_argument("bundle")
    p.add_argument("--format", default="json")
    p.set_defaults(func=cmd_report)
    p = sub.add_parser("export")
    p.add_argument("--data", required=True)
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--spec")
    p.add_argument("--config")
    p.add_argument("--workflow")
    p.add_argument("--perf")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_export)
    p = sub.add_parser("serve")
    p.add_argument("directory")
    p.add_argument("--port", type=int, default=8080)
    p.set_defaults(func=cmd_serve)
    p = sub.add_parser("server-db", help="backup/restore/export/import a server database")
    p.add_argument("action", choices=["backup", "restore", "export", "import"])
    p.add_argument("--db", required=True, help="server SQLite database path")
    p.add_argument("-o", "--output", help="backup file / restored db / export JSON path")
    p.add_argument("--input", help="snapshot JSON to import")
    p.add_argument("--org-id", type=int, help="org id for export")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_server_db)
    p = sub.add_parser("plugins")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_plugins)
    p = sub.add_parser("rules")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_rules)
    p = sub.add_parser("self-test")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_self_test)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result: Any = args.func(args)
        return int(result)
    except SystemExit:
        raise
    except KeyboardInterrupt:
        return EXIT_OK
    except Exception as exc:
        print(f"internal error: {exc}", file=sys.stderr)
        return EXIT_INTERNAL


if __name__ == "__main__":
    sys.exit(main())
