"""Runtime lane commands: drift, replay, baseline, regression."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from apiverity.cli.commands.common import (
    EXIT_FINDINGS,
    EXIT_OK,
    EXIT_UNREACHABLE,
    EXIT_USAGE,
    NL,
    _emit,
    _load,
    set_last_contract,
    set_last_seed,
    set_last_target,
)
from apiverity.core.model import Service

#: Severities that make a gate fail. INFO is excluded on purpose.
#:
#: `drift` used to exit 1 whenever the report carried any finding at all, which
#: meant a fully conformant MCP server failed the gate for telling us something
#: true and harmless -- `MCP-CONF-LIST-ORDER-NONDETERMINISTIC` says in its own
#: message that it is not a defect, and then failed the build. Reporting an
#: observation and failing on it are different jobs; the artifact still carries
#: every INFO finding either way.
_GATING = frozenset({"WARN", "ERROR"})


def _gate(findings: list[Any]) -> int:
    """EXIT_FINDINGS when anything is at or above WARN, else EXIT_OK."""
    return (
        EXIT_FINDINGS
        if any(str(getattr(f, "severity", "ERROR")).upper() in _GATING for f in findings)
        else EXIT_OK
    )


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

    if service.protocol.value == "mcp":
        # Same shape of reason: `tools/list` is how an MCP server states what
        # it serves, and calling one tool at a time could never notice a tool
        # the manifest never declared.
        return _drift_mcp(args, service)

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
    return _gate(report.findings)


def _drift_mcp(args: argparse.Namespace, service: Service) -> int:
    """Declared MCP manifest vs a live server, read-only."""
    from apiverity.runtime.mcp_drift import McpTransportError, detect_mcp_drift

    set_last_target(args.base_url)
    headers: dict[str, str] = {}
    for item in getattr(args, "header", None) or []:
        name, sep, value = item.partition("=")
        if not sep:
            print(f"error: --header expects NAME=VALUE, got {item!r}", file=sys.stderr)
            return EXIT_USAGE
        headers[name.strip()] = value.strip()

    invoke = list(getattr(args, "invoke_tool", None) or [])
    execute = bool(getattr(args, "execute", False))
    if execute and not invoke:
        print(
            "error: --execute needs at least one --invoke-tool; without it the "
            "server's own tool list would decide what runs",
            file=sys.stderr,
        )
        return EXIT_USAGE

    try:
        report = detect_mcp_drift(
            service,
            args.base_url,
            timeout=args.timeout,
            headers=headers or None,
            max_pages=getattr(args, "max_list_pages", 50),
            check_auth=not getattr(args, "skip_auth_probe", False),
        )
    except McpTransportError as exc:
        print(f"error: target unreachable: {exc}", file=sys.stderr)
        return EXIT_UNREACHABLE
    except Exception as exc:  # pragma: no cover - defensive
        print(f"error: target unreachable: {exc}", file=sys.stderr)
        return EXIT_UNREACHABLE

    # Deliberately no "protocol" key. `_drift_graphql` writes one, and
    # schemas/result-v1.schema.json constrains it -- but the value already
    # reaches the artifact as `protocol_version` from `_LAST_PROTOCOL`, set
    # when the manifest was loaded. Writing it twice is how the two would
    # eventually disagree.
    payload: dict[str, Any] = {
        "tool": "apiverity",
        "command": "drift",
        "target": args.base_url,
        "report": report,
    }

    if invoke:
        from apiverity.runtime.mcp_invoke import InvokeRefused, invoke_tools

        set_last_seed(int(getattr(args, "seed", 0)))
        try:
            invocation = invoke_tools(
                service,
                args.base_url,
                invoke,
                execute=execute,
                allow_production=bool(getattr(args, "i_know_this_is_production", False)),
                timeout=args.timeout,
                headers=headers or None,
                seed=int(getattr(args, "seed", 0)),
            )
        except InvokeRefused as exc:
            print(f"error: {exc}", file=sys.stderr)
            return EXIT_USAGE
        except McpTransportError as exc:
            print(f"error: target unreachable: {exc}", file=sys.stderr)
            return EXIT_UNREACHABLE
        payload["invocation"] = invocation
        report.findings.extend(invocation.findings)
        if not execute:
            print(
                f"dry run: {len(invocation.plan)} tool call(s) planned, none sent. "
                "Add --execute to send them.",
                file=sys.stderr,
            )

    _emit(payload, args.json)
    return _gate(report.findings)


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
        return _gate(report.findings)

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
    if quality.first_seen:
        print(f"  covering {quality.first_seen} to {quality.last_seen}")
    elif quality.entries:
        # A frequency with no window behind it is a ratio, not a trend.
        print("  no entry carried a timestamp, so no window can be reported")

    if not report.findings:
        print("no drift found")
        return EXIT_OK

    print(f"{NL}findings ({len(report.findings)} distinct):")
    for finding in report.findings:
        kind = "systematic" if finding.systematic else ("one-off" if finding.one_off else "")
        share = f"{finding.occurrences}/{finding.observations}"
        suffix = f" [{kind}]" if kind else ""
        span = (
            f", {finding.first_seen} to {finding.last_seen}"
            if finding.first_seen and finding.last_seen != finding.first_seen
            else (f", at {finding.first_seen}" if finding.first_seen else "")
        )
        print(
            f"  [{finding.severity}] {finding.rule_id} {finding.operation_key}: "
            f"{finding.message} ({share}, {finding.frequency * 100:.0f}%{span}){suffix}"
        )
    return _gate(report.findings)


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
    return _gate(findings)


def _capture_tools(args: argparse.Namespace) -> tuple[list[dict[str, Any]], str] | int:
    """The tool surface to lock, from a saved manifest or a live server."""
    from apiverity.runtime.mcp_lock import tools_from_document
    from apiverity.specs import parse_document, read_source
    from apiverity.specs.mcp.manifest import ManifestShapeError

    base_url = getattr(args, "base_url", None)
    source = getattr(args, "source", None)
    if bool(base_url) == bool(source):
        print(
            "error: mcp-lock needs exactly one of a manifest path or --base-url",
            file=sys.stderr,
        )
        return EXIT_USAGE

    if base_url:
        from apiverity.specs.mcp.runner import McpClient, McpTransportError, Observation, list_tools

        headers: dict[str, str] = {}
        for item in getattr(args, "header", None) or []:
            name, sep, value = item.partition("=")
            if not sep:
                print(f"error: --header expects NAME=VALUE, got {item!r}", file=sys.stderr)
                return EXIT_USAGE
            headers[name.strip()] = value.strip()
        set_last_target(base_url)
        try:
            with McpClient(base_url, timeout=args.timeout, headers=headers or None) as client:
                observation = Observation(endpoint=base_url)
                tools, _ = list_tools(client, observation, max_pages=args.max_list_pages)
        except McpTransportError as exc:
            print(f"error: target unreachable: {exc}", file=sys.stderr)
            return EXIT_UNREACHABLE
        if not observation.pagination_exhausted:
            # A baseline built from part of a tool list would report every tool
            # on a later page as removed, forever.
            print(
                f"error: stopped after {observation.pages_read} pages of tools/list with a "
                "cursor still set; raise --max-list-pages. A partial capture is not a baseline",
                file=sys.stderr,
            )
            return EXIT_USAGE
        set_last_contract(None, "mcp")
        return tools, base_url

    resolved, raw = read_source(str(source))
    try:
        tools = tools_from_document(parse_document(raw))
    except ManifestShapeError as exc:
        print(f"error: {source} is not an MCP tool manifest: {exc}", file=sys.stderr)
        return EXIT_USAGE
    set_last_contract(resolved, "mcp")
    # Posix, because the lockfile is committed and reviewed on every platform
    # the team uses, and a backslash path in it is noise in every diff opened
    # somewhere else.
    return tools, Path(resolved).as_posix()


def cmd_mcp_lock(args: argparse.Namespace) -> int:
    """Write or check `mcp.lock`, a reviewed baseline for a tool surface."""
    from apiverity import __version__
    from apiverity.runtime.mcp_lock import (
        DEFAULT_KEY_ENV,
        LockError,
        build_lock,
        compare,
        dumps_lock,
        load_lock,
    )

    captured = _capture_tools(args)
    if isinstance(captured, int):
        return captured
    tools, source = captured

    lock_path = Path(getattr(args, "lock", None) or "mcp.lock")
    action = getattr(args, "action", "check")

    if action == "write":
        if lock_path.exists() and not getattr(args, "force", False):
            print(
                f"error: {lock_path} already exists; pass --force to overwrite. Rewriting a "
                "baseline is the thing this file exists to make visible",
                file=sys.stderr,
            )
            return EXIT_USAGE
        try:
            body = build_lock(
                tools,
                source=source,
                tool_version=__version__,
                surface_version=getattr(args, "surface_version", None) or "1.0.0",
                key_env=(getattr(args, "key_env", None) or DEFAULT_KEY_ENV)
                if getattr(args, "sign", False)
                else None,
            )
        except LockError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return EXIT_USAGE
        lock_path.write_text(dumps_lock(body), encoding="utf-8")
        _emit(
            {
                "tool": "apiverity",
                "command": "mcp-lock",
                "action": "write",
                "lock": str(lock_path),
                "source": source,
                "tools_locked": len(tools),
                "surface_version": body["surface_version"],
                "surface_hash": body["surface_hash"],
                "signed": "signature" in body,
            },
            getattr(args, "json", False),
        )
        return EXIT_OK

    try:
        body = load_lock(lock_path)
    except LockError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    delta = compare(
        body,
        tools,
        require_minor_for_warnings=bool(getattr(args, "require_minor_for_warnings", False)),
    )
    _emit(
        {
            "tool": "apiverity",
            "command": "mcp-lock",
            "action": "check",
            "lock": str(lock_path),
            "source": source,
            "changed": delta.changed,
            "added": delta.added,
            "removed": delta.removed,
            "modified": delta.modified,
            "surface_version": delta.surface_version,
            "signature": delta.signature_state,
            "advice": delta.advice,
            "findings": delta.findings,
        },
        getattr(args, "json", False),
    )

    # Any change fails, not just a breaking one. The subject of this command is
    # "did the surface move without review", and an added tool -- additive by
    # every rule in the catalogue -- is exactly the case worth stopping on.
    if delta.changed or delta.signature_state == "invalid":
        return EXIT_FINDINGS
    return _gate(delta.findings)


def cmd_mcp_inventory(args: argparse.Namespace) -> int:
    """Which MCP servers this machine is configured to talk to."""
    from apiverity.runtime.mcp_inventory import coverage_note, take_inventory

    report = take_inventory(
        getattr(args, "root", "."),
        extra_configs=list(getattr(args, "config", None) or []),
        approved_path=getattr(args, "inventory", None),
        include_home=bool(getattr(args, "include_home", False)),
    )
    _emit(
        {
            "tool": "apiverity",
            "command": "mcp-inventory",
            "root": report.root,
            "coverage": coverage_note(report),
            "paths_examined": report.paths_examined,
            "servers": report.servers,
            "approved": report.approved,
            "findings": report.findings,
        },
        getattr(args, "json", False),
    )
    if not getattr(args, "json", False):
        # Printed after the payload, because a count of zero is the number a
        # reader is most likely to misread, and the sentence that qualifies it
        # has to be the last thing on screen.
        print()
        print(coverage_note(report))
    return _gate(report.findings)


def _calls_from(source: str, service: Service | None) -> list[dict[str, Any]] | int:
    """Observed calls, from a HAR or from a call log an agent wrote.

    A HAR records a concrete URL, so turning one into an operation key needs
    the contract; a call log already names the operation and does not. Refusing
    a HAR without `--spec` is better than matching on raw paths, which would
    budget `/orders/41` and `/orders/42` separately and never trip a limit.
    """
    import json as _json

    from apiverity.runtime.corpus_drift import match_operation
    from apiverity.traffic.redact import RedactionConfig, import_har

    try:
        raw = _json.loads(Path(source).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        print(f"error: could not read {source}: {exc}", file=sys.stderr)
        return EXIT_USAGE

    if isinstance(raw, dict) and isinstance(raw.get("log"), dict):
        if service is None:
            print(
                "error: a HAR records concrete URLs, so --spec is needed to resolve them to "
                "operations. Without it every path parameter would be budgeted separately",
                file=sys.stderr,
            )
            return EXIT_USAGE
        calls: list[dict[str, Any]] = []
        for entry in import_har(source, RedactionConfig()):
            from urllib.parse import urlparse

            op = match_operation(
                service, str(entry.get("method") or ""), urlparse(str(entry.get("url") or "")).path
            )
            if op is None:
                continue
            calls.append({"operation_key": op.key, "at": entry.get("started_at")})
        return calls

    entries = raw.get("calls") if isinstance(raw, dict) else raw
    if not isinstance(entries, list):
        print(
            f"error: {source} is neither a HAR nor a call log (a list of "
            '{"operation"|"tool", "at"} objects)',
            file=sys.stderr,
        )
        return EXIT_USAGE

    out: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        tool = entry.get("tool")
        key = f"tool {tool}" if isinstance(tool, str) else entry.get("operation")
        if isinstance(key, str) and key:
            out.append({"operation_key": key, "at": entry.get("at")})
    return out


def cmd_budget(args: argparse.Namespace) -> int:
    """Observed calls against a declared call budget."""
    from apiverity.rules.budget import BudgetError, evaluate, load_budget

    service: Service | None = None
    declared: set[str] | None = None
    if getattr(args, "spec", None):
        service, _, _ = _load(args.spec)
        declared = {op.key for op in service.operations}

    try:
        budget = load_budget(args.budget)
    except BudgetError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    calls = _calls_from(args.calls, service)
    if isinstance(calls, int):
        return calls

    findings = evaluate(budget, calls, declared_operations=declared)
    _emit(
        {
            "tool": "apiverity",
            "command": "budget",
            "budget": budget.source,
            "calls_source": args.calls,
            "calls_observed": len(calls),
            "limits": len(budget.limits),
            "deny_by_default": budget.deny_by_default,
            "findings": findings,
        },
        getattr(args, "json", False),
    )
    return _gate(findings)
