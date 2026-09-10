"""Platform commands: server-db administration, plugins, rules, self-test."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from apiverity.cli.commands.common import (
    EXIT_INTERNAL,
    EXIT_OK,
    EXIT_USAGE,
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
        # catalogue is sixty-five rows and three more at the bottom is where a
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
    ("SEC-SCOPE-", "Security: authorization scope", "docs/check-rules.md"),
    ("SEC-AUTH-", "Security: authentication", "docs/check-rules.md"),
    ("SEC-SCHEME-", "Security: authentication", "docs/check-rules.md"),
    ("SEC-NO-AUTH-", "Security: authentication", "docs/check-rules.md"),
    ("SEC-APIKEY-", "Security: credentials", "docs/check-rules.md"),
    ("SEC-BASIC-", "Security: credentials", "docs/check-rules.md"),
    ("SEC-SECRET-", "Security: credentials", "docs/check-rules.md"),
    ("SEC-RESPONSE-CREDENTIAL", "Security: credentials", "docs/check-rules.md"),
    ("SEC-SENSITIVE-", "Security: credentials", "docs/check-rules.md"),
    ("SEC-ARRAY-", "Security: resource consumption", "docs/check-rules.md"),
    ("SEC-COLLECTION-", "Security: resource consumption", "docs/check-rules.md"),
    ("SEC-RATE-LIMIT-", "Security: resource consumption", "docs/check-rules.md"),
    ("SEC-", "Security: shape and transport", "docs/check-rules.md"),
    ("SEMANTIC-", "Behaviour", "docs/check-rules.md"),
    ("LIFECYCLE-", "Lifecycle", "docs/check-rules.md"),
    ("SEMVER-", "Semantic versioning", "docs/rule-catalog.md"),
    ("MCP-DRIFT-", "MCP runtime drift", "docs/mcp-drift.md"),
    ("MCP-CONF-", "MCP conformance", "docs/mcp-drift.md"),
    ("DRIFT-", "Runtime drift", "docs/capability-status.md"),
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
