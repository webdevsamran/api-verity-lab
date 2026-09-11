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
    NL,
    _emit,
    _load,
    _pair,
    apply_project_suppressions,
    config_setting,
    fail_on_threshold,
    merged_severity_overrides,
)


def cmd_validate(args: argparse.Namespace) -> int:
    service, findings, plugin = _load(args.spec)
    from apiverity.performance.slo import validate as validate_objectives
    from apiverity.security import run_security_checks

    sec = run_security_checks(service)
    # A malformed objective is worse than a missing one: `p95_ms: "250ms"`
    # looks declared, reads as declared in a review, and is compared against
    # nothing. Checked here because `validate` is where a contract gets read,
    # and a check nobody invokes is a check nobody has.
    sec.extend(validate_objectives(service))
    all_findings, suppressed = apply_project_suppressions(findings + sec)
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
        # What this contract was assembled from, when it was assembled from
        # more than itself. `contract_hash` covers the entry document only, so
        # without this an artifact for a four-file contract named one file --
        # provenance that does not name what it came from.
        **({"dependencies": service.dependencies} if service.dependencies else {}),
        **({"suppressions": suppressed} if suppressed else {}),
    }
    _emit(data, args.json)
    return _exit_for(all_findings)


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


def _config_default(args: argparse.Namespace, flag: str) -> bool:
    """A boolean flag: the command line if it was given, else the config.

    `store_true` cannot distinguish "not passed" from "passed false", so a
    config value can only ever turn one *on*. That is the right direction --
    a project declaring `check_semver: true` wants it everywhere, and nobody
    writes `check_semver: false` to defeat a flag they did not type.
    """
    return bool(getattr(args, flag, False)) or bool(config_setting(flag, False))


def _exit_for(findings: list[Any]) -> int:
    """Exit code for a set of findings, at the project's declared threshold.

    `fail_on` was a config key that reached no code: every command failed on
    ERROR and nothing else, so a team adopting the gate on an existing API had
    the documented way to say "report, do not block" and it did nothing.
    """
    floor = fail_on_threshold()
    if floor == "never":
        return EXIT_OK
    wanted = {"error": ("ERROR",), "warn": ("ERROR", "WARN")}.get(floor, ("ERROR",))
    hit = any(getattr(f.severity, "value", str(f.severity)) in wanted for f in findings)
    return EXIT_FINDINGS if hit else EXIT_OK


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
    # `.apiverity.yaml` under the command line. Its `severity_overrides` were
    # parsed, schema-checked and then applied to nothing at all -- so a project
    # that wrote them got the catalogue defaults and no indication of it.
    findings = evaluate_breaking(changes, merged_severity_overrides(overrides))
    # whole-contract HTTP compatibility + protocol-specific (GraphQL/gRPC) rules
    from apiverity.diff.compat import analyze_compat
    from apiverity.diff.protocol_compat import analyze_protocol_compat

    findings = findings + analyze_compat(old, new) + analyze_protocol_compat(old, new)

    # Wire-compatible changes that move a generated client's surface. Opt-in,
    # and narrowable: every rule in the family depends on a convention a
    # generator may or may not follow, and a run that asserted them all
    # unconditionally would be claiming things about tools this project has
    # not run.
    sdk_conventions: list[str] | None = None
    if getattr(args, "sdk", False):
        from apiverity.diff.sdk_surface import CONVENTIONS, analyze_sdk_surface

        sdk_conventions = sorted(getattr(args, "sdk_convention", None) or CONVENTIONS)
        try:
            findings = findings + analyze_sdk_surface(old, new, set(sdk_conventions))
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return EXIT_USAGE
    # Scoped suppressions with an owner, a reason and an expiry. The module
    # implementing them was imported by nothing, so a project keeping a
    # suppressions file had it read by no command.
    findings, suppressed = apply_project_suppressions(findings)

    if getattr(args, "suggest_fix", False):
        # The non-breaking route to the same destination, attached to the
        # finding that objected. A gate that only says no gets switched off,
        # and the reader still wants the change they came here to make.
        from apiverity.rules.alternatives import contextual

        by_change = {change.id: change for change in changes}
        annotated: list[Any] = []
        for finding in findings:
            instead = contextual(finding.rule_id, by_change.get(finding.change_id or ""))
            if instead is None:
                annotated.append(finding)
                continue
            updated = finding.model_copy(deep=True)
            updated.metadata = {**updated.metadata, "instead": instead}
            annotated.append(updated)
        findings = annotated

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

    if _config_default(args, "check_semver"):
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
    if _config_default(args, "suggest_version"):
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
            # What the SDK rules were allowed to assume. A run narrowed to two
            # conventions reports fewer findings than one that assumed six, and
            # an artifact that did not say which would read as the same run.
            **({"sdk_conventions": sdk_conventions} if sdk_conventions is not None else {}),
            "findings": findings,
            "errors": errors,
            **({"blast_radius": radius} if radius is not None else {}),
            **({"version_advice": advice} if advice is not None else {}),
            **(
                {"summary": {**summary.as_dict(), "markdown": summary.as_markdown()}}
                if summary is not None
                else {}
            ),
            # Reported, never merely dropped. A gate that silences findings on
            # the say-so of a file, without saying which, is a gate nobody can
            # audit.
            **({"suppressions": suppressed} if suppressed else {}),
        },
        args.json,
    )
    return _exit_for(findings)


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


def _looks_like_a_collection(path: str) -> bool:
    """Is this corpus a Postman collection rather than a HAR?

    Sniffed on content, not on the extension: both are `.json`, and a HAR
    named `collection.json` is a file somebody will hand this.
    """
    import json

    from apiverity.traffic import postman

    try:
        document = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return False
    return postman.is_collection(document)


def _note_the_collection(
    document: dict[str, Any], provenance: dict[str, Any], collection: Any
) -> None:
    """Record where the draft came from, and everything that did not survive.

    A draft missing a third of an API because those requests used form bodies
    looks like an API with a third fewer endpoints. The counts go in the
    artifact and the sentence goes in the document, because the two are read
    by different people.
    """
    info = document.setdefault("info", {})
    existing = str(info.get("description") or "").rstrip()
    info["description"] = f"{existing}\n\n{collection.note}".strip()
    info["x-apiverity-source"] = "postman-collection"
    provenance["source"] = "postman-collection"
    provenance["collection"] = collection.name
    provenance["requests_without_a_saved_response"] = collection.without_response
    if collection.skipped:
        provenance["skipped"] = collection.skipped
    if collection.unresolved:
        provenance["unresolved_variables"] = collection.unresolved


def cmd_infer(args: argparse.Namespace) -> int:
    """Draft a contract from recorded traffic, labelled as a draft."""
    import json

    import yaml

    from apiverity.specs.infer import infer
    from apiverity.traffic import postman
    from apiverity.traffic.redact import RedactionConfig, import_har

    # A Postman collection is the second most common answer to "we have no
    # contract", after "we have nothing". It is read into the same entries a
    # HAR produces so `infer` drafts from it with the same thresholds -- a
    # second inference path would be a second set of decisions about when a
    # field is required, and the two would disagree.
    collection: postman.Import | None = None
    try:
        if _looks_like_a_collection(args.corpus):
            collection = postman.read(args.corpus)
            entries = collection.entries
        else:
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
        title=getattr(args, "title", None) or (collection.name if collection else "Inferred API"),
        infer_enums=bool(getattr(args, "infer_enums", False)),
        request_noun="saved" if collection else "recorded",
    )
    if collection is not None:
        # The draft has to say what it came from. A collection is a set of
        # requests somebody saved, not traffic anybody observed -- and every
        # threshold `infer` applies means something weaker about examples than
        # about observations.
        _note_the_collection(document, provenance, collection)

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


def cmd_graph(args: argparse.Namespace) -> int:
    """Which contract in a tree reads whose schemas.

    The question a monorepo has and forty independent contract gates cannot
    answer: if I edit `shared/money.yaml`, whose build goes red?
    """
    from apiverity.cli.commands.project import discover_contracts_deep
    from apiverity.specs.graph import as_dict, build, mermaid
    from apiverity.specs.loader import detect_and_load

    root = Path(getattr(args, "root", ".")).resolve()
    if not root.is_dir():
        print(f"error: not a directory: {root}", file=sys.stderr)
        return EXIT_USAGE

    relative_paths = discover_contracts_deep(root, limit=int(getattr(args, "limit", 500)))
    if not relative_paths:
        # The same refusal `sweep` makes, for the same reason: an empty graph
        # and a graph of a tree with no contracts in it look identical.
        print(
            f"error: no contracts found under {root}; nothing was graphed, which is not "
            "the same as nothing depending on anything",
            file=sys.stderr,
        )
        return EXIT_USAGE

    contracts: dict[str, list[Any]] = {}
    unreadable: list[dict[str, str]] = []
    for relative in relative_paths:
        try:
            service, _, _ = detect_and_load(str(root / relative))
        except Exception as exc:
            # Named, never skipped. A contract that will not load has unknown
            # dependencies, and a graph that quietly omitted it would show a
            # shared schema with fewer dependents than it has.
            unreadable.append({"path": relative, "error": str(exc)[:200]})
            continue
        contracts[relative] = list(service.dependency_edges)

    graph = build(contracts)
    focus = getattr(args, "dependents_of", None)
    payload: dict[str, Any] = {
        "tool": "apiverity",
        "command": "graph",
        "root": str(root),
        "contracts": len(contracts),
        "unreadable": unreadable,
        **as_dict(graph),
    }
    if focus:
        payload["dependents_of"] = {
            "node": focus,
            "contracts": graph.dependents_of(focus),
            # A node nothing in the tree references and a node that is not in
            # the tree at all both produce an empty list.
            "known": focus in graph.nodes,
        }
    if getattr(args, "mermaid", False):
        payload["mermaid"] = mermaid(graph)

    _emit(payload, args.json)
    # Cycles and unreadable contracts are the two states a graph reports that
    # somebody has to act on.
    return EXIT_FINDINGS if (graph.cycles or unreadable) else EXIT_OK


def cmd_digest(args: argparse.Namespace) -> int:
    """One contract-health document per team, from a sweep.

    `sweep` answers a platform team's question in one document covering
    everything. This cuts the same data the other way, so each team receives
    only what it owns and can be sent it on a schedule.
    """
    import json
    import re

    from apiverity.reports.digest import as_dict, compare, render

    try:
        current = json.loads(Path(args.artifact).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        print(f"error: could not read sweep artifact '{args.artifact}': {exc}", file=sys.stderr)
        return EXIT_USAGE

    previous = None
    if getattr(args, "since", None):
        try:
            previous = json.loads(Path(args.since).read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as exc:
            print(f"error: could not read '{args.since}': {exc}", file=sys.stderr)
            return EXIT_USAGE

    try:
        digests = compare(current, previous)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    root = current.get("root")
    quiet = [d.team for d in digests.values() if d.quiet]
    speaking = [d for d in digests.values() if not d.quiet]

    written: list[str] = []
    if getattr(args, "out", None):
        directory = Path(args.out)
        directory.mkdir(parents=True, exist_ok=True)
        for digest in speaking:
            # A team name is `@org/platform` or an email; neither is a filename.
            stem = re.sub(r"[^A-Za-z0-9._-]+", "-", digest.team).strip("-") or "team"
            target = directory / f"{stem}.md"
            target.write_text(render(digest, root=root), encoding="utf-8", newline=NL)
            written.append(str(target))

    _emit(
        {
            "tool": "apiverity",
            "command": "digest",
            "root": root,
            "compared_to": str(args.since) if getattr(args, "since", None) else None,
            "teams": len(digests),
            # Named, not just counted: "four teams had nothing to report" is a
            # different claim from "four teams were not in the sweep at all".
            "quiet": sorted(quiet),
            "written": written,
            "digests": [as_dict(d) for d in speaking],
        },
        args.json,
    )
    return EXIT_FINDINGS if any(d.newly_failing for d in speaking) else EXIT_OK


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
