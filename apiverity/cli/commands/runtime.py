"""Runtime lane commands: drift, replay, baseline, regression."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from apiverity.cli.commands.common import (
    EXIT_FINDINGS,
    EXIT_OK,
    EXIT_UNREACHABLE,
    EXIT_USAGE,
    _emit,
    _load,
    set_last_target,
)


def cmd_drift(args: argparse.Namespace) -> int:
    from apiverity.runtime.drift import detect_drift

    service, _, _ = _load(args.spec)
    set_last_target(args.base_url)
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
    set_last_target(args.base_url)
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
