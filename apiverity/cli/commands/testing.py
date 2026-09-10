"""Testing lane commands: test, workflow, mock, coverage."""

from __future__ import annotations

import argparse
import sys
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
    if service.protocol.value == "graphql":
        # GraphQL cannot go through the HTTP runner: it answers a malformed
        # query with 200 and an `errors` array, so a status-code verdict marks
        # every failure a pass.
        return _test_graphql(args)
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

    if getattr(args, "to_arazzo", False):
        return _to_arazzo(args)

    imported = _read_arazzo_if_it_is_one(args)
    if isinstance(imported, int):
        return imported
    wf = imported if imported is not None else load_workflow_manifest(args.manifest)
    base_url = args.base_url or wf.base_url
    if not base_url:
        print("error: no base URL (pass --base-url or set base_url in manifest)", file=sys.stderr)
        return EXIT_USAGE
    inputs, bad = _workflow_inputs(args)
    if bad is not None:
        print(f"error: --input {bad!r} is not NAME=VALUE", file=sys.stderr)
        return EXIT_USAGE

    if not _preflight(wf, inputs, skip=getattr(args, "no_preflight", False)):
        return EXIT_USAGE

    try:
        result = WorkflowEngine(wf, base_url, inputs).run()
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

    if getattr(args, "workspace", None):
        return _serve_workspace(args)
    if not args.spec:
        print("error: pass a contract to mock, or --workspace FILE", file=sys.stderr)
        return EXIT_USAGE

    service, _, _ = _load(args.spec)
    faults = FaultConfig(
        latency_ms=args.latency_ms,
        force_status=args.force_status,
        malformed_json=args.malformed,
        rate_limit_after=args.rate_limit_after,
    )
    host = "127.0.0.1"  # always localhost by default
    if getattr(args, "json", False):
        # Printed before the server blocks, so a script can read the address it
        # is about to talk to. A --json that produced nothing until Ctrl+C
        # would be a flag that does nothing.
        _emit(
            {
                "tool": "apiverity",
                "command": "mock",
                "base_url": f"http://{host}:{args.port}",
                "operations": len(service.operations),
                "faults": {
                    "latency_ms": args.latency_ms,
                    "force_status": args.force_status,
                    "malformed_json": args.malformed,
                    "rate_limit_after": args.rate_limit_after,
                },
            },
            True,
        )
    serve(service, host=host, port=args.port, faults=faults)
    return EXIT_OK


def _serve_workspace(args: argparse.Namespace) -> int:
    """Serve every contract a workspace names, under one seed.

    The address table is printed *before* the servers block, and to stdout,
    because ports may be ephemeral: a workspace whose addresses only appear
    after Ctrl+C is a workspace nothing can connect to.
    """
    from apiverity.core.artifact import contract_hash
    from apiverity.mock.virtualization import (
        VirtualizationWorkspace,
        WorkspaceError,
        load_workspace,
    )

    try:
        definition = load_workspace(args.workspace)
    except (OSError, WorkspaceError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    if args.spec:
        # Both would be two different answers to "what is being served", and
        # picking one silently is how somebody ends up debugging a service
        # that is not running.
        print(
            f"error: --workspace serves the contracts {args.workspace} names; "
            f"drop the {args.spec!r} argument",
            file=sys.stderr,
        )
        return EXIT_USAGE

    # The artifact is stamped with the workspace file, not with nothing. One
    # run served three contracts, so no single `contract_hash` names what was
    # served -- but the file that named all three does, and each service
    # carries its own hash below.
    set_last_contract(str(args.workspace), "workspace")

    workspace = VirtualizationWorkspace(definition)
    addresses = workspace.start()
    try:
        if getattr(args, "json", False):
            _emit(
                {
                    "tool": "apiverity",
                    "command": "mock",
                    "workspace": definition.name,
                    "seed": definition.seed,
                    "services": [
                        {
                            "name": name,
                            "base_url": url,
                            "operations": len(_virtual(definition, name).service.operations),
                            "contract": _virtual(definition, name).spec_path,
                            "contract_hash": contract_hash(_virtual(definition, name).spec_path),
                            "faults": _fault_dict(definition, name),
                        }
                        for name, url in addresses.items()
                    ],
                },
                True,
            )
        else:
            print(f"workspace {definition.name!r}, seed {definition.seed}")
            width = max(len(name) for name in addresses)
            for name, url in addresses.items():
                faults = _fault_dict(definition, name)
                suffix = f"   faults: {faults}" if faults else ""
                print(f"  {name:<{width}}  {url}{suffix}")
            print("Ctrl+C to stop.")
        _block()
    except KeyboardInterrupt:  # pragma: no cover - interactive
        pass
    finally:
        workspace.stop()
    return EXIT_OK


def _virtual(definition: Any, name: str) -> Any:
    return next(vs for vs in definition.services if vs.name == name)


def _fault_dict(definition: Any, name: str) -> dict[str, Any]:
    """The faults configured for one service, without the seed.

    The seed is a property of the workspace and is reported once, beside its
    name. Repeating it per service would suggest it can differ, and it is
    exactly the thing that must not.
    """
    from dataclasses import asdict

    config = definition.faults.get(name)
    if config is None:
        return {}
    return {k: v for k, v in asdict(config).items() if k != "seed" and v not in (0, False, None)}


def _block() -> None:
    """Wait until interrupted.

    Separated so a test can drive `_serve_workspace` to the point where the
    addresses are printed and the servers are up, without hanging.
    """
    import threading

    threading.Event().wait()


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


def _preflight(workflow: Any, inputs: dict[str, Any], *, skip: bool = False) -> bool:
    """Check the manifest as a graph before a single request goes out.

    `stateful/graph.py` has existed since the engine did and no command called
    it -- which is how it came to be looking for `{{ name }}` while the engine
    substitutes `{name}`, for long enough that the four built-in templates were
    written to match the validator rather than the engine.

    An ERROR stops the run. `WF-MISSING-VAR` means a request would go out with
    a literal `{name}` in its path, and a workflow whose first step is wrong is
    a workflow that has already sent whatever came before it by the time
    anybody notices. Warnings print and the run continues: an uncleaned
    resource is worth knowing about and is not a reason to refuse.

    Variables supplied with `--input` count as available, so a manifest that
    declares none but templates one the caller passes is not reported.
    """
    from apiverity.stateful.graph import validate_workflow_graph

    if skip:
        return True
    declared = list(workflow.inputs)
    workflow.inputs = sorted(set(declared) | set(inputs))
    try:
        validation = validate_workflow_graph(workflow)
    finally:
        workflow.inputs = declared

    for issue in validation.issues:
        print(f"{issue.severity.value.lower()}: {issue.message}", file=sys.stderr)
    if validation.ok:
        return True
    print(
        "refusing to run: the manifest would send requests that cannot be "
        "completed. Pass --no-preflight to run it anyway.",
        file=sys.stderr,
    )
    return False


def _workflow_inputs(args: argparse.Namespace) -> tuple[dict[str, Any], str | None]:
    """`--input name=value` pairs, or the first one that is not a pair.

    Values stay strings. The manifest has no types for them -- `inputs` is a
    list of names -- so parsing `1` into an integer here would be this command
    deciding something the contract did not say.
    """
    out: dict[str, Any] = {}
    for raw in getattr(args, "input", None) or []:
        name, sep, value = str(raw).partition("=")
        if not sep or not name:
            return {}, str(raw)
        out[name] = value
    return out, None


def _read_arazzo_if_it_is_one(args: argparse.Namespace) -> Any:
    """An Arazzo description read into a runnable workflow, or None.

    Returns an exit code instead when the description names several workflows
    and the caller did not say which, or when the one it names does not exist.
    Guessing would run a different workflow from the one the operator meant,
    against whatever `--base-url` points at.
    """
    from pathlib import Path

    import yaml

    from apiverity.stateful.arazzo import from_arazzo, is_arazzo

    try:
        raw = yaml.safe_load(Path(args.manifest).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None  # load_workflow_manifest reports it in its own words
    if not is_arazzo(raw):
        return None

    result = from_arazzo(raw)
    wanted = getattr(args, "workflow_id", None)
    chosen = None
    for workflow in result.workflows:
        if wanted is None or workflow.name == wanted:
            chosen = workflow
            break
    if chosen is None:
        known = ", ".join(w.name for w in result.workflows) or "none"
        print(
            f"error: no workflow {wanted!r} in {args.manifest} (it declares: {known})",
            file=sys.stderr,
        )
        return EXIT_USAGE
    if wanted is None and len(result.workflows) > 1:
        print(
            f"note: {args.manifest} declares {len(result.workflows)} workflows; "
            f"running {chosen.name!r}. Pass --workflow-id to choose another.",
            file=sys.stderr,
        )

    # Printed to stderr so a `--json` run is still one JSON document on stdout,
    # and printed at all because a description that lost a retry, a goto or a
    # whole step imports and runs looking complete.
    print(f"note: {result.note}", file=sys.stderr)
    for entry in result.untranslated:
        if entry.workflow == chosen.name:
            print(f"  not carried: {entry}", file=sys.stderr)
    return chosen


def _to_arazzo(args: argparse.Namespace) -> int:
    """Write a manifest as an Arazzo 1.1.0 description.

    `--json` here selects the document's serialisation rather than wrapping a
    result: Arazzo is defined in both YAML and JSON, and the output of this
    flag is a specification document, not a run.
    """
    import json
    from pathlib import Path

    from apiverity.stateful.arazzo import to_arazzo
    from apiverity.stateful.engine import load_workflow_manifest

    spec = getattr(args, "spec", None)
    if not spec:
        print(
            "error: --to-arazzo requires --spec. An Arazzo description must name at "
            "least one source description, and the contract is also what turns this "
            "engine's `{user_id}` into the path parameter the contract declares.",
            file=sys.stderr,
        )
        return EXIT_USAGE

    service, _, _ = _load(spec)
    workflow = load_workflow_manifest(args.manifest)
    export = to_arazzo(
        workflow,
        source_name=_source_name(spec),
        source_url=spec,
        service=service,
    )
    text = (
        json.dumps(export.document, indent=2) + NL
        if getattr(args, "json", False)
        else export.to_yaml()
    )

    output = getattr(args, "output", None)
    if output:
        target = Path(output)
        if target.exists():
            print(f"error: {output} already exists; refusing to overwrite", file=sys.stderr)
            return EXIT_USAGE
        target.write_text(text, encoding="utf-8")
        print(f"wrote {output}")
    else:
        print(text, end="")

    for entry in export.untranslated:
        print(f"note: not carried into the description: {entry}", file=sys.stderr)
    for old, new in sorted(export.renamed.items()):
        print(f"note: renamed {old!r} to {new!r} for Arazzo's id charset", file=sys.stderr)
    return EXIT_OK


def _source_name(spec: str) -> str:
    """A Source Description name from a path: `[A-Za-z0-9_-]+`, non-empty."""
    import re
    from pathlib import Path

    stem = re.sub(r"[^A-Za-z0-9_\-]+", "-", Path(spec).stem).strip("-")
    return stem or "source"


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


def _graphql_schema(spec: str) -> Any:
    """Build a graphql-core schema, with a clear error when the extra is absent."""
    try:
        from graphql import build_schema
    except ImportError as exc:  # pragma: no cover - depends on the install
        raise ValueError(
            "GraphQL support requires the 'graphql' extra: pip install api-verity-lab[graphql]"
        ) from exc

    from pathlib import Path

    return build_schema(Path(spec).read_text(encoding="utf-8-sig"))


def _test_graphql(args: argparse.Namespace) -> int:
    """Run generated and persisted GraphQL operations against an endpoint."""
    from pathlib import Path

    from apiverity.specs.graphql.operations import build_cases as build_graphql_cases
    from apiverity.specs.graphql.operations import load_persisted_operations
    from apiverity.specs.graphql.runner import run_cases as run_graphql_cases

    try:
        schema = _graphql_schema(args.spec)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    cases = build_graphql_cases(
        schema, include_mutations=bool(getattr(args, "include_mutations", False))
    )
    for document in getattr(args, "operations", None) or []:
        path = Path(document)
        if not path.is_file():
            print(f"error: no such operations document: {document}", file=sys.stderr)
            return EXIT_USAGE
        try:
            cases.extend(load_persisted_operations(path.read_text(encoding="utf-8-sig"), path.name))
        except Exception as exc:
            print(f"error: could not parse {document}: {exc}", file=sys.stderr)
            return EXIT_USAGE

    set_last_target(args.base_url)
    try:
        results = run_graphql_cases(args.base_url, cases, timeout=args.timeout)
    except Exception as exc:
        print(f"error: target unreachable: {exc}", file=sys.stderr)
        return EXIT_UNREACHABLE

    failures = [r for r in results if r.status != "pass"]
    _emit(
        {
            "tool": "apiverity",
            "command": "test",
            "protocol": "graphql",
            "base_url": args.base_url,
            "total": len(results),
            "passed": len(results) - len(failures),
            "failed": len(failures),
            "results": [r.as_dict() for r in results],
        },
        args.json,
    )
    return EXIT_FINDINGS if failures else EXIT_OK
