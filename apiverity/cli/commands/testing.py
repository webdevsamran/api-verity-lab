"""Testing lane commands: test, workflow, mock, coverage."""

from __future__ import annotations

import argparse
import sys

from apiverity.cli.commands.common import (
    EXIT_FINDINGS,
    EXIT_OK,
    EXIT_UNREACHABLE,
    EXIT_USAGE,
    NL,
    _emit,
    _load,
    set_last_seed,
    set_last_target,
)


def cmd_test(args: argparse.Namespace) -> int:
    from apiverity.fuzz.minimize import minimize_failures
    from apiverity.fuzz.runner import build_cases, run_cases

    service, _, _ = _load(args.spec)
    set_last_target(args.base_url)
    set_last_seed(args.seed)
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

    if getattr(args, "list_templates", False):
        from apiverity.stateful.templates import TEMPLATES

        for name, factory in sorted(TEMPLATES.items()):
            doc = (factory.__doc__ or "").strip().splitlines()
            print(f"{name:22} {doc[0] if doc else ''}")
        return EXIT_OK

    template = getattr(args, "template", None)
    if template:
        return _emit_template(args, template)

    if getattr(args, "infer", False):
        return _infer_workflow(args)

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


def _infer_workflow(args: argparse.Namespace) -> int:
    """Print a draft manifest built from the spec's declared links.

    Never writes over an existing file without being asked twice -- a draft
    that silently replaced a hand-written manifest would be the worst possible
    outcome of a command whose entire premise is caution.
    """
    from pathlib import Path

    from apiverity.stateful.infer import infer_workflows, render_manifest

    service, _, _ = _load(args.manifest)
    drafts = infer_workflows(service)
    manifest = render_manifest(service, drafts)

    output = getattr(args, "output", None)
    if output:
        target = Path(output)
        if target.exists():
            print(f"error: {output} already exists; refusing to overwrite", file=sys.stderr)
            return EXIT_USAGE
        target.write_text(manifest, encoding="utf-8")
        print(f"wrote {output}")
    else:
        print(manifest, end="")

    if not drafts:
        # Not an error: links are optional, and saying "no drafts" plainly is
        # better than an exit code that reads like the spec was rejected.
        return EXIT_OK
    return EXIT_OK


def _emit_template(args: argparse.Namespace, name: str) -> int:
    """Print a built-in manifest template as YAML.

    These four templates existed, were tested, and had no way to reach them
    from the command line -- so the honest advice for "this spec declares no
    links, now what" had nowhere to point.
    """
    from pathlib import Path

    import yaml

    from apiverity.stateful.templates import TEMPLATES

    factory = TEMPLATES.get(name)
    if factory is None:
        known = ", ".join(sorted(TEMPLATES))
        print(f"error: unknown template '{name}' (known: {known})", file=sys.stderr)
        return EXIT_USAGE

    workflow = factory(base_url=args.base_url or "http://127.0.0.1:8080")
    manifest = yaml.safe_dump(
        workflow.model_dump(mode="json", exclude_none=True), sort_keys=False, allow_unicode=True
    )
    summary = (factory.__doc__ or "").strip().splitlines()
    header = NL.join(
        [
            f"# Built-in template '{name}'.",
            f"# {summary[0] if summary else ''}",
            "# Review allowed_hosts and every destructive step before running this.",
            "",
        ]
    )
    output = getattr(args, "output", None)
    if output:
        target = Path(output)
        if target.exists():
            print(f"error: {output} already exists; refusing to overwrite", file=sys.stderr)
            return EXIT_USAGE
        target.write_text(header + manifest, encoding="utf-8")
        print(f"wrote {output}")
    else:
        print(header + manifest, end="")
    return EXIT_OK
