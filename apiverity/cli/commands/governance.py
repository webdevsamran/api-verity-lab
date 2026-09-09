"""Governance lane commands: validate, diff, breaking, changelog."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from apiverity.cli.commands.common import (
    EXIT_FINDINGS,
    EXIT_OK,
    EXIT_USAGE,
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
        # `operations` in a result-v1 artifact is the array of per-operation
        # stats that performance/engine.py reads back from a baseline
        # (`{o["operation_key"]: o for o in baseline["operations"]}`). Emitting
        # an integer under the same key meant a `validate` artifact and a
        # `baseline` artifact disagreed about the type of the same field, and
        # handing the former to the performance engine would raise rather than
        # report. The count is still useful, under a name that says so.
        "operation_count": len(service.operations),
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

    # Who breaks, not just what. Annotation only, unless the registry declares
    # itself complete *and* the caller asks: "no consumer listed" and "no
    # consumer exists" are different statements, and softening a finding on the
    # first is how a breaking change ships.
    radius = None
    affected_names: list[str] = []
    if getattr(args, "consumers", None):
        from apiverity.rules.consumers import (
            RegistryError,
            annotate,
            blast_radius,
            load_registry,
            validate_against,
        )

        try:
            registry = load_registry(args.consumers)
        except RegistryError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return EXIT_USAGE

        # Both sides. A consumer using an operation the new version removed is
        # the case this exists to report, not a typo in the registry.
        known = {op.key for op in old.operations} | {op.key for op in new.operations}
        findings = findings + validate_against(registry, known)
        findings = annotate(
            findings,
            registry,
            adjust_severity=bool(getattr(args, "severity_by_consumers", False)),
        )
        radius = blast_radius(findings, registry)
        affected_names = sorted(radius["by_consumer"])

    if args.check_semver:
        policy = SemverPolicy(
            args.old_version or old.version,
            args.new_version or new.version,
            require_minor_for_warnings=args.require_minor_for_warnings,
        )
        findings = findings + policy.evaluate(findings, changes)
    errors = sum(1 for f in findings if f.severity.value == "ERROR")

    # Advice first: the summary quotes the concrete version when both flags are
    # given, and "release this as 2.0.0" is a more useful sentence than
    # "release this behind a major version bump".
    advice = None
    if getattr(args, "suggest_version", False):
        from apiverity.rules.semver import suggest_bump

        advice = suggest_bump(
            args.old_version or old.version,
            findings,
            changes,
            require_minor_for_warnings=args.require_minor_for_warnings,
            declared_new_version=args.new_version or new.version,
        ).as_dict()

    summary = None
    if getattr(args, "summary", False):
        from apiverity.rules.summary import summarize

        summary = summarize(
            changes,
            findings,
            old_version=args.old_version or old.version,
            new_version=args.new_version or new.version,
            suggested_version=(
                str(advice["suggested_version"])
                if advice and isinstance(advice.get("suggested_version"), str)
                else None
            ),
            consumers=affected_names or None,
        )

    _emit(
        {
            "tool": "apiverity",
            "command": "breaking",
            # Which two documents, not just which two versions. `contract_hash`
            # covers the last one loaded, so an artifact from a comparison
            # could not say what it was compared against -- and a reader of an
            # evidence bundle six months later has no other way to find out.
            "old_spec": args.old,
            "new_spec": args.new,
            "old_version": old.version,
            "new_version": new.version,
            # `diff` emits `changes` as the array of changes; this emitted the
            # same key as an integer count, so a consumer reading `changes`
            # got a list or a number depending on which command produced the
            # artifact -- and schemas/result-v1 declares it an array, which
            # made every `breaking` artifact silently non-conformant. Renamed
            # rather than converted: the count is genuinely useful here, and
            # `breaking` reports findings, not the changes themselves.
            "change_count": len(changes),
            "findings": findings,
            "errors": errors,
            **({"blast_radius": radius} if radius is not None else {}),
            **({"version_advice": advice} if advice is not None else {}),
            **(
                {"summary": {**summary.as_dict(), "markdown": summary.as_markdown()}}
                if summary is not None
                else {}
            ),
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

    if getattr(args, "json", False):
        # The rendered document goes *inside* the artifact rather than to
        # stdout beside it: a caller asking for JSON is parsing stdout, and a
        # markdown changelog printed alongside would corrupt the parse.
        _emit(
            {
                "tool": "apiverity",
                "command": "changelog",
                "old_version": old.version,
                "new_version": new.version,
                "format": "html" if args.html else "markdown",
                "change_count": len(changes),
                "output_path": args.output or None,
                "document": text,
            },
            True,
        )
    elif not args.output:
        print(text)
    return EXIT_OK


def cmd_infer(args: argparse.Namespace) -> int:
    """Draft a contract from recorded traffic, labelled as a draft."""
    import json

    import yaml

    from apiverity.specs.infer import infer
    from apiverity.traffic.redact import RedactionConfig, import_har

    try:
        entries = import_har(args.corpus, RedactionConfig(), include_response_bodies=True)
    except (OSError, ValueError) as exc:
        print(f"error: could not read corpus '{args.corpus}': {exc}", file=sys.stderr)
        return EXIT_USAGE

    if not entries:
        # Nothing observed is not an empty API. An inferred document with no
        # paths would be read as "this service has none".
        print(
            f"error: {args.corpus} contains no usable entries; there is nothing to infer from",
            file=sys.stderr,
        )
        return EXIT_USAGE

    document, provenance = infer(
        entries,
        title=getattr(args, "title", None) or "Inferred API",
        infer_enums=bool(getattr(args, "infer_enums", False)),
    )

    output = getattr(args, "output", None)
    if output:
        text = (
            json.dumps(document, indent=2) + "\n"
            if str(output).endswith(".json")
            else yaml.safe_dump(document, sort_keys=False, allow_unicode=True)
        )
        Path(output).write_text(text, encoding="utf-8")

    _emit(
        {
            "tool": "apiverity",
            "command": "infer",
            "corpus": args.corpus,
            "output": str(output) if output else None,
            "provenance": provenance,
            # Emitted whether or not it was written, so a run with no -o is
            # still useful in a pipeline.
            "document": document if not output else None,
        },
        getattr(args, "json", False),
    )
    if not getattr(args, "json", False):
        print()
        print(
            f"Drafted {provenance['operations']} operation(s) from "
            f"{provenance['requests_usable']} request(s). This describes what was observed, "
            "not what the API supports -- read it before publishing it."
        )
    return EXIT_OK


def cmd_sweep(args: argparse.Namespace) -> int:
    """Every contract in a tree, with an owner and a verdict for each.

    A monorepo has one contract gate per service and no view across them. This
    walks the tree once and answers the two questions a platform team actually
    has: which contracts are failing, and whose they are.
    """
    from apiverity.cli.commands.project import discover_contracts_deep
    from apiverity.core.ownership import load_ownership
    from apiverity.specs.loader import detect_and_load

    root = Path(getattr(args, "root", ".")).resolve()
    if not root.is_dir():
        print(f"error: not a directory: {root}", file=sys.stderr)
        return EXIT_USAGE

    relative_paths = discover_contracts_deep(root, limit=int(getattr(args, "limit", 500)))
    if not relative_paths:
        # Not a pass. Zero contracts found and zero contracts broken look
        # identical in a summary line, and only one of them is good news.
        print(
            f"error: no contracts found under {root}; nothing was swept, which is not the "
            "same as nothing being wrong",
            file=sys.stderr,
        )
        return EXIT_USAGE

    ownership = load_ownership(root)
    base = Path(args.base).resolve() if getattr(args, "base", None) else None

    contracts: list[dict[str, Any]] = []
    for relative in relative_paths:
        record: dict[str, Any] = {
            "path": relative,
            "owners": list(ownership.owners_of(relative)),
            "errors": 0,
            "warnings": 0,
            "status": "ok",
        }
        try:
            service, load_findings, plugin = detect_and_load(str(root / relative))
        except Exception as exc:
            # A contract that will not load is the loudest possible finding
            # about that contract, and skipping it would make the sweep read
            # cleaner than the repository is.
            #
            # Deliberately every exception, not a curated list. A malformed
            # YAML file raises `yaml.YAMLError`, which is not a `ValueError`,
            # so a narrower clause let one bad file in a hundred-service
            # monorepo end the whole run with "internal error" -- the least
            # useful thing a sweep can say.
            record.update(status="unreadable", errors=1, detail=str(exc)[:200])
            contracts.append(record)
            continue

        from apiverity.security import run_security_checks

        findings = list(load_findings) + list(run_security_checks(service))
        record["protocol"] = plugin.protocol().value
        record["title"] = service.title
        record["version"] = service.version
        record["operations"] = len(service.operations)

        if base is not None:
            previous = base / relative
            if previous.is_file():
                from apiverity.diff.engine import diff_services
                from apiverity.rules.breaking import evaluate_breaking

                try:
                    old_service, _, _ = detect_and_load(str(previous))
                except Exception as exc:
                    record["compared"] = f"base copy unreadable: {str(exc)[:120]}"
                else:
                    changes = diff_services(old_service, service)
                    findings.extend(evaluate_breaking(changes))
                    record["compared"] = str(previous)
                    record["changes"] = len(changes)
            else:
                # Named rather than silently skipped: "no findings" for a
                # contract that was never compared is not the same claim.
                record["compared"] = None
                record["detail"] = "new in this tree; nothing to compare against"

        record["errors"] = sum(1 for f in findings if f.severity.value == "ERROR")
        record["warnings"] = sum(1 for f in findings if f.severity.value == "WARN")
        record["status"] = "failing" if record["errors"] else "ok"
        record["findings"] = [
            f.model_dump(mode="json") for f in findings if f.severity.value in ("ERROR", "WARN")
        ]
        contracts.append(record)

    by_owner: dict[str, dict[str, Any]] = {}
    for record in contracts:
        for owner in record["owners"] or ["(unowned)"]:
            bucket = by_owner.setdefault(owner, {"contracts": [], "errors": 0, "warnings": 0})
            bucket["contracts"].append(record["path"])
            bucket["errors"] += record["errors"]
            bucket["warnings"] += record["warnings"]

    failing = [r for r in contracts if r["status"] != "ok"]
    _emit(
        {
            "tool": "apiverity",
            "command": "sweep",
            "root": str(root),
            "codeowners": ownership.source,
            "base": str(base) if base else None,
            "contracts_found": len(contracts),
            "contracts_failing": len(failing),
            "unowned": sorted(r["path"] for r in contracts if not r["owners"]),
            "contracts": contracts,
            "by_owner": {k: by_owner[k] for k in sorted(by_owner)},
        },
        getattr(args, "json", False),
    )
    if not getattr(args, "json", False):
        print()
        if ownership.source is None:
            print("No CODEOWNERS found, so nothing here has an owner.")
        print(f"{len(failing)} of {len(contracts)} contract(s) failing.")
        for owner, bucket in sorted(by_owner.items()):
            if bucket["errors"] or bucket["warnings"]:
                print(
                    f"  {owner}: {bucket['errors']} error(s), {bucket['warnings']} warning(s) "
                    f"across {len(bucket['contracts'])} contract(s)"
                )
    return EXIT_FINDINGS if failing else EXIT_OK
