"""Testing lane commands: test, workflow, mock, coverage."""

from __future__ import annotations

import argparse
import sys

from apiverity.cli.commands.common import (
    EXIT_FINDINGS,
    EXIT_OK,
    EXIT_UNREACHABLE,
    EXIT_USAGE,
    _emit,
    _load,
    set_last_seed,
    set_last_target,
)


def cmd_test(args: argparse.Namespace) -> int:
    from apiverity.fuzz.generators import BUILTIN_GENERATORS, load_generators
    from apiverity.fuzz.minimize import minimize_failures
    from apiverity.fuzz.runner import build_cases, run_cases

    if getattr(args, "list_generators", False):
        available = load_generators()
        for name in sorted(available):
            origin = "built-in" if name in BUILTIN_GENERATORS else "plugin"
            doc = (type(available[name]).__doc__ or "").strip().splitlines()
            print(f"{name:16} {origin:9} {doc[0] if doc else ''}")
        print(f"{'schema':16} {'built-in':9} Valid and invalid values derived from the schema.")
        return EXIT_OK

    if not args.base_url:
        print("error: --base-url is required", file=sys.stderr)
        return EXIT_USAGE

    selected = list(getattr(args, "generator", None) or [])
    if "all" in selected:
        selected = sorted(load_generators())

    service, _, _ = _load(args.spec)
    set_last_target(args.base_url)
    set_last_seed(args.seed)
    try:
        cases = build_cases(service, seed=args.seed, generators=selected or None)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
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
