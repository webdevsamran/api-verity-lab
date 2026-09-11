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

#: A result payload names its command in one place and always the same way:
#: immediately after `"tool": "apiverity"`.
#:
#: The pair, not `"command"` alone. `agents/skill.py` writes an `.mcp.json`
#: entry -- `{"command": "apiverity-mcp", "args": [...]}` -- which is a server
#: launch configuration and not a result artifact, and a scan for the bare key
#: reported it as a command the published enum rejects. Matching the pair drops
#: exactly that one string and nothing else: every one of the emitters this
#: file exists to police writes the two keys adjacent, and a test below asserts
#: the set found here is the set the CLI defines.
_EMITS = re.compile(r'"tool":\s*"apiverity",\s*"command":\s*"([a-z0-9-]+)"')


#: Commands that emit no result artifact of their own, and why.
#:
#: Named rather than absorbed into a loose floor: a command that stops emitting
#: an artifact should fail this file, and it cannot if the assertion is "more
#: than fifteen of them do".
_NO_ARTIFACT = frozenset(
    {
        # Re-runs another command and prints *that* command's output.
        "watch",
        # Renders an artifact into a document; the document is the output.
        "report",
        # Speaks LSP on stdout for the life of the process. Its output is a
        # stream of JSON-RPC frames, not one result artifact, and emitting one
        # would corrupt the stream it shares.
        "lsp",
    }
)


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


def test_the_scan_found_every_command_the_cli_defines() -> None:
    """A regex that matched nothing would make both tests pass silently.

    Bound to the parser rather than to a floor, because the scan was tightened
    to a key *pair* and a looser floor would not notice if the tightening had
    also dropped a real emitter.
    """
    missed = sorted(_cli_commands() - _emitted_commands() - _NO_ARTIFACT)
    assert not missed, (
        f"{missed} define a subcommand and the scan found no artifact for them. Either "
        "the pattern above stopped matching one, or they genuinely emit none -- in "
        "which case say so in _NO_ARTIFACT, with the reason"
    )


def test_the_enum_is_sorted() -> None:
    """It is read by people choosing what to branch on."""
    doc = json.loads(_SCHEMA.read_text(encoding="utf-8"))
    enum = doc["properties"]["command"]["enum"]
    assert enum == sorted(enum)
