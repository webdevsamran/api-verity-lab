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

    rules = [
        {"rule_id": rid, "severity": spec.severity.value, "description": spec.description}
        for rid, spec in sorted(CATALOG.items())
    ]
    _emit({"tool": "apiverity", "command": "rules", "count": len(rules), "rules": rules}, args.json)
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
            "operations": len(service.operations),
            "spec_findings": len(findings),
        },
        args.json,
    )
    return EXIT_OK if ok else EXIT_INTERNAL
