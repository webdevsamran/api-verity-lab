"""Platform commands: server-db administration, plugins, rules, self-test."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from apiverity.cli.commands.common import (
    EXIT_FINDINGS,
    EXIT_INTERNAL,
    EXIT_OK,
    EXIT_UNREACHABLE,
    EXIT_USAGE,
    NL,
    _emit,
    _load,
    active_profile,
    merged_severity_overrides,
)


def cmd_server_db(args: argparse.Namespace) -> int:
    """Administer a self-hosted server SQLite database.

    Actions: backup (consistent snapshot), restore (from a snapshot),
    export (org JSON snapshot without token hashes), import (snapshot as a
    new org).
    """
    from apiverity.server.store import Store

    action = args.action
    if action == "backup":
        store = Store(args.db)
        out = store.backup_to(args.output)
        _emit(
            {"tool": "apiverity", "command": "server-db", "action": "backup", "output": str(out)},
            args.json,
        )
        return EXIT_OK
    if action == "restore":
        store = Store.restore_from(args.db, target=args.output)
        orgs = store.conn.execute("SELECT COUNT(*) FROM orgs").fetchone()[0]
        store.close()
        _emit(
            {
                "tool": "apiverity",
                "command": "server-db",
                "action": "restore",
                "target": args.output,
                "orgs_restored": int(orgs),
            },
            args.json,
        )
        return EXIT_OK
    if action == "export":
        store = Store(args.db)
        snap = store.export_org(int(args.org_id))
        Path(args.output).write_text(json.dumps(snap, indent=2), encoding="utf-8")
        _emit(
            {
                "tool": "apiverity",
                "command": "server-db",
                "action": "export",
                "org_id": int(args.org_id),
                "output": args.output,
            },
            args.json,
        )
        return EXIT_OK
    if action == "import":
        store = Store(args.db)
        snap = json.loads(Path(args.input).read_text(encoding="utf-8"))
        new_org = store.import_org(snap)
        _emit(
            {
                "tool": "apiverity",
                "command": "server-db",
                "action": "import",
                "new_org_id": new_org,
            },
            args.json,
        )
        return EXIT_OK
    print(f"error: unknown action '{action}'", file=sys.stderr)
    return EXIT_USAGE


def _hmac_key(args: argparse.Namespace) -> bytes | None:
    """The seal key, from the environment and never from a flag.

    A key on the command line lands in shell history, in the CI log that echoes
    the command, and in the process table for every other user on the box. The
    variable name is the argument; the value never passes through argv.
    """
    import os

    name = getattr(args, "hmac_key_env", None)
    if not name:
        return None
    value = os.environ.get(str(name))
    if not value:
        raise KeyError(str(name))
    return value.encode("utf-8")


def cmd_audit(args: argparse.Namespace) -> int:
    """Export the hash-chained audit log, or check an exported one.

    `verify` reads the file and nothing else -- no database, no server, no
    network. That is the point of it: a verifier that needs the system under
    audit is a verifier the system under audit can lie to.
    """
    from apiverity.server.audit_export import verify_export

    try:
        key = _hmac_key(args)
    except KeyError as exc:
        print(
            f"error: ${exc.args[0]} is not set, so no seal key is available. "
            "Unset --hmac-key-env to export without a seal.",
            file=sys.stderr,
        )
        return EXIT_USAGE

    if args.action == "export":
        from apiverity.server.store import Store

        if not args.db or args.org_id is None:
            print("error: audit export needs --db and --org-id", file=sys.stderr)
            return EXIT_USAGE
        store = Store(args.db)
        try:
            document = store.audit_export(int(args.org_id), hmac_key=key)
        finally:
            store.close()
        if args.output:
            Path(args.output).write_text(
                json.dumps(document, indent=2, sort_keys=True), encoding="utf-8"
            )
        _emit(
            {
                "tool": "apiverity",
                "command": "audit",
                "action": "export",
                "org_id": int(args.org_id),
                "entry_count": document["entry_count"],
                "last_entry_hash": document["last_entry_hash"],
                "chain_valid": document["chain"]["valid"],
                "sealed": "seal" in document,
                "output": args.output,
            },
            args.json,
        )
        # A broken chain is the finding this command exists to surface. Exiting
        # 0 on one would mean the export succeeded and the log did not.
        return EXIT_OK if document["chain"]["valid"] else EXIT_FINDINGS

    if args.action == "verify":
        if not args.file:
            print("error: audit verify needs a path to an export document", file=sys.stderr)
            return EXIT_USAGE
        document = json.loads(Path(args.file).read_text(encoding="utf-8"))
        earlier = (
            json.loads(Path(args.against).read_text(encoding="utf-8")) if args.against else None
        )
        result = verify_export(document, hmac_key=key, against=earlier)
        _emit(
            {
                "tool": "apiverity",
                "command": "audit",
                "action": "verify",
                "file": args.file,
                **result.as_dict(),
            },
            args.json,
        )
        return EXIT_OK if result.ok else EXIT_FINDINGS

    print(f"error: unknown action '{args.action}'", file=sys.stderr)
    return EXIT_USAGE


def cmd_freeze(args: argparse.Namespace) -> int:
    """Stop releases, release them, or ask which it is.

    The kill-switch *procedure* an agent-governance auditor asks for, as a
    command somebody can run rather than a paragraph somebody wrote. Every
    transition lands in the server's hash-chained audit log with an actor and a
    reason, so the procedure is evidenced instead of asserted.

    `status` exits 1 while frozen, so a pipeline can gate on it directly, and
    3 when the server cannot be reached -- neither of which is 0, so a gate
    written against it fails closed. A kill switch a network partition disables
    is not one.
    """
    import os

    import httpx

    base = (args.server or os.environ.get("APIVERITY_SERVER") or "").rstrip("/")
    if not base:
        print(
            "error: --server (or APIVERITY_SERVER) must name the self-hosted server",
            file=sys.stderr,
        )
        return EXIT_USAGE

    token = os.environ.get(args.token_env or "APIVERITY_TOKEN", "")
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    try:
        if args.action == "status":
            response = httpx.get(f"{base}/v1/freeze", headers=headers, timeout=10.0)
        elif args.action == "on":
            reason = (args.reason or "").strip()
            if not reason:
                # An unexplained freeze is an outage whose cause nobody can
                # find, at the moment everybody is looking.
                print("error: freeze on needs --reason", file=sys.stderr)
                return EXIT_USAGE
            body = {"reason": reason}
            if args.review_by:
                body["review_by"] = args.review_by
            response = httpx.post(f"{base}/v1/freeze", headers=headers, json=body, timeout=10.0)
        elif args.action == "off":
            response = httpx.request(
                "DELETE",
                f"{base}/v1/freeze",
                headers=headers,
                json={"reason": args.reason or ""},
                timeout=10.0,
            )
        else:
            print(f"error: unknown action '{args.action}'", file=sys.stderr)
            return EXIT_USAGE
    except Exception as exc:
        print(f"error: could not reach {base}: {exc}", file=sys.stderr)
        return EXIT_UNREACHABLE

    if response.status_code >= 400:
        detail = ""
        try:
            detail = str(response.json().get("error", ""))
        except Exception:
            detail = response.text[:200]
        print(f"error: server returned {response.status_code}: {detail}", file=sys.stderr)
        return EXIT_USAGE if response.status_code < 500 else EXIT_INTERNAL

    state = response.json()
    _emit(
        {
            "tool": "apiverity",
            "command": "freeze",
            "action": args.action,
            "server": base,
            **{k: v for k, v in state.items() if k != "history"},
        },
        args.json,
    )
    # Frozen is not an error, it is a state a gate must act on -- which is
    # exactly what exit 1 means in this project's contract.
    return EXIT_FINDINGS if state.get("frozen") else EXIT_OK


def cmd_watch(args: argparse.Namespace) -> int:
    """Re-run a command whenever the files it names change.

    The watched paths are the command's own arguments, not a separate list.
    Two lists drift, and the failure is silent: you edit a file, nothing
    re-runs, and the output on screen is stale while looking current.
    """
    import time

    from apiverity.cli.commands.common import reset_provenance
    from apiverity.cli.watch import DEFAULT_INTERVAL, Change, expand, watch

    argv = list(args.argv or [])
    if argv and argv[0] == "--":
        argv = argv[1:]
    if not argv:
        print(
            "error: nothing to run. Usage: apiverity watch -- breaking old.yaml new.yaml",
            file=sys.stderr,
        )
        return EXIT_USAGE

    # The command's own file arguments, plus anything named with --path. A
    # token counts as a path when it exists or carries an extension, which
    # keeps the subcommand name itself ("breaking") out of the watch list
    # without needing to know what the subcommands are called.
    candidates = [
        token
        for token in argv
        if not token.startswith("-") and (Path(token).exists() or Path(token).suffix)
    ]
    watched, skipped = expand(list(args.path or []) + candidates)
    if not watched:
        print(
            "error: none of those arguments name a file to watch. Add --path to name a directory.",
            file=sys.stderr,
        )
        return EXIT_USAGE
    if skipped:
        # Reported, not applied quietly: a watcher silently ignoring the file
        # you are editing is worse than one that refuses.
        print(
            f"note: watching the first {len(watched)} files; {skipped} more were skipped. "
            "Narrow --path to include them.",
            file=sys.stderr,
        )

    print(f"watching {len(watched)} file(s); ctrl-c to stop", file=sys.stderr)

    from apiverity.cli.main import main as run_cli

    def run() -> int:
        code = run_cli(argv)
        print(f"-- exit {code}", file=sys.stderr)
        return code

    def announce(changes: list[Change]) -> None:
        stamp = time.strftime("%H:%M:%S")
        for change in changes:
            print(f"-- {stamp} {change}", file=sys.stderr)

    try:
        summary = watch(
            watched,
            run,
            interval=max(0.05, float(args.interval or DEFAULT_INTERVAL)),
            on_change=announce,
            reset=reset_provenance,
        )
    except KeyboardInterrupt:
        print("", file=sys.stderr)
        return EXIT_OK
    print(f"-- stopped after {summary.runs} run(s)", file=sys.stderr)
    return EXIT_OK


def _monitor_once(
    argv: list[str],
) -> tuple[list[dict[str, Any]] | None, str | None, int | None]:
    """Run one inner command; return its findings, why there are none, and how
    many things it measured.

    The inner command is this CLI, run in-process with `--json` so the result
    artifact comes back rather than being printed. Its exit code decides
    whether the run established anything:

    * 0 / 1  -- it ran; zero findings means zero findings.
    * 3      -- the target was unreachable. Zero findings means *unknown*.
    * 2 / 4  -- usage or internal error. Also unknown.

    That distinction is the whole reason this returns a reason rather than
    just a list. A monitor that mapped an unreachable target to an empty
    finding list would report every known finding as resolved at the exact
    moment the service went down.
    """
    import contextlib
    import io

    from apiverity.cli.commands.common import reset_provenance
    from apiverity.cli.main import main as run_cli
    from apiverity.runtime.monitor import measured_count

    inner = list(argv)
    if "--json" not in inner:
        inner.append("--json")

    reset_provenance()
    buffer = io.StringIO()
    try:
        with contextlib.redirect_stdout(buffer):
            code = run_cli(inner)
    except SystemExit as exc:  # argparse exits on a bad inner command line
        code = int(exc.code or 0)
    except Exception as exc:
        return None, f"the command raised {type(exc).__name__}: {exc}", None

    if code in (EXIT_UNREACHABLE, EXIT_USAGE, EXIT_INTERNAL):
        return None, f"`{' '.join(argv)}` exited {code}", None

    try:
        artifact = json.loads(buffer.getvalue())
    except ValueError:
        return None, "the command did not print a JSON result artifact", None
    findings = artifact.get("findings")
    if not isinstance(findings, list):
        return None, "the result artifact has no top-level `findings` array", None
    return (
        [f for f in findings if isinstance(f, dict)],
        None,
        measured_count(artifact),
    )


def cmd_monitor(args: argparse.Namespace) -> int:
    """Run a check on a schedule and report what changed since last time.

    Shaped like `watch`: everything after `--` is the command to run. Unlike
    `watch`, the trigger is a clock rather than a file, and the output is a
    diff against the previous run rather than the run's own report.
    """
    import time

    from apiverity.runtime.monitor import MonitorState, apply_run, report

    argv = list(args.argv or [])
    if argv and argv[0] == "--":
        argv = argv[1:]
    if not argv:
        print(
            "error: nothing to run. Usage: apiverity monitor --state s.json -- "
            "drift openapi.yaml --base-url https://staging",
            file=sys.stderr,
        )
        return EXIT_USAGE
    if argv[0] == "monitor":
        # Otherwise it recurses: each run spawns a monitor that spawns a
        # monitor, and the first symptom is a stack overflow at 3am.
        print("error: monitor cannot monitor itself", file=sys.stderr)
        return EXIT_USAGE

    try:
        state = MonitorState.load(args.state)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    target = " ".join(argv)
    if state.target and state.target != target:
        # Two commands sharing one state file diff against each other: every
        # finding of the one reads as resolved, every finding of the other as
        # new, on every alternate run. Refused rather than silently reset,
        # because a reset would report the whole current state as a baseline
        # and lose the history the file exists to hold.
        print(
            f"error: {args.state} holds the state of `{state.target}`, not "
            f"`{target}`. Use a separate --state file per command.",
            file=sys.stderr,
        )
        return EXIT_USAGE
    state.target = target

    rounds = max(1, int(args.runs or 1))
    interval = max(0.0, float(args.interval or 0.0))
    payload: dict[str, Any] = {}
    exit_code = EXIT_OK

    for index in range(rounds):
        if index:
            time.sleep(interval)
        findings, inconclusive, measured = _monitor_once(argv)
        transitions = apply_run(state, findings, inconclusive=inconclusive, measured=measured)
        payload = report(transitions, target=target)
        try:
            state.save(args.state)
        except OSError as exc:
            print(f"error: could not write {args.state}: {exc}", file=sys.stderr)
            return EXIT_INTERNAL
        if args.out:
            try:
                Path(args.out).write_text(
                    json.dumps(
                        {"tool": "apiverity", "command": "monitor", **payload},
                        indent=2,
                        default=str,
                    )
                    + NL,
                    encoding="utf-8",
                    newline=NL,
                )
            except OSError as exc:
                print(f"error: could not write {args.out}: {exc}", file=sys.stderr)
                return EXIT_INTERNAL
        if transitions.inconclusive:
            exit_code = EXIT_UNREACHABLE
        elif transitions.appeared:
            exit_code = EXIT_FINDINGS
        else:
            exit_code = EXIT_OK
        if rounds > 1:
            print(f"-- {time.strftime('%H:%M:%S')} {payload['summary']}", file=sys.stderr)

    _emit({"tool": "apiverity", "command": "monitor", **payload}, args.json)
    return exit_code


def cmd_plugins(args: argparse.Namespace) -> int:
    from apiverity.plugins.registry import list_entry_points

    groups = list_entry_points()
    _emit({"tool": "apiverity", "command": "plugins", "groups": groups}, args.json)
    return EXIT_OK


def cmd_rules(args: argparse.Namespace) -> int:
    from apiverity.rules.breaking import CATALOG
    from apiverity.rules.profiles import active_severity, summary

    if getattr(args, "profiles", False):
        # Listed on request rather than appended to every `rules` run: the
        # catalogue is seventy rows and three more at the bottom is where a
        # reader stops looking.
        profiles = [
            {
                "profile": name,
                "fail_on": threshold,
                "rules_raised": raised,
                "description": description,
            }
            for name, threshold, description, raised in summary()
        ]
        _emit(
            {
                "tool": "apiverity",
                "command": "rules",
                "count": len(profiles),
                "profiles": profiles,
            },
            args.json,
        )
        return EXIT_OK

    # Severities as *this run* would apply them, not as the catalogue declares
    # them. `apiverity rules` is where someone checks what a rule will do
    # before writing an override; printing the shipped severity while a profile
    # or a config quietly changes it makes this command the thing that misleads.
    profile = active_profile()
    overrides = merged_severity_overrides(None) or {}
    rules = [
        {
            "rule_id": rid,
            "severity": active_severity(rid, spec.severity.value, overrides),
            "catalog_severity": spec.severity.value,
            "description": spec.description,
        }
        for rid, spec in sorted(CATALOG.items())
    ]
    _emit(
        {
            "tool": "apiverity",
            "command": "rules",
            "count": len(rules),
            **({"profile": profile} if profile else {}),
            "rules": rules,
        },
        args.json,
    )
    return EXIT_OK


#: Rule-id prefix -> the group it belongs to and where its behaviour is decided.
#:
#: `explain` exists because a rule nobody understands gets suppressed rather
#: than fixed -- ESLint's whole adoption story. The catalogue already carries a
#: description; what it does not carry is *where to look next*, which is the
#: question someone reaching for --severity-override actually has.
_RULE_GUIDE: tuple[tuple[str, str, str], ...] = (
    ("BRK-MCP-", "MCP tool manifests", "docs/rule-catalog.md#mcp-tool-manifests"),
    ("BRK-OP-", "Operations and RPCs", "docs/rule-catalog.md#operations-and-rpcs"),
    ("BRK-RPC-", "Operations and RPCs", "docs/rule-catalog.md#operations-and-rpcs"),
    ("BRK-PARAM-", "Parameters", "docs/rule-catalog.md#parameters"),
    ("BRK-REQ-", "Request bodies and fields", "docs/rule-catalog.md#request-bodies-and-fields"),
    ("BRK-RESP-", "Responses", "docs/rule-catalog.md#responses"),
    ("BRK-HEADER-", "Responses", "docs/rule-catalog.md#responses"),
    ("BRK-CONSTRAINT-", "Schemas and constraints", "docs/rule-catalog.md#schemas-and-constraints"),
    ("BRK-ENUM-", "Schemas and constraints", "docs/rule-catalog.md#schemas-and-constraints"),
    ("BRK-MEDIA-", "Schemas and constraints", "docs/rule-catalog.md#schemas-and-constraints"),
    ("BRK-DEPENDENT-", "JSON Schema 2020-12", "docs/rule-catalog.md#json-schema-2020-12"),
    ("BRK-TUPLE-", "JSON Schema 2020-12", "docs/rule-catalog.md#json-schema-2020-12"),
    ("BRK-PATTERN-PROPERTIES-", "JSON Schema 2020-12", "docs/rule-catalog.md#json-schema-2020-12"),
    ("BRK-PROPERTY-NAMES-", "JSON Schema 2020-12", "docs/rule-catalog.md#json-schema-2020-12"),
    ("BRK-CONTAINS-", "JSON Schema 2020-12", "docs/rule-catalog.md#json-schema-2020-12"),
    ("BRK-CONDITIONAL-", "JSON Schema 2020-12", "docs/rule-catalog.md#json-schema-2020-12"),
    ("BRK-DEPRECATION-", "Lifecycle and security", "docs/rule-catalog.md#lifecycle-and-security"),
    ("BRK-SECURITY-", "Lifecycle and security", "docs/rule-catalog.md#lifecycle-and-security"),
    ("BRK-FIELD-", "Protocol buffers", "docs/rule-catalog.md"),
    ("BRK-ONEOF-", "Protocol buffers", "docs/rule-catalog.md"),
    ("BRK-RESERVATION-", "Protocol buffers", "docs/rule-catalog.md"),
    ("BRK-SOAP-", "SOAP bindings", "docs/spec-support.md"),
    ("SEC-SCOPE-", "Security: authorization scope", "docs/check-rules.md"),
    ("SEC-AUTH-", "Security: authentication", "docs/check-rules.md"),
    ("SEC-SCHEME-", "Security: authentication", "docs/check-rules.md"),
    ("SEC-NO-AUTH-", "Security: authentication", "docs/check-rules.md"),
    ("SEC-APIKEY-", "Security: credentials", "docs/check-rules.md"),
    ("SEC-BASIC-", "Security: credentials", "docs/check-rules.md"),
    ("SEC-DEP-", "Supply chain", "docs/supply-chain.md"),
    ("SEC-SECRET-", "Security: credentials", "docs/check-rules.md"),
    ("SEC-RESPONSE-CREDENTIAL", "Security: credentials", "docs/check-rules.md"),
    ("SEC-SENSITIVE-", "Security: credentials", "docs/check-rules.md"),
    ("SEC-ARRAY-", "Security: resource consumption", "docs/check-rules.md"),
    ("SEC-COLLECTION-", "Security: resource consumption", "docs/check-rules.md"),
    ("SEC-RATE-LIMIT-", "Security: resource consumption", "docs/check-rules.md"),
    ("SEC-ABUSE-", "Security: resource consumption", "docs/check-rules.md"),
    ("SEC-", "Security: shape and transport", "docs/check-rules.md"),
    ("SEMANTIC-", "Behaviour", "docs/check-rules.md"),
    ("SLO-", "Objectives", "docs/check-rules.md"),
    ("GOV-", "Governance", "docs/check-rules.md"),
    ("LINT-", "Lint", "docs/check-rules.md"),
    ("POLICY-RULE-CRASHED", "Governance", "docs/check-rules.md"),
    ("LIFECYCLE-", "Lifecycle", "docs/check-rules.md"),
    ("SEMVER-", "Semantic versioning", "docs/rule-catalog.md"),
    ("MCP-DRIFT-", "MCP runtime drift", "docs/mcp-drift.md"),
    ("MCP-CONF-", "MCP conformance", "docs/mcp-drift.md"),
    ("DRIFT-", "Runtime drift", "docs/capability-status.md"),
    ("AUTHZ-", "Authorization, between identities", "docs/authorization.md"),
    ("SDK-", "Generated SDKs", "docs/sdk-surface.md"),
    ("SUPPRESSION-", "The gate's escape hatch", "docs/ci.md#suppressions"),
    ("CONFIG-", "Project configuration", "docs/ci.md"),
    ("SPEC-", "Spec loading", "docs/spec-support.md"),
    ("MCP-", "MCP manifest loading", "docs/spec-support.md"),
)


def _guide_for(rule_id: str) -> tuple[str, str]:
    for prefix, group, where in _RULE_GUIDE:
        if rule_id.startswith(prefix):
            return group, where
    return "Other", "docs/rule-catalog.md"


def _did_you_mean(rule_id: str, known: list[str]) -> list[str]:
    """Nearest rule ids, so a typo does not end in a dead end."""
    import difflib

    upper = rule_id.upper()
    close = difflib.get_close_matches(upper, known, n=3, cutoff=0.5)
    substring = [r for r in known if upper and upper in r and r not in close]
    return (close + substring)[:5]


def cmd_explain(args: argparse.Namespace) -> int:
    """Explain one rule: what it means, why, and how to change its severity."""
    from apiverity.rules.alternatives import ALTERNATIVES
    from apiverity.rules.breaking import CATALOG
    from apiverity.rules.check_catalog import catalog as check_catalog

    rule_id = str(args.rule_id).strip().upper()
    spec = CATALOG.get(rule_id)
    if spec is None:
        # Twenty-two security rules were reachable, emitted by real runs, and
        # answered here with "no rule with id ..." -- in the command that exists
        # because a rule nobody understands gets suppressed rather than fixed.
        # The lifecycle rules joined the same table rather than starting a
        # second one.
        checks = check_catalog()
        security = checks.get(rule_id)
        if security is not None:
            group, where = _guide_for(rule_id)
            _emit(
                {
                    "tool": "apiverity",
                    "command": "explain",
                    "rule_id": rule_id,
                    "severity": security.severity.value,
                    "group": group,
                    "description": security.description,
                    "instead": security.instead,
                    "produced_by": security.produced_by,
                    "documentation": where,
                    "severity_override": f"--severity-override {rule_id}=INFO",
                },
                args.json,
            )
            return EXIT_OK
        # The semver rules live in `rules/semver.py` rather than the breaking
        # catalogue, and a reader looking one up does not care which module it
        # came from. Answering with the alternative alone beats "no such rule"
        # for an id the tool really does emit.
        alternative = ALTERNATIVES.get(rule_id)
        if alternative is not None:
            _emit(
                {
                    "tool": "apiverity",
                    "command": "explain",
                    "rule_id": rule_id,
                    "severity": "ERROR",
                    "group": "Semantic versioning",
                    "description": "The declared version does not match the changes.",
                    "instead": alternative,
                    "documentation": "docs/rule-catalog.md",
                },
                args.json,
            )
            return EXIT_OK
        suggestions = _did_you_mean(
            rule_id, sorted(CATALOG) + sorted(ALTERNATIVES) + sorted(checks)
        )
        print(f"error: no rule with id {rule_id!r}", file=sys.stderr)
        if suggestions:
            print("did you mean:", file=sys.stderr)
            for candidate in suggestions:
                print(f"  {candidate}", file=sys.stderr)
        else:
            print("run `apiverity rules` for the full catalog", file=sys.stderr)
        return EXIT_USAGE

    group, where = _guide_for(rule_id)
    _emit(
        {
            "tool": "apiverity",
            "command": "explain",
            "rule_id": spec.rule_id,
            "severity": spec.severity.value,
            "group": group,
            "description": spec.description,
            # What to ship instead. A gate that only says no gets switched off,
            # and the reader still wants the change they came here to make.
            "instead": ALTERNATIVES.get(rule_id, ""),
            "documentation": where,
            "override": f"apiverity breaking old new --severity-override {spec.rule_id}=WARN",
            "suppress": (
                "add the rule id to a suppression entry with a justification and an expiry; "
                "see apiverity/rules/suppressions.py"
            ),
        },
        args.json,
    )
    return EXIT_OK


def cmd_self_test(args: argparse.Namespace) -> int:
    """Run built-in sanity checks against bundled fixtures."""
    fixture = Path(__file__).parents[3] / "fixtures" / "apis" / "crud" / "openapi.yaml"
    if not fixture.exists():
        print("self-test: fixtures missing", file=sys.stderr)
        return EXIT_INTERNAL
    service, findings, plugin = _load(str(fixture))
    ok = plugin.protocol().value == "openapi" and len(service.operations) > 0
    _emit(
        {
            "tool": "apiverity",
            "command": "self-test",
            "ok": ok,
            # See governance.py: `operations` is the per-operation array in a
            # result-v1 artifact, not a count.
            "operation_count": len(service.operations),
            "spec_findings": len(findings),
        },
        args.json,
    )
    return EXIT_OK if ok else EXIT_INTERNAL


def cmd_notify(args: argparse.Namespace) -> int:
    """Route the findings in a result artifact to the teams they concern.

    Sends nothing without `--send`. A tool that posts to a team's channel as a
    side effect of being run has done something the person running it did not
    ask for -- the same reason `replay` and `--invoke-tool` are dry by default.
    """
    import yaml

    from apiverity.core.ownership import load_ownership
    from apiverity.reports.routing import load_routes, plan_notifications

    try:
        artifact = json.loads(Path(args.artifact).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"error: could not read result artifact '{args.artifact}': {exc}", file=sys.stderr)
        return EXIT_USAGE

    try:
        raw = yaml.safe_load(Path(args.routes).read_text(encoding="utf-8")) or {}
        routes = load_routes(raw.get("routes", raw))
    except (OSError, ValueError) as exc:
        print(f"error: could not read routes '{args.routes}': {exc}", file=sys.stderr)
        return EXIT_USAGE

    findings = artifact.get("findings")
    if not isinstance(findings, list):
        print(
            f"error: {args.artifact} has no top-level `findings` array. Produce it with "
            "`--json` from validate, breaking or drift",
            file=sys.stderr,
        )
        return EXIT_USAGE

    contract = str(artifact.get("new_spec") or artifact.get("spec") or "")
    owners: tuple[str, ...] = ()
    if contract:
        ownership = load_ownership(getattr(args, "root", ".") or ".")
        owners = ownership.owners_of(contract)

    consumers_by_operation: dict[str, list[str]] = {}
    teams_by_consumer: dict[str, str] = {}
    if getattr(args, "consumers", None):
        from apiverity.rules.consumers import RegistryError, load_registry

        try:
            registry = load_registry(args.consumers)
        except RegistryError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return EXIT_USAGE
        for consumer in registry.consumers:
            if consumer.team:
                teams_by_consumer[consumer.name] = consumer.team
            for operation in consumer.operations:
                consumers_by_operation.setdefault(operation, []).append(consumer.name)

    plan = plan_notifications(
        findings,
        routes,
        contract_path=contract,
        owners=owners,
        consumers_by_operation=consumers_by_operation,
        teams_by_consumer=teams_by_consumer,
    )

    delivered: list[dict[str, Any]] = []
    if getattr(args, "send", False) and plan.messages:
        import httpx

        for message in plan.messages:
            try:
                response = httpx.post(message.url, json=message.payload(), timeout=10.0)
                delivered.append(
                    {
                        "team": message.team,
                        "audience": message.audience,
                        "status": response.status_code,
                    }
                )
            except Exception as exc:
                # One unreachable webhook must not stop the others: the team
                # whose endpoint is down is not the team that needs telling
                # least.
                delivered.append(
                    {"team": message.team, "audience": message.audience, "error": str(exc)}
                )

    payload: dict[str, Any] = {
        "tool": "apiverity",
        "command": "notify",
        "artifact": args.artifact,
        "contract": contract,
        "owners": list(owners),
        "sent": bool(getattr(args, "send", False)),
        "messages": [
            {
                "team": m.team,
                "audience": m.audience,
                "kind": m.kind,
                "subject": m.subject,
                "body": m.body,
                "rule_ids": list(m.rule_ids),
            }
            for m in plan.messages
        ],
        # Both reported. A finding that reached nobody is the one that ends up
        # nowhere, and a routing layer that drops it silently is worse than the
        # shared channel it replaced.
        "unrouted": plan.unrouted,
        "unknown_teams": plan.unknown_teams,
        **({"delivered": delivered} if delivered else {}),
    }
    _emit(payload, args.json)

    if not args.json and not getattr(args, "send", False) and plan.messages:
        print(
            f"{NL}dry run: {len(plan.messages)} message(s) prepared, none sent. "
            "Add --send to deliver them.",
            file=sys.stderr,
        )
    return EXIT_OK
