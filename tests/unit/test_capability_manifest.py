"""The files that tell other people's tools what this one can do.

`docs/llms.txt` and `docs/capabilities.json` are the machine-readable answer to
"can api-verity-lab do this job". A hand-written capability list is a claim that
rots, and this project has already fixed that defect four times in its own
prose -- a competitive table that was never generated, a rule catalogue that
documented six rules the engine never had, two different page counts, a
"31-page product UI". The file that answers for other software is the last one
to leave to memory.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
_LLMS = _ROOT / "docs" / "llms.txt"
_CAPABILITIES = _ROOT / "docs" / "capabilities.json"


def _generator() -> Any:
    spec = importlib.util.spec_from_file_location(
        "generate_capability_manifest", _ROOT / "scripts" / "generate_capability_manifest.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _payload() -> dict[str, Any]:
    return json.loads(_CAPABILITIES.read_text(encoding="utf-8"))


def test_both_files_match_the_code() -> None:
    """`--check` runs in CI; failing here too is faster feedback."""
    module = _generator()
    assert _LLMS.read_text(encoding="utf-8") == module.render_llms()
    assert _CAPABILITIES.read_text(encoding="utf-8") == module.render_capabilities()


def test_every_command_the_cli_defines_is_listed() -> None:
    from apiverity.cli.main import build_parser

    parser = build_parser()
    assert parser._subparsers is not None
    defined = set(parser._subparsers._group_actions[0].choices)
    listed = {command["name"] for command in _payload()["commands"]}
    assert listed == defined


def test_every_command_has_a_summary() -> None:
    """A field that looks populated in a schema and says nothing is worse than none.

    It did: the help text lives on the parent's choice action, not on the
    subparser, so reading `subparser.description` produced an empty string for
    all thirty commands.
    """
    empty = [c["name"] for c in _payload()["commands"] if not c["summary"]]
    assert not empty, f"commands with no summary: {empty}"


def test_the_rule_ids_are_the_catalogue() -> None:
    from apiverity.rules.breaking import CATALOG

    payload = _payload()
    assert set(payload["rules"]["ids"]) == set(CATALOG)
    assert payload["rules"]["count"] == len(CATALOG)


def test_the_exit_codes_are_the_defined_ones() -> None:
    from apiverity.cli.commands.common import EXIT_FINDINGS, EXIT_OK, EXIT_USAGE

    codes = _payload()["exit_codes"]
    assert (codes["ok"], codes["findings"], codes["usage"]) == (EXIT_OK, EXIT_FINDINGS, EXIT_USAGE)


def test_formats_and_protocol_values_are_published_separately() -> None:
    """Two lists that answer different questions, each named for its question.

    Two plugins map onto `openapi`, so a set of protocol values reports six
    formats where seven exist; the enum reports eight because it carries `sse`
    and `websocket`, which are AsyncAPI channel kinds rather than documents
    anyone passes on a command line.
    """
    payload = _payload()
    assert len(payload["spec_plugins"]) == 7
    assert len(payload["protocol_values"]) == 8
    assert {entry["protocol"] for entry in payload["spec_plugins"]} < set(
        payload["protocol_values"]
    )


def test_the_format_count_in_prose_is_derived_not_typed() -> None:
    module = _generator()
    text = module.render_llms()
    words = {4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight"}
    assert f"across {words[module._format_count()]} formats" in text


def test_every_document_llms_txt_points_at_exists() -> None:
    """A reading list with a dead entry is worse than a shorter list."""
    module = _generator()
    missing = [path for _, path, _ in module._GUIDE if not (_ROOT / "docs" / path).is_file()]
    assert not missing, f"llms.txt points at documents that do not exist: {missing}"


def test_llms_txt_says_what_the_tool_will_not_do() -> None:
    """The half a model is least likely to infer, and most likely to assert."""
    text = _LLMS.read_text(encoding="utf-8")
    assert "## What it does not do" in text
    assert "never" in text
