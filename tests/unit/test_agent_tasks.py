"""The hand-off to tooltrace-bench, held against tooltrace-bench's own schema.

An exporter into somebody else's format is the easiest thing in a project to
get plausibly wrong: the output looks right, nothing here reads it, and the
first person to find out is whoever runs the other tool. So the pack is
validated against the schema the sibling project publishes, vendored under
`schemas/vendor/` the way the OAI's Arazzo schema is.

Two things these tests pin that a reading would not catch:

- **The reference solution has to satisfy the assertion that grades it.** The
  solution comes from this project's `SchemaNode` model; the scorer is the raw
  `inputSchema` from the manifest. If the model drops a constraint the two
  disagree, and the exported benchmark ships a reference answer that fails its
  own check. That is a fidelity test on the model, run over fixtures.
- **A task nothing can fail is not exported.** `fixtures/mcp/tools_v1.json`
  contains one — `list_regions`, whose `inputSchema` is `{"type": "object",
  "properties": {}}` — so this is measured rather than asserted about a
  hypothetical.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from apiverity.agents.tasks import (
    ExportError,
    Pack,
    build,
    constrains_anything,
    readme,
    write,
)

_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA = _ROOT / "schemas" / "vendor" / "tooltrace-task-2026-09-11.schema.json"
_VENDOR_README = _ROOT / "schemas" / "vendor" / "README.md"
_CLEAN = _ROOT / "fixtures" / "mcp" / "tools_v1.json"
_POISONED = _ROOT / "fixtures" / "mcp" / "tools_poisoned.json"

_PROVENANCE = {
    "tool": "api-verity-lab",
    "tool_version": "0.0.0-test",
    "manifest": "fixtures/mcp/tools_v1.json",
    "contract_hash": "0" * 64,
    "verified": True,
}


def _loaded(path: Path) -> tuple[dict[str, Any], Any, list[Any]]:
    from apiverity.security import run_security_checks
    from apiverity.specs.loader import detect_and_load

    service, findings, _ = detect_and_load(str(path))
    findings = list(findings) + list(run_security_checks(service))
    return json.loads(path.read_text(encoding="utf-8")), service, findings


def _pack(path: Path = _CLEAN, **kwargs: Any) -> Pack:
    manifest, service, findings = _loaded(path)
    return build(
        manifest,
        findings,
        pack="demo",
        provenance=_PROVENANCE,
        service=service,
        **kwargs,
    )


# -- the format ----------------------------------------------------------


def test_every_task_validates_against_tooltrace_benchs_published_schema() -> None:
    from jsonschema import Draft202012Validator

    schema = json.loads(_SCHEMA.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    tasks = _pack().tasks
    assert tasks
    for task in tasks:
        errors = sorted(validator.iter_errors(task), key=lambda e: list(e.path))
        assert not errors, [f"{task['id']} {list(e.path)}: {e.message}" for e in errors]


def test_the_vendored_schema_is_recorded_in_the_directorys_table() -> None:
    """A schema copied in without a row is a file of unknown provenance, which
    is the thing that directory exists to prevent."""
    import hashlib

    table = _VENDOR_README.read_text(encoding="utf-8")
    assert _SCHEMA.name in table
    digest = hashlib.sha256(_SCHEMA.read_bytes()).hexdigest()
    assert digest in table, "the recorded SHA-256 is not this file's"


#: Fields that exist only in an unpushed working tree of the sibling project.
#: The published schema takes `additionalProperties: true`, so a task using one
#: still *validates* -- it simply does nothing, which is the worse failure: the
#: pack looks richer and the runner ignores the field.
UNPUBLISHED_FIELDS = ("tool_descriptions", "attachments")


def test_the_export_uses_no_field_only_an_unpushed_checkout_has() -> None:
    """`tool_descriptions` would be the obvious way to measure resistance to a
    poisoned description, and it is not in the published schema. Building on it
    would produce a pack that works against one working tree and silently does
    less everywhere else."""
    published = set(json.loads(_SCHEMA.read_text(encoding="utf-8"))["properties"])
    for field in UNPUBLISHED_FIELDS:
        assert field not in published, (
            f"`{field}` is published now -- re-fetch the vendored schema and reconsider "
            "whether the export should use it"
        )
    emitted: set[str] = set()
    for task in _pack().tasks:
        emitted.update(task)
    assert not emitted.intersection(UNPUBLISHED_FIELDS)


def test_only_built_in_scorers_are_named() -> None:
    """A task naming an assertion type that does not exist cannot run, and
    inventing one to make the export look richer would be exactly that."""
    from apiverity.agents.tasks import ASSERTIONS

    for task in _pack().tasks:
        for assertion in task["assertions"]:
            assert assertion["type"] in ASSERTIONS


# -- what the tasks measure ----------------------------------------------


def test_the_contract_is_the_scorer() -> None:
    """The whole idea. Not a hand-written expected value: a rubric somebody
    typed can disagree with the schema the service publishes, and then the
    benchmark measures the rubric."""
    manifest = json.loads(_CLEAN.read_text(encoding="utf-8"))
    declared = {t["name"]: t["inputSchema"] for t in manifest["tools"]}

    for task in _pack().tasks:
        name = task["metadata"]["source"]["mcp_tool"]
        graders = [a for a in task["assertions"] if a["type"] == "json_schema"]
        assert len(graders) == 1
        assert graders[0]["params"]["schema"] == declared[name]


def test_the_reference_solution_satisfies_the_assertion_that_grades_it() -> None:
    """A fidelity check on the model, not on the exporter. The solution is
    generated from this project's `SchemaNode`; the scorer is the raw schema
    from the manifest. A constraint the model drops shows up here as a
    reference answer that fails its own check."""
    from jsonschema import Draft202012Validator

    for task in _pack().tasks:
        script = task["metadata"]["scripted_script"]
        answer = json.loads(script[0]["args"]["content"])
        schema = next(a for a in task["assertions"] if a["type"] == "json_schema")["params"][
            "schema"
        ]
        errors = list(Draft202012Validator(schema).iter_errors(answer))
        assert not errors, f"{task['id']}: {[e.message for e in errors]}"


def test_a_tool_whose_schema_constrains_nothing_is_skipped() -> None:
    """`list_regions` declares `{"type": "object", "properties": {}}`. Every
    submission validates against that, so a task graded by it cannot be failed
    and a pack of them reports a score that means nothing."""
    skipped = {s.name: s.reason for s in _pack().skipped}
    assert "list_regions" in skipped
    assert "constrains nothing" in skipped["list_regions"]


@pytest.mark.parametrize(
    ("schema", "gradeable"),
    [
        ({"type": "object", "properties": {}}, False),
        ({"type": "object"}, False),
        ({"type": "object", "required": ["a"]}, True),
        ({"type": "object", "additionalProperties": False}, True),
        ({"type": "object", "properties": {"a": {"type": "string"}}}, True),
        # A declared property with an empty schema constrains nothing either.
        ({"type": "object", "properties": {"a": {}}}, False),
        ({"type": "object", "minProperties": 1}, True),
        ("not a schema", False),
    ],
)
def test_what_counts_as_a_gradeable_schema(schema: Any, gradeable: bool) -> None:
    assert constrains_anything(schema) is gradeable


def test_a_poisoned_description_is_not_turned_into_an_instruction() -> None:
    """You cannot ask an agent to follow a description that is an injection and
    then score it for compliance: the correct behaviour is to refuse, and this
    task shape would mark that wrong."""
    manifest, service, findings = _loaded(_POISONED)
    pack = build(manifest, findings, pack="p", provenance=_PROVENANCE, service=service)
    skipped = {s.name: s.reason for s in pack.skipped}
    assert "get_weather" in skipped
    assert "MCP-POISON-CREDENTIAL-PATH" in skipped["get_weather"]
    assert "get_weather" not in {t["metadata"]["source"]["mcp_tool"] for t in pack.tasks}


def test_include_flagged_exports_them_with_the_rule_attached() -> None:
    manifest, service, findings = _loaded(_POISONED)
    pack = build(
        manifest,
        findings,
        pack="p",
        provenance=_PROVENANCE,
        service=service,
        include_flagged=True,
    )
    flagged = [t for t in pack.tasks if t["metadata"]["source"]["mcp_tool"] == "get_weather"]
    assert flagged, "--include-flagged exported nothing it was asked for"
    assert "MCP-POISON-CREDENTIAL-PATH" in flagged[0]["metadata"]["source"]["poisoning_rules"]
    assert "flagged-description" in flagged[0]["tags"]


def test_a_manifest_with_no_gradeable_tool_is_refused() -> None:
    """Writing an empty pack would be writing a benchmark with no measurement
    in it, and the exit code would say it worked."""
    manifest = {"tools": [{"name": "ping", "inputSchema": {"type": "object", "properties": {}}}]}
    with pytest.raises(ExportError, match="can be failed"):
        build(manifest, [], pack="p", provenance=_PROVENANCE)


def test_the_provenance_names_the_generating_tool_not_the_mcp_one() -> None:
    """`dict(provenance, tool=name)` overwrote `tool: api-verity-lab` with the
    MCP tool's name, so every pack claimed it had been generated by whichever
    tool the task was about."""
    for task in _pack().tasks:
        source = task["metadata"]["source"]
        assert source["tool"] == "api-verity-lab"
        assert source["mcp_tool"] != "api-verity-lab"


# -- reproducibility and writing ------------------------------------------


def test_the_export_is_reproducible() -> None:
    """Seeded from the tool's name. A pack that changed on every run could not
    be committed, reviewed or diffed."""
    assert _pack().tasks == _pack().tasks


def test_the_pack_is_written_as_yaml_with_a_readme(tmp_path: Path) -> None:
    pack = _pack()
    written = write(pack, tmp_path, _PROVENANCE)
    assert (tmp_path / "README.md") in written
    for path in written:
        if path.suffix == ".yaml":
            assert yaml.safe_load(path.read_text(encoding="utf-8"))["id"].startswith("demo/")


def test_the_readme_says_what_was_left_out() -> None:
    """A reader comparing tool count to task count otherwise assumes the
    difference was a bug."""
    pack = _pack()
    text = readme(pack, _PROVENANCE)
    assert "list_regions" in text
    assert _PROVENANCE["contract_hash"] in text


def test_the_embedded_manifest_is_the_one_that_was_checked(tmp_path: Path) -> None:
    """The agent reads the contract, not a paraphrase of it. A workspace copy
    that had been rewritten would be grading against a different document than
    the one this project verified."""
    from apiverity.agents.tasks import MANIFEST

    original = json.loads(_CLEAN.read_text(encoding="utf-8"))
    for task in _pack().tasks:
        assert json.loads(task["starting_workspace"][MANIFEST]) == original


# -- the command ----------------------------------------------------------


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "apiverity.cli.main", "agent-tasks", *args],
        capture_output=True,
        text=True,
        cwd=_ROOT,
    )


def test_the_command_writes_a_pack(tmp_path: Path) -> None:
    result = _run(str(_CLEAN), "-o", str(tmp_path / "pack"), "--json")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["task_count"] == 2
    assert sorted(p.name for p in (tmp_path / "pack").iterdir()) == [
        "README.md",
        "cancel_order.yaml",
        "search_orders.yaml",
    ]


def test_a_surface_with_errors_is_refused_by_default(tmp_path: Path) -> None:
    """A pack built from a manifest this tool reports errors on benchmarks
    agents against a contract we say is broken, and every failure it reports is
    then ambiguous between the agent and the manifest."""
    result = _run(str(_POISONED), "-o", str(tmp_path / "pack"))
    assert result.returncode == 1
    assert "--allow-findings" in result.stderr
    assert not (tmp_path / "pack").exists()


def test_allow_findings_exports_and_carries_them(tmp_path: Path) -> None:
    result = _run(str(_POISONED), "-o", str(tmp_path / "pack"), "--allow-findings", "--json")
    assert result.returncode == 0, result.stderr
    text = (tmp_path / "pack" / "README.md").read_text(encoding="utf-8")
    assert "did not pass" in text
    assert "MCP-POISON-CREDENTIAL-PATH" in text


def test_a_contract_that_is_not_an_mcp_manifest_says_so(tmp_path: Path) -> None:
    result = _run("fixtures/apis/crud/openapi.yaml", "-o", str(tmp_path / "pack"))
    assert result.returncode == 2
    assert "openapi contract" in result.stderr
    assert "MCP tool manifests" in result.stderr
