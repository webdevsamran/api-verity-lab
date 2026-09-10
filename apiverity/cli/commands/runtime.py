"""Runtime lane commands: drift, replay, baseline, regression."""

from __future__ import annotations

import argparse
import json
import sys
import time
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
    active_profile,
    auth_material,
    config_setting,
    fail_on_threshold,
    set_last_contract,
    set_last_seed,
    set_last_target,
)
from apiverity.core.model import Finding, Service
from apiverity.runtime.findings import unify_all

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
    """EXIT_FINDINGS when anything is at or above the threshold, else EXIT_OK.

    The threshold is WARN here, not ERROR: a runtime observation that the
    contract does not describe is a finding about the deployment, and the
    catalogue's severities were written for contract changes. `fail_on` in the
    project config still overrides it -- that key reached no code at all until
    now, so a team adopting the gate on an existing API had the documented way
    to say "report, do not block" and it did nothing.
    """
    floor = fail_on_threshold() if (config_setting("fail_on") or active_profile()) else ""
    if floor == "never":
        return EXIT_OK
    gating = {"error": frozenset({"ERROR"})}.get(floor, _GATING)
    return (
        EXIT_FINDINGS
        if any(str(getattr(f, "severity", "ERROR")).upper() in gating for f in findings)
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
    headers, cert = auth_material(args)
    try:
        report = detect_drift(
            service,
            args.base_url,
            timeout=args.timeout,
            forbid_undeclared_fields=forbid,
            headers=headers,
            cert=cert,
        )
    except Exception as exc:
        print(f"error: target unreachable: {exc}", file=sys.stderr)
        return EXIT_UNREACHABLE
    # `findings` alongside `report`, not instead of it. The four drift modes
    # each returned a differently-shaped report and none of them was covered
    # by the published contract, which constrains a *top-level* `findings`
    # array. Additive: a consumer reading `report.findings` keeps working.
    findings, trend, code = _with_baseline(args, report.findings, args.base_url)
    _emit(
        {
            "tool": "apiverity",
            "command": "drift",
            "report": report,
            "findings": findings,
            **({"trend": trend} if trend else {}),
        },
        args.json,
    )
    return code


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

    otlp_endpoint = getattr(args, "otlp_endpoint", None)
    recorder = None
    if otlp_endpoint:
        from apiverity.exporters.otel import TraceRecorder

        # Seeded from the target and the clock, so two runs against the same
        # server are separate traces without the caller passing an id.
        recorder = TraceRecorder(seed=f"{args.base_url}:{time.time_ns()}")

    try:
        report = detect_mcp_drift(
            service,
            args.base_url,
            timeout=args.timeout,
            headers=headers or None,
            max_pages=getattr(args, "max_list_pages", 50),
            check_auth=not getattr(args, "skip_auth_probe", False),
            recorder=recorder,
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
        "findings": unify_all(report.findings),
    }
    payload["findings"], trend, mcp_code = _with_baseline(args, report.findings, args.base_url)
    if trend:
        payload["trend"] = trend

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
        payload["findings"], trend, mcp_code = _with_baseline(args, report.findings, args.base_url)
        if trend:
            payload["trend"] = trend
        if not execute:
            print(
                f"dry run: {len(invocation.plan)} tool call(s) planned, none sent. "
                "Add --execute to send them.",
                file=sys.stderr,
            )

    if recorder is not None:
        report.trace = {
            "trace_id": recorder.trace_id,
            "spans": [
                {
                    "span_id": span.span_id,
                    "name": span.name,
                    "status": span.status,
                    "duration_ms": span.duration_ms,
                }
                for span in recorder.spans
            ],
        }
        payload["report"] = report
        try:
            status = recorder.export(str(otlp_endpoint))
        except Exception as exc:
            # A collector that is down must not fail a drift run. The findings
            # were established before the export was attempted, and losing them
            # because a sidecar restarted is how a gate becomes the thing teams
            # switch off.
            print(f"warning: OTLP export to {otlp_endpoint} failed: {exc}", file=sys.stderr)
        else:
            if status >= 400:
                print(
                    f"warning: OTLP collector at {otlp_endpoint} answered {status}",
                    file=sys.stderr,
                )

    _emit(payload, args.json)
    return mcp_code


def _drift_corpus(
    args: argparse.Namespace,
    service: Service,
    corpus: str,
    *,
    forbid_undeclared_fields: bool,
) -> int:
    from apiverity.runtime.corpus_drift import analyze_corpus
    from apiverity.traffic.redact import RedactionConfig, import_har

    def read(path: str) -> list[Any] | int:
        try:
            return import_har(
                path,
                RedactionConfig(),
                include_response_bodies=getattr(args, "include_response_bodies", False),
            )
        except (OSError, ValueError) as exc:
            print(f"error: could not read corpus '{path}': {exc}", file=sys.stderr)
            return EXIT_USAGE

    loaded = read(corpus)
    if isinstance(loaded, int):
        return loaded
    entries = loaded

    # Behaviour against behaviour, rather than behaviour against the document.
    # Needs response bodies on both sides: a corpus imported without them has
    # no fields to profile, and comparing two empty profiles would report a
    # confident "nothing changed".
    semantic = None
    against = getattr(args, "against_corpus", None)
    if against:
        if not getattr(args, "include_response_bodies", False):
            print(
                "error: --against-corpus compares response *contents*, which "
                "--include-response-bodies is what reads. Pass it, and read "
                "docs/safety-model.md first: a HAR of a real service holds real user data",
                file=sys.stderr,
            )
            return EXIT_USAGE
        earlier = read(against)
        if isinstance(earlier, int):
            return earlier
        from apiverity.runtime.semantic import MIN_SAMPLES, compare_profiles, profile_corpus

        semantic = compare_profiles(
            profile_corpus(service, earlier, source=against),
            profile_corpus(service, entries, source=corpus),
            min_samples=int(getattr(args, "min_samples", None) or MIN_SAMPLES),
        )

    report = analyze_corpus(
        service,
        entries,
        source=corpus,
        forbid_undeclared_fields=forbid_undeclared_fields,
    )
    # Computed once, before either rendering. The text branch used to fall
    # through to its own `_gate(report.findings)`, so `--baseline` silenced
    # nothing unless `--json` was also passed -- a flag that worked in one
    # output mode and quietly did not in the other.
    all_findings = list(report.findings) + list(semantic.findings if semantic else [])
    findings, trend, code = _with_baseline(args, all_findings, corpus)

    if args.json:
        _emit(
            {
                "tool": "apiverity",
                "command": "drift",
                "report": report,
                **({"semantic": semantic} if semantic else {}),
                "findings": findings,
                **({"trend": trend} if trend else {}),
            },
            True,
        )
        return code

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

    if trend.get("baseline"):
        print(
            f"  against baseline {trend['baseline']}: {trend['new']} new, "
            f"{trend['known']} known, {len(trend['resolved'])} resolved"
        )
    if trend.get("saved"):
        print(f"  baseline written to {trend['saved']}")

    if semantic is not None:
        print()
        print(f"behaviour vs {semantic.before}:")
        print(f"  {semantic.compared} field(s) compared")
        if semantic.skipped_for_samples:
            # Said out loud. "Nothing changed" and "we could not tell" are
            # different answers, and only one of them is reassuring.
            print(
                f"  {semantic.skipped_for_samples} field(s) not compared: "
                "too few responses on one side"
            )
        for change in semantic.findings:
            evidence = (
                f"{change.before.get('present', 0)}/{change.before.get('observations', 0)}"
                f" -> {change.after.get('present', 0)}/{change.after.get('observations', 0)}"
            )
            print(
                f"  [{change.severity}] {change.rule_id} {change.operation_key} "
                f"{change.field_path}: {change.message} ({evidence})"
            )
        if not semantic.findings:
            print("  no behavioural change found")

    if not all_findings:
        print("no drift found")
        return EXIT_OK

    if not report.findings:
        return code

    print(f"{NL}findings ({len(report.findings)} distinct):")
    # `findings` now carries the semantic ones after the corpus ones, so the
    # zip takes the prefix rather than asserting equal length.
    for finding, unified in zip(report.findings, findings, strict=False):
        kind = "systematic" if finding.systematic else ("one-off" if finding.one_off else "")
        share = f"{finding.occurrences}/{finding.observations}"
        suffix = f" [{kind}]" if kind else ""
        state = f" [{unified['state']}]" if "state" in unified else ""
        span = (
            f", {finding.first_seen} to {finding.last_seen}"
            if finding.first_seen and finding.last_seen != finding.first_seen
            else (f", at {finding.first_seen}" if finding.first_seen else "")
        )
        print(
            f"  [{finding.severity}] {finding.rule_id} {finding.operation_key}: "
            f"{finding.message} ({share}, {finding.frequency * 100:.0f}%{span}){suffix}{state}"
        )
    return code


def _replay_gate(args: argparse.Namespace, entries: list[Any]) -> int | None:
    """The four controls `SAFETY_MODEL.md` numbers, applied.

    None means the run may proceed. `apiverity/traffic/safety.py` held all of
    this and no command called it: `replay_corpus` had a weaker check of its
    own, whose production branch keyed off a flag on corpus entries that
    nothing ever set.

    A dry run -- the default -- is not gated. Printing which requests *would*
    be sent is the thing an operator does to decide, and requiring the
    confirmation token to see the token would be a loop.
    """
    from apiverity.traffic.safety import (
        DESTRUCTIVE_METHODS,
        build_dry_run_plan,
        check_replay_safety,
        classify_target,
        confirmation_token,
    )

    methods = {e.method.upper() for e in entries}
    writes = sorted(methods & DESTRUCTIVE_METHODS)
    if not getattr(args, "execute", False):
        plan = build_dry_run_plan(entries, args.base_url)
        target = classify_target(args.base_url).classification
        print(f"dry run: {len(plan)} request(s) would be sent to a {target} target")
        for planned in plan[:20]:
            print(f"  {planned.method:7} {planned.url}")
        if len(plan) > 20:
            print(f"  ... and {len(plan) - 20} more")
        if writes:
            token = confirmation_token(args.base_url, set(writes), len(entries))
            unlock = [f"--allow-method {m}" for m in writes] + [f"--confirm {token}"]
            if target in ("production", "unknown"):
                # Printed here rather than discovered on the next run: telling
                # somebody a command that will then be refused is worse than
                # not telling them one.
                unlock.append("--i-know-this-is-production")
            print()
            print(
                f"this corpus writes ({', '.join(writes)}) to a {target} target. "
                "To send it: " + " ".join([*unlock, "--execute"])
            )
        return None

    outcome = check_replay_safety(
        base_url=args.base_url,
        allowed_hosts=list(getattr(args, "allow_host", None) or []),
        entries=entries,
        destructive_allowlist={m.upper() for m in (getattr(args, "allow_method", None) or [])},
        confirmation=getattr(args, "confirm", None),
        production_acknowledged=bool(getattr(args, "i_know_this_is_production", False)),
    )
    if not outcome.approved:
        print(f"error: {outcome.reason}", file=sys.stderr)
        return EXIT_USAGE
    return None


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
    decision = _replay_gate(args, entries)
    if decision is not None:
        return decision

    try:
        replay_headers, replay_cert = auth_material(args)
        report = replay_corpus(
            entries,
            args.base_url,
            allowed_hosts=args.allow_host,
            dry_run=not args.execute,
            rate_per_second=args.rate,
            allow_production=args.i_know_this_is_production,
            headers=replay_headers,
            cert=replay_cert,
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
        headers, cert = auth_material(args)
        report = measure(
            service,
            args.base_url,
            iterations=args.iterations,
            warmup=getattr(args, "warmup", 0) or 0,
            headers=headers,
            cert=cert,
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


def _regression_curve(args: argparse.Namespace, service: Service) -> int:
    """Sweep concurrency and report the shape, rather than one point.

    A separate path rather than a flag inside the measurement, because a curve
    is not a measurement with a tolerance: comparing it against a baseline
    would mean deciding what "the same shape" is, and this reports the shape
    instead of judging it.
    """
    from apiverity.performance.curve import measure_curve, parse_levels

    try:
        levels = parse_levels(str(args.curve))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    try:
        headers, cert = auth_material(args)
        report = measure_curve(
            service,
            args.base_url,
            levels=levels,
            iterations=args.iterations,
            warmup=getattr(args, "warmup", 0) or 0,
            headers=headers,
            cert=cert,
        )
    except Exception as exc:
        print(f"error: target unreachable: {exc}", file=sys.stderr)
        return EXIT_UNREACHABLE

    if args.json:
        _emit({"tool": "apiverity", "command": "regression", "curve": report}, True)
        return EXIT_OK

    print(f"target: {report.target}")
    print(f"  levels swept: {', '.join(str(level) for level in report.levels)}")
    print(f"  {report.iterations_per_level} requests per operation per level")
    print(
        "  measures this client and that service together; numbers below the service's "
        "own ceiling are expected"
    )
    for curve in report.curves:
        print()
        print(f"{curve.operation_key}: {curve.summary()}")
        print(f"  {'conc':>5}  {'p50':>8}  {'p95':>8}  {'p99':>8}  {'rps':>8}  {'err%':>6}")
        for point in curve.points:
            print(
                f"  {point.concurrency:>5}  {point.p50_ms:>8.1f}  {point.p95_ms:>8.1f}  "
                f"{point.p99_ms:>8.1f}  {point.throughput_rps:>8.1f}  "
                f"{point.error_rate_pct:>6.2f}"
            )
    return EXIT_OK


#: Methods a load shape drives without asking. Everything else changes state
#: at whatever rate the profile names, which is a different conversation from
#: "measure this endpoint".
_READ_METHODS = ("GET", "HEAD", "OPTIONS")


def _regression_shape(args: argparse.Namespace, service: Service) -> int:
    """Drive one operation at a declared arrival rate.

    One operation, named, rather than every operation in the contract: a
    profile states a rate, and running `constant:60s@50` against forty
    operations means two thousand requests a second at a target the operator
    asked for fifty.
    """
    import httpx

    from apiverity.performance.profiles import execute, parse_profile

    try:
        profile = parse_profile(str(args.shape))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    key = getattr(args, "operation", None)
    if not key:
        print(
            "error: --shape needs --operation KEY (for example --operation 'GET /users'). "
            "A rate is stated for one endpoint; applying it to every operation in the "
            "contract would multiply it by the size of the API.",
            file=sys.stderr,
        )
        return EXIT_USAGE
    operation = service.find_operation(key)
    if operation is None or not operation.path:
        known = ", ".join(service.operation_keys()[:8])
        print(f"error: no operation {key!r} in this contract (it has: {known})", file=sys.stderr)
        return EXIT_USAGE

    method = (operation.method or "GET").upper()
    if method not in _READ_METHODS and not getattr(args, "include_mutations", False):
        print(
            f"error: {key!r} is a {method}. Driving it at {profile.rate_start:g} requests a "
            "second writes to the target that many times a second. Pass --include-mutations "
            "if that is what you mean.",
            file=sys.stderr,
        )
        return EXIT_USAGE

    headers, cert = auth_material(args)
    path = str(getattr(args, "path", None) or operation.path)
    if "{" in path:
        print(
            f"error: {key!r} is declared at {operation.path!r}, which is a template rather "
            "than a URL. Pass --path with a concrete one (--path /users/42): a load shape "
            "sends the same request thousands of times and there is nothing here that "
            "knows a real id.",
            file=sys.stderr,
        )
        return EXIT_USAGE
    with httpx.Client(
        base_url=str(args.base_url).rstrip("/"),
        timeout=float(getattr(args, "timeout", 10.0) or 10.0),
        limits=httpx.Limits(max_connections=256, max_keepalive_connections=256),
        headers=headers or None,
        cert=cert,
    ) as client:

        def transport(verb: str, target: str) -> tuple[int, float]:
            started = time.perf_counter()
            response = client.request(verb, target)
            return response.status_code, (time.perf_counter() - started) * 1000.0

        try:
            result = execute(profile, transport, method=method, path=path)
        except Exception as exc:
            print(f"error: target unreachable: {exc}", file=sys.stderr)
            return EXIT_UNREACHABLE

    if result.sent == 0:
        print(
            f"error: target unreachable: nothing answered at {args.base_url}{path}",
            file=sys.stderr,
        )
        return EXIT_UNREACHABLE

    payload = {
        "tool": "apiverity",
        "command": "regression",
        "shape": {
            "profile": result.profile,
            "operation_key": key,
            "path": path,
            "requested_rps": profile.rate_start,
            "achieved_rps": round(result.achieved_rps, 2),
            "scheduled": result.scheduled,
            "sent": result.sent,
            "errors": result.errors,
            "status_counts": result.status_counts,
            "p50_ms": round(result.p50, 2),
            "p95_ms": round(result.p95, 2),
            "p99_ms": round(result.p99, 2),
            "max_late_ms": round(result.max_late_ms, 2),
            "kept_up": result.kept_up(),
            "dispatch_s": round(result.dispatch_s, 3),
            "duration_s": round(result.duration_s, 3),
        },
    }
    if getattr(args, "json", False):
        _emit(payload, True)
    else:
        shape = payload["shape"]
        assert isinstance(shape, dict)
        print(f"{key}  {result.profile}")
        print(f"  target: {args.base_url}{path}")
        print(f"  scheduled {result.scheduled}, sent {result.sent}, errors {result.errors}")
        print(
            f"  requested {profile.rate_start:g}/s, offered {result.achieved_rps:.1f}/s "
            f"over {result.dispatch_s:.1f}s ({result.duration_s:.1f}s including the drain)"
        )
        print(f"  p50 {result.p50:.1f}ms   p95 {result.p95:.1f}ms   p99 {result.p99:.1f}ms")
        print(f"  statuses: {result.status_counts}")
        if not result.kept_up():
            # Printed loudly because the numbers above are not what they look
            # like: with requests going out this far after they were due, the
            # latencies describe a load nobody asked for.
            print(
                f"  WARNING: this generator fell up to {result.max_late_ms:.0f}ms behind its "
                "own schedule. The offered load was not the profile above -- lower the rate, "
                "or drive it from somewhere closer to the target."
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

    if getattr(args, "curve", None):
        return _regression_curve(args, service)

    if getattr(args, "shape", None):
        return _regression_shape(args, service)

    try:
        headers, cert = auth_material(args)
        report = measure(
            service,
            args.base_url,
            iterations=args.iterations,
            warmup=getattr(args, "warmup", 0) or 0,
            concurrency=max(1, int(getattr(args, "concurrency", 1) or 1)),
            headers=headers,
            cert=cert,
        )
    except Exception as exc:
        print(f"error: target unreachable: {exc}", file=sys.stderr)
        return EXIT_UNREACHABLE
    if report.nothing_answered():
        print(f"error: target unreachable: nothing answered at {args.base_url}", file=sys.stderr)
        return EXIT_UNREACHABLE
    violations = evaluate_policies(report, args.policy or [])
    # Objectives the contract declared, rather than a number in somebody's CI
    # file. Off by default: measuring against a promise the caller did not ask
    # to be measured against would fail builds for a `x-slo` block somebody
    # added as documentation.
    objective_findings: list[Finding] = []
    if getattr(args, "slo", False):
        from apiverity.performance.slo import evaluate as evaluate_objectives

        objective_findings = evaluate_objectives(service, report)
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
            # Kept out of `violations`, which is a list of strings a gate
            # counts. These are findings with a severity and a hint, and the
            # hint is the part that matters: one run is not a judgement about
            # an objective promised over a window.
            **({"findings": objective_findings} if objective_findings else {}),
            # Printed, but not fatal: "the run was too short to tell" is not a
            # regression, and failing a build on it is how a gate gets turned
            # off. The count is what tells you to raise --iterations.
            "inconclusive": inconclusive,
            "report": report,
        },
        args.json,
    )
    exceeded = [f for f in objective_findings if f.severity.value == "ERROR"]
    return EXIT_FINDINGS if violations or exceeded else EXIT_OK


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
            "findings": unify_all(findings),
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


def _with_baseline(
    args: argparse.Namespace, findings: list[Any], target: str
) -> tuple[list[dict[str, Any]], dict[str, Any], int]:
    """Unified findings, the baseline block, and the exit code to use.

    Point `drift` at a service that has run for three years and it reports
    forty true findings, none of which are today's problem. The gate goes red
    on the first run, somebody makes it advisory, and it never comes back. With
    a baseline, the gate fails on what is *newly* wrong -- the only thing a
    pull request can be held responsible for.
    """
    from apiverity.runtime.drift_trend import classify, export, read_baseline

    unified = unify_all(findings)
    block: dict[str, Any] = {}

    save = getattr(args, "save_baseline", None)
    if save:
        Path(save).write_text(
            json.dumps(export(unified, target=target), indent=2) + NL, encoding="utf-8"
        )
        block["saved"] = str(save)

    path = getattr(args, "baseline", None)
    if not path:
        return unified, block, _gate(findings)

    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        print(f"error: could not read baseline '{path}': {exc}", file=sys.stderr)
        return unified, block, EXIT_USAGE

    marked, resolved = classify(unified, read_baseline(data))
    new = [f for f in marked if f["state"] == "new"]
    block.update(
        {
            "baseline": str(path),
            "known": len(marked) - len(new),
            "new": len(new),
            "resolved": resolved,
        }
    )
    # Only the new ones can fail the run. Everything else is history, and it
    # is still in the artifact under `state: known`.
    return marked, block, _gate([f for f in marked if f["state"] == "new"])


def cmd_ghosts(args: argparse.Namespace) -> int:
    """Routes the contract no longer declares that the server still answers."""
    from apiverity.runtime.ghosts import (
        Candidate,
        audit,
        removed_operations,
        unmatched_paths,
    )

    service, _, _ = _load(args.spec)
    set_last_target(args.base_url)

    candidates: list[Candidate] = []
    previous: Service | None = None
    if getattr(args, "was", None):
        previous, _, _ = _load(args.was)
        candidates.extend(removed_operations(previous, service))

    if getattr(args, "corpus", None):
        from apiverity.runtime.corpus_drift import analyze_corpus
        from apiverity.traffic.redact import RedactionConfig, import_har

        try:
            entries = import_har(args.corpus, RedactionConfig())
        except (OSError, ValueError) as exc:
            print(f"error: could not read corpus '{args.corpus}': {exc}", file=sys.stderr)
            return EXIT_USAGE
        quality = analyze_corpus(service, entries, source=args.corpus).quality
        candidates.extend(unmatched_paths(quality.unmatched_paths, args.corpus))

    if not candidates:
        # Not a pass. Nothing was asked, so nothing was established, and a
        # green run here would be the most misleading output in the tool.
        print(
            "error: no candidate routes. Pass --was <previous spec> for the operations it "
            "declared and this one does not, or --corpus <har> for paths real traffic used "
            "that this contract does not match",
            file=sys.stderr,
        )
        return EXIT_USAGE

    # Deduplicated, keeping the first reason each route came up.
    seen: dict[str, Candidate] = {}
    for candidate in candidates:
        seen.setdefault(candidate.key, candidate)

    try:
        headers, cert = auth_material(args)
        report = audit(
            list(seen.values()),
            args.base_url,
            old=previous,
            timeout=args.timeout,
            headers=headers,
            cert=cert,
        )
    except Exception as exc:  # pragma: no cover - defensive
        print(f"error: target unreachable: {exc}", file=sys.stderr)
        return EXIT_UNREACHABLE

    _emit(
        {
            "tool": "apiverity",
            "command": "ghosts",
            "target": args.base_url,
            "report": report,
            "findings": unify_all(report.findings),
        },
        getattr(args, "json", False),
    )
    return _gate(report.findings)
