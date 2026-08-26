"""Governance lane commands: validate, diff, breaking, changelog."""

from __future__ import annotations

import argparse
from pathlib import Path

from apiverity.cli.commands.common import (
    EXIT_FINDINGS,
    EXIT_OK,
    _emit,
    _load,
    _pair,
)


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
    # whole-contract HTTP compatibility + protocol-specific (GraphQL/gRPC) rules
    from apiverity.diff.compat import analyze_compat
    from apiverity.diff.protocol_compat import analyze_protocol_compat

    findings = findings + analyze_compat(old, new) + analyze_protocol_compat(old, new)
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
