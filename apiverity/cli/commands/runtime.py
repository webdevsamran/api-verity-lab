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
    NL,
    _emit,
    _load,
    set_last_target,
)
from apiverity.core.model import Service


def cmd_drift(args: argparse.Namespace) -> int:
    from apiverity.runtime.drift import detect_drift

    service, _, _ = _load(args.spec)
    corpus = getattr(args, "corpus", None)
    if corpus and args.base_url:
        print("error: pass either --base-url or --corpus, not both", file=sys.stderr)
        return EXIT_USAGE
    if not corpus and not args.base_url:
        print("error: drift needs either --base-url or --corpus", file=sys.stderr)
        return EXIT_USAGE

    forbid = not getattr(args, "allow_undeclared_fields", False)
    if corpus:
        return _drift_corpus(args, service, corpus, forbid_undeclared_fields=forbid)

    if service.protocol.value == "graphql":
        # Introspection is the only way to ask a GraphQL endpoint what it
        # actually serves; probing one operation at a time cannot see a field
        # the schema never declared.
        return _drift_graphql(args)

    set_last_target(args.base_url)
    try:
        report = detect_drift(
            service,
            args.base_url,
            timeout=args.timeout,
            forbid_undeclared_fields=forbid,
        )
    except Exception as exc:
        print(f"error: target unreachable: {exc}", file=sys.stderr)
        return EXIT_UNREACHABLE
    _emit({"tool": "apiverity", "command": "drift", "report": report}, args.json)
    return EXIT_FINDINGS if report.findings else EXIT_OK


def _drift_corpus(
    args: argparse.Namespace,
    service: Service,
    corpus: str,
    *,
    forbid_undeclared_fields: bool,
) -> int:
    from apiverity.runtime.corpus_drift import analyze_corpus
    from apiverity.traffic.redact import RedactionConfig, import_har

    try:
        entries = import_har(
            corpus,
            RedactionConfig(),
            include_response_bodies=getattr(args, "include_response_bodies", False),
        )
    except (OSError, ValueError) as exc:
        print(f"error: could not read corpus '{corpus}': {exc}", file=sys.stderr)
        return EXIT_USAGE

    report = analyze_corpus(
        service,
        entries,
        source=corpus,
        forbid_undeclared_fields=forbid_undeclared_fields,
    )
    if args.json:
        _emit({"tool": "apiverity", "command": "drift", "report": report}, True)
        return EXIT_FINDINGS if report.findings else EXIT_OK

    quality = report.quality
    print(f"corpus: {corpus}")
    print(
        f"  {quality.analysed}/{quality.entries} entries analysed ({quality.coverage * 100:.0f}%)"
    )
    if quality.skipped_unmatched:
        print(f"  {quality.skipped_unmatched} skipped: no matching operation")
        for label in quality.unmatched_paths[:5]:
            print(f"    - {label}")
    if quality.skipped_malformed:
        print(f"  {quality.skipped_malformed} skipped: malformed entry")
    if quality.bodies_unavailable:
        print(f"  {quality.bodies_unavailable} matched entries had no usable body")
        for reason, count in sorted(quality.body_drop_reasons.items(), key=lambda kv: -kv[1]):
            print(f"    - {count}x {reason}")
    if quality.uncovered_operations:
        # Said out loud, because a clean report over a corpus that never
        # touched half the API reads exactly like a correct one.
        print(f"  {len(quality.uncovered_operations)} operations never exercised")

    if not report.findings:
        print("no drift found")
        return EXIT_OK

    print(f"{NL}findings ({len(report.findings)} distinct):")
    for finding in report.findings:
        kind = "systematic" if finding.systematic else ("one-off" if finding.one_off else "")
        share = f"{finding.occurrences}/{finding.observations}"
        suffix = f" [{kind}]" if kind else ""
        print(
            f"  [{finding.severity}] {finding.rule_id} {finding.operation_key}: "
            f"{finding.message} ({share}, {finding.frequency * 100:.0f}%){suffix}"
        )
    return EXIT_FINDINGS


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
        # Warmup matters here as much as in the comparison run: a cold
        # baseline compared against a warm one measures the connection pool,
        # not the service.
        report = measure(
            service,
            args.base_url,
            iterations=args.iterations,
            warmup=getattr(args, "warmup", 0) or 0,
        )
    except Exception as exc:
        print(f"error: target unreachable: {exc}", file=sys.stderr)
        return EXIT_UNREACHABLE
    if report.nothing_answered():
        print(f"error: target unreachable: nothing answered at {args.base_url}", file=sys.stderr)
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
    from apiverity.performance.engine import (
        compare_baseline,
        evaluate_policies,
        measure,
        parse_tolerance,
    )

    service, _, _ = _load(args.spec)
    try:
        tolerances = parse_tolerance(getattr(args, "tolerance", None) or None)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    try:
        report = measure(
            service,
            args.base_url,
            iterations=args.iterations,
            warmup=getattr(args, "warmup", 0) or 0,
        )
    except Exception as exc:
        print(f"error: target unreachable: {exc}", file=sys.stderr)
        return EXIT_UNREACHABLE
    if report.nothing_answered():
        print(f"error: target unreachable: nothing answered at {args.base_url}", file=sys.stderr)
        return EXIT_UNREACHABLE
    violations = evaluate_policies(report, args.policy or [])
    inconclusive: list[str] = []
    if args.baseline:
        baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
        comparison = compare_baseline(report, baseline, tolerance_pct=tolerances)
        violations += comparison.regressions
        inconclusive = comparison.inconclusive
    report.policy_violations = violations
    report.inconclusive = inconclusive
    _emit(
        {
            "tool": "apiverity",
            "command": "regression",
            "violations": violations,
            # Printed, but not fatal: "the run was too short to tell" is not a
            # regression, and failing a build on it is how a gate gets turned
            # off. The count is what tells you to raise --iterations.
            "inconclusive": inconclusive,
            "report": report,
        },
        args.json,
    )
    return EXIT_FINDINGS if violations else EXIT_OK


def _drift_graphql(args: argparse.Namespace) -> int:
    """Compare a committed SDL against a live endpoint's introspection."""
    from pathlib import Path

    from apiverity.specs.graphql.runner import run_drift

    try:
        from graphql import build_schema
    except ImportError:  # pragma: no cover - depends on the install
        print(
            "error: GraphQL support requires the 'graphql' extra: "
            "pip install api-verity-lab[graphql]",
            file=sys.stderr,
        )
        return EXIT_USAGE

    schema = build_schema(Path(args.spec).read_text(encoding="utf-8-sig"))
    set_last_target(args.base_url)
    try:
        findings = run_drift(schema, args.base_url, timeout=args.timeout)
    except ValueError as exc:
        # Introspection being disabled is a fact about the endpoint, not a
        # clean drift report. Saying so beats reporting every declared type as
        # missing.
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_UNREACHABLE
    except Exception as exc:
        print(f"error: target unreachable: {exc}", file=sys.stderr)
        return EXIT_UNREACHABLE

    _emit(
        {
            "tool": "apiverity",
            "command": "drift",
            "protocol": "graphql",
            "target": args.base_url,
            "findings": findings,
        },
        args.json,
    )
    return EXIT_FINDINGS if findings else EXIT_OK
