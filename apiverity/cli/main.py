"""apiverity command-line interface.

All commands support ``--json`` and stable exit codes:
0 ok · 1 findings at/above threshold · 2 usage error ·
3 target unreachable · 4 internal error.

Command implementations live in ``apiverity.cli.commands``, grouped by
product lane; this module owns argument parsing and process exit codes.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from apiverity.cli.commands.artifacts import cmd_export, cmd_report, cmd_serve
from apiverity.cli.commands.common import EXIT_INTERNAL, EXIT_OK
from apiverity.cli.commands.governance import (
    cmd_breaking,
    cmd_changelog,
    cmd_diff,
    cmd_validate,
)
from apiverity.cli.commands.platform import (
    cmd_plugins,
    cmd_rules,
    cmd_self_test,
    cmd_server_db,
)
from apiverity.cli.commands.runtime import (
    cmd_baseline,
    cmd_drift,
    cmd_regression,
    cmd_replay,
)
from apiverity.cli.commands.testing import (
    cmd_coverage,
    cmd_mock,
    cmd_test,
    cmd_workflow,
)

__all__ = [
    "build_parser",
    "cmd_baseline",
    "cmd_breaking",
    "cmd_changelog",
    "cmd_coverage",
    "cmd_diff",
    "cmd_drift",
    "cmd_export",
    "cmd_mock",
    "cmd_plugins",
    "cmd_regression",
    "cmd_replay",
    "cmd_report",
    "cmd_rules",
    "cmd_self_test",
    "cmd_serve",
    "cmd_server_db",
    "cmd_test",
    "cmd_validate",
    "cmd_workflow",
    "main",
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="apiverity", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("validate")
    p.add_argument("spec")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_validate)
    p = sub.add_parser("diff")
    p.add_argument("old")
    p.add_argument("new")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_diff)
    p = sub.add_parser("breaking")
    p.add_argument("old")
    p.add_argument("new")
    p.add_argument("--check-semver", action="store_true")
    p.add_argument("--old-version")
    p.add_argument("--new-version")
    p.add_argument("--require-minor-for-warnings", action="store_true")
    p.add_argument("--severity-override", action="append")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_breaking)
    p = sub.add_parser("changelog")
    p.add_argument("old")
    p.add_argument("new")
    p.add_argument("--html", action="store_true")
    p.add_argument("--output")
    p.set_defaults(func=cmd_changelog)
    p = sub.add_parser("test")
    p.add_argument("spec")
    p.add_argument("--base-url", required=True)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--timeout", type=float, default=10.0)
    p.add_argument("--minimize", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_test)
    p = sub.add_parser("workflow")
    p.add_argument("manifest")
    p.add_argument("--base-url")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_workflow)
    p = sub.add_parser("mock")
    p.add_argument("spec")
    p.add_argument("--port", type=int, default=8090)
    p.add_argument("--latency-ms", type=int, default=0)
    p.add_argument("--force-status", type=int)
    p.add_argument("--malformed", action="store_true")
    p.add_argument("--rate-limit-after", type=int)
    p.set_defaults(func=cmd_mock)
    p = sub.add_parser("coverage")
    p.add_argument("spec")
    p.add_argument("--exercised", nargs="*")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_coverage)
    p = sub.add_parser("drift")
    p.add_argument("spec")
    p.add_argument("--base-url", required=True)
    p.add_argument("--timeout", type=float, default=10.0)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_drift)
    p = sub.add_parser("replay")
    p.add_argument("har")
    p.add_argument("--base-url", required=True)
    p.add_argument("--allow-host", action="append", required=True)
    p.add_argument("--execute", action="store_true")
    p.add_argument("--rate", type=float, default=10.0)
    p.add_argument("--i-know-this-is-production", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_replay)
    p = sub.add_parser("baseline")
    p.add_argument("spec")
    p.add_argument("--base-url", required=True)
    p.add_argument("-o", "--output", default="perf-baseline.json")
    p.add_argument("--iterations", type=int, default=20)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_baseline)
    p = sub.add_parser("regression")
    p.add_argument("spec")
    p.add_argument("--base-url", required=True)
    p.add_argument("--baseline")
    p.add_argument("--policy", action="append")
    p.add_argument("--tolerance", type=float, default=20.0)
    p.add_argument("--iterations", type=int, default=20)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_regression)
    p = sub.add_parser("report")
    p.add_argument("bundle")
    p.add_argument("--format", default="json")
    p.set_defaults(func=cmd_report)
    p = sub.add_parser("export")
    p.add_argument("--data", required=True)
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--spec")
    p.add_argument("--config")
    p.add_argument("--workflow")
    p.add_argument("--perf")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_export)
    p = sub.add_parser("serve")
    p.add_argument("directory")
    p.add_argument("--port", type=int, default=8080)
    p.set_defaults(func=cmd_serve)
    p = sub.add_parser("server-db", help="backup/restore/export/import a server database")
    p.add_argument("action", choices=["backup", "restore", "export", "import"])
    p.add_argument("--db", required=True, help="server SQLite database path")
    p.add_argument("-o", "--output", help="backup file / restored db / export JSON path")
    p.add_argument("--input", help="snapshot JSON to import")
    p.add_argument("--org-id", type=int, help="org id for export")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_server_db)
    p = sub.add_parser("plugins")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_plugins)
    p = sub.add_parser("rules")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_rules)
    p = sub.add_parser("self-test")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_self_test)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result: Any = args.func(args)
        return int(result)
    except SystemExit:
        raise
    except KeyboardInterrupt:
        return EXIT_OK
    except Exception as exc:
        print(f"internal error: {exc}", file=sys.stderr)
        return EXIT_INTERNAL


if __name__ == "__main__":
    sys.exit(main())
