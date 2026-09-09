"""The published `command` enum against the commands that actually write one.

Same defect as the `protocol` enum, found the same way. `schemas/result-v1.
schema.json` is the artifact contract this project publishes, and `export` and
`server-db` emitted `"command": "export"` and `"command": "server-db"` into
artifacts the enum did not allow -- so those two commands had been writing
schema-violating output for their whole lives, and nothing noticed because
`scripts/validate_result_artifacts.py` never ran them.

The bind is two-directional, because the two failures are different. An enum
missing a command means the tool emits artifacts it says are invalid. An enum
carrying a command the CLI does not define is a promise to consumers about
output that can never appear.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA = _ROOT / "schemas" / "result-v1.schema.json"

#: A payload names its command in one place and always the same way.
_EMITS = re.compile(r'"command":\s*"([a-z0-9-]+)"')


def _schema_commands() -> set[str]:
    doc = json.loads(_SCHEMA.read_text(encoding="utf-8"))
    return set(doc["properties"]["command"]["enum"])


def _emitted_commands() -> set[str]:
    found: set[str] = set()
    for path in (_ROOT / "apiverity").rglob("*.py"):
        found.update(_EMITS.findall(path.read_text(encoding="utf-8")))
    return found


def _cli_commands() -> set[str]:
    from apiverity.cli.main import build_parser

    parser = build_parser()
    assert parser._subparsers is not None
    return set(parser._subparsers._group_actions[0].choices)


def test_every_command_the_code_emits_is_allowed_by_the_schema() -> None:
    missing = sorted(_emitted_commands() - _schema_commands())
    assert not missing, (
        f"these commands write `command` values the published schema rejects: {missing}. "
        "Add them to schemas/result-v1.schema.json"
    )


def test_the_schema_promises_no_command_the_cli_does_not_define() -> None:
    invented = sorted(_schema_commands() - _cli_commands())
    assert not invented, (
        f"the schema allows commands that do not exist: {invented}. A consumer branching on "
        "one is branching on output that can never arrive"
    )


def test_the_scan_found_something_to_check() -> None:
    """A regex that matches nothing would make both tests pass silently."""
    assert len(_emitted_commands()) > 15


def test_the_enum_is_sorted() -> None:
    """It is read by people choosing what to branch on."""
    doc = json.loads(_SCHEMA.read_text(encoding="utf-8"))
    enum = doc["properties"]["command"]["enum"]
    assert enum == sorted(enum)
