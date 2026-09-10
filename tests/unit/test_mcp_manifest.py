"""MCP tool manifests as a contract format.

Two halves. The first is that the shared engine does the work: an MCP manifest
compiles into the same `Service` as every other format, so a removed tool, a
newly-required argument and a narrowed enum fire the *existing* rules with no
MCP-specific code involved. Those assertions are the concrete evidence for the
"one contract model, one rule engine" claim, and they would be the first thing
to break if a future change special-cased MCP somewhere it should not.

The second is the handful of things only an MCP manifest has -- the four
annotation hints, the presence of an outputSchema, pagination -- and the
volatile fields that must never reach the diff at all.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from apiverity.core.model import OperationKind, Protocol
from apiverity.diff.engine import diff_services
from apiverity.rules.breaking import CATALOG, evaluate_breaking
from apiverity.specs import UnrecognizedSpecError
from apiverity.specs.loader import detect_and_load
from apiverity.specs.mcp import load_manifest
from apiverity.specs.mcp.manifest import ManifestShapeError, unwrap_manifest

_ROOT = Path(__file__).resolve().parents[2]
_FIXTURES = _ROOT / "fixtures" / "mcp"


def _load(name: str):
    service, findings, plugin = detect_and_load(str(_FIXTURES / name))
    return service, findings, plugin


def _tool(**overrides: Any) -> dict[str, Any]:
    tool = {
        "name": "search",
        "description": "Find things.",
        "inputSchema": {
            "type": "object",
            "required": ["query"],
            "properties": {"query": {"type": "string"}},
        },
    }
    tool.update(overrides)
    return tool


def _manifest(*tools: dict[str, Any], **envelope: Any) -> dict[str, Any]:
    return {"tools": list(tools), **envelope}


def _rules(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    before, _ = load_manifest(old)
    after, _ = load_manifest(new)
    return [f.rule_id for f in evaluate_breaking(diff_services(before, after))]


# --------------------------------------------------------------- recognition


def test_a_saved_tools_list_is_recognised_as_a_contract() -> None:
    service, findings, plugin = _load("tools_v1.json")
    assert plugin.protocol() is Protocol.MCP
    assert service.protocol is Protocol.MCP
    assert [op.rpc_name for op in service.operations] == [
        "search_orders",
        "cancel_order",
        "list_regions",
    ]
    assert not [f for f in findings if f.severity.value == "ERROR"]


@pytest.mark.parametrize("name", ["not-a-manifest.json", "server-config.json"])
def test_json_that_is_not_a_manifest_is_unrecognised_not_broken(name: str) -> None:
    """`UnrecognizedSpecError` is deliberately distinct from a parse failure.

    A repository is full of JSON that is not a contract. A `package.json` that
    reported as a *malformed* MCP manifest would fail the contract gate on
    every pull request that touched it; one that is simply not recognised is
    skipped, which is the correct response.
    """
    with pytest.raises(UnrecognizedSpecError) as caught:
        detect_and_load(str(_FIXTURES / name))
    assert "mcp" in caught.value.tried


def test_a_server_config_is_not_a_tool_manifest() -> None:
    """`{"mcpServers": ...}` says how to *launch* a server, not what it exposes."""
    with pytest.raises(ManifestShapeError):
        unwrap_manifest(json.loads((_FIXTURES / "server-config.json").read_text(encoding="utf-8")))


def test_a_bare_tools_array_of_strings_is_refused() -> None:
    """An agent config listing tool names must not be mistaken for a contract."""
    from apiverity.specs.mcp.manifest import McpSpecPlugin

    payload = json.dumps({"tools": ["alpha", "beta"]}).encode()
    assert McpSpecPlugin().detect("agent.json", payload) is False


def test_a_jsonrpc_response_is_unwrapped() -> None:
    """What teeing a stdio session produces."""
    payload = {"jsonrpc": "2.0", "id": 1, "result": {"tools": [_tool()]}}
    service, _ = load_manifest(payload)
    assert [op.rpc_name for op in service.operations] == ["search"]


# ------------------------------------------------------------------ identity


def test_the_tool_name_is_the_whole_identity() -> None:
    """Not `service_name.rpc_name`, which would fold in the manifest label.

    The label comes from the filename, so without its own branch in
    `Operation.key` two dumps of the same server saved under different names
    would diff as a total replacement.
    """
    a, _ = load_manifest(_manifest(_tool()), label="from-staging")
    b, _ = load_manifest(_manifest(_tool()), label="from-prod")
    assert a.operations[0].key == "tool search"
    assert a.operation_keys() == b.operation_keys()
    assert diff_services(a, b) == []


def test_operations_are_tagged_as_mcp_tools() -> None:
    service, _ = load_manifest(_manifest(_tool()))
    assert service.operations[0].kind is OperationKind.MCP_TOOL


# ------------------------------------------------------- the shared engine
#
# The point of the whole design: no MCP-specific rule code is involved below.


def test_a_removed_tool_fires_the_shared_removal_rule() -> None:
    fired = _rules(_manifest(_tool(), _tool(name="other")), _manifest(_tool()))
    assert "BRK-RPC-REMOVED" in fired


def test_a_newly_required_argument_fires_the_shared_rule() -> None:
    """A tool's `inputSchema` argument is a body field, not a parameter.

    This asserted `BRK-PARAM-ADDED-REQUIRED` while the rules that name a body
    field were reachable from no input at all -- so it was pinning the wrong
    answer rather than catching it. An agent author reading "a request
    parameter was added" about a tool argument has nowhere to go with that.
    """
    widened = _tool(
        inputSchema={
            "type": "object",
            "required": ["query", "tenant"],
            "properties": {"query": {"type": "string"}, "tenant": {"type": "string"}},
        }
    )
    assert "BRK-REQ-FIELD-ADDED-REQUIRED" in _rules(_manifest(_tool()), _manifest(widened))


def test_a_narrowed_enum_fires_the_shared_rule() -> None:
    def with_enum(values: list[str]) -> dict[str, Any]:
        return _tool(
            inputSchema={
                "type": "object",
                "properties": {"mode": {"type": "string", "enum": values}},
            }
        )

    fired = _rules(_manifest(with_enum(["a", "b"])), _manifest(with_enum(["a"])))
    assert "BRK-ENUM-NARROWED-REQUEST" in fired


def test_a_tightened_constraint_fires_the_shared_rule() -> None:
    def with_max(value: int) -> dict[str, Any]:
        return _tool(
            inputSchema={
                "type": "object",
                "properties": {"limit": {"type": "integer", "maximum": value}},
            }
        )

    assert "BRK-CONSTRAINT-TIGHTENED" in _rules(_manifest(with_max(100)), _manifest(with_max(10)))


def test_a_removed_output_field_fires_the_shared_response_rule() -> None:
    def with_out(props: dict[str, Any], required: list[str]) -> dict[str, Any]:
        return _tool(outputSchema={"type": "object", "required": required, "properties": props})

    fired = _rules(
        _manifest(with_out({"a": {"type": "string"}, "b": {"type": "string"}}, ["a", "b"])),
        _manifest(with_out({"a": {"type": "string"}}, ["a"])),
    )
    assert "BRK-RESP-FIELD-REMOVED" in fired


# ------------------------------------------------------- MCP-specific rules


@pytest.mark.parametrize(
    ("hint", "before", "after", "expected"),
    [
        ("readOnlyHint", True, False, "BRK-MCP-READONLY-HINT-CLEARED"),
        ("readOnlyHint", None, True, "BRK-MCP-READONLY-HINT-SET"),
        ("destructiveHint", None, True, "BRK-MCP-DESTRUCTIVE-HINT-SET"),
        ("destructiveHint", True, None, "BRK-MCP-DESTRUCTIVE-HINT-CLEARED"),
        ("idempotentHint", True, False, "BRK-MCP-IDEMPOTENT-HINT-CLEARED"),
        ("idempotentHint", False, True, "BRK-MCP-IDEMPOTENT-HINT-SET"),
        ("openWorldHint", False, True, "BRK-MCP-OPENWORLD-HINT-CHANGED"),
        ("openWorldHint", None, False, "BRK-MCP-ANNOTATION-DECLARATION-CHANGED"),
    ],
)
def test_annotation_transitions_are_classified(
    hint: str, before: bool | None, after: bool | None, expected: str
) -> None:
    def annotated(value: bool | None) -> dict[str, Any]:
        return _tool(annotations={} if value is None else {hint: value})

    assert expected in _rules(_manifest(annotated(before)), _manifest(annotated(after)))


def test_annotation_rules_are_not_errors() -> None:
    """The specification says clients MUST treat annotations as untrusted.

    A rule cannot rest the catalogue's highest severity on a field the protocol
    itself declines to trust -- which is the same reason `idempotentHint` is
    not mapped onto `Operation.idempotent`. `--severity-override` is one flag
    away for anyone treating a manifest as supply chain.
    """
    hint_rules = [r for r in CATALOG if "HINT" in r]
    assert hint_rules, "the annotation rules disappeared"
    for rule_id in hint_rules:
        assert CATALOG[rule_id].severity.value != "ERROR", (
            f"{rule_id} is ERROR, but it rests on an annotation the spec says is untrusted"
        )


def test_a_description_edit_is_reported_for_mcp_and_not_for_http() -> None:
    """For an MCP tool the description is the model's routing input.

    A silent edit is the documented tool-poisoning vector (OWASP MCP03), so it
    is a WARN finding here -- while the same edit on an OpenAPI operation stays
    the INFO-level documentation change it has always been.
    """
    fired = _rules(_manifest(_tool()), _manifest(_tool(description="Now does something else.")))
    assert "BRK-MCP-TOOL-DESCRIPTION-CHANGED" in fired
    assert CATALOG["BRK-MCP-TOOL-DESCRIPTION-CHANGED"].severity.value == "WARN"

    openapi_old, _, _ = detect_and_load(str(_ROOT / "fixtures/apis/versioned/v1.yaml"))
    openapi_new, _, _ = detect_and_load(str(_ROOT / "fixtures/apis/versioned/v2.yaml"))
    http_rules = {f.rule_id for f in evaluate_breaking(diff_services(openapi_old, openapi_new))}
    assert "BRK-MCP-TOOL-DESCRIPTION-CHANGED" not in http_rules


def test_dropping_an_output_schema_is_breaking_and_adding_one_is_not() -> None:
    with_schema = _tool(outputSchema={"type": "object", "properties": {"a": {"type": "string"}}})
    assert "BRK-MCP-OUTPUT-SCHEMA-REMOVED" in _rules(_manifest(with_schema), _manifest(_tool()))
    assert "BRK-MCP-OUTPUT-SCHEMA-ADDED" in _rules(_manifest(_tool()), _manifest(with_schema))
    assert CATALOG["BRK-MCP-OUTPUT-SCHEMA-REMOVED"].severity.value == "ERROR"


def test_a_rename_is_suspected_but_never_replaces_the_removal() -> None:
    """A manifest carries no identity but the name.

    Remove-plus-add and rename are genuinely indistinguishable, so the
    suspicion is context attached to a removal that is still reported -- not a
    downgrade of it.
    """
    fired = _rules(_manifest(_tool(name="old_name")), _manifest(_tool(name="new_name")))
    assert "BRK-MCP-TOOL-RENAME-SUSPECTED" in fired
    assert "BRK-RPC-REMOVED" in fired


def test_two_out_two_in_raises_no_rename_suspicion() -> None:
    """Pairing them would be a guess."""
    before = _manifest(_tool(name="a"), _tool(name="b"))
    after = _manifest(_tool(name="c"), _tool(name="d"))
    assert "BRK-MCP-TOOL-RENAME-SUSPECTED" not in _rules(before, after)


def test_a_truncated_manifest_is_an_error_in_the_diff() -> None:
    """Every tool past the page boundary would otherwise read as removed."""
    page_one = _manifest(_tool(), nextCursor="page-2", resultType="complete")
    assert "BRK-MCP-MANIFEST-TRUNCATED" in _rules(page_one, _manifest(_tool()))


# ------------------------------------------------------------ volatile fields


def test_cache_and_pagination_state_never_reaches_the_diff() -> None:
    """`ttlMs`, `cacheScope` and `nextCursor` differ run to run.

    Excluded by whitelist -- the loader copies only what it models -- rather
    than by a list of fields to drop, which would start leaking the moment the
    next revision adds another cache hint.
    """
    a = _manifest(_tool(), ttlMs=60000, cacheScope="public", resultType="complete")
    b = _manifest(_tool(), ttlMs=15, cacheScope="private", resultType="complete")
    before, _ = load_manifest(a)
    after, _ = load_manifest(b)
    assert diff_services(before, after) == []


def test_a_legacy_dump_and_a_modern_envelope_carrying_the_same_tools_are_equal() -> None:
    bare, _ = load_manifest(_manifest(_tool()))
    enveloped, _ = load_manifest(
        _manifest(_tool(), ttlMs=1, cacheScope="public", resultType="complete")
    )
    assert diff_services(bare, enveloped) == []


# ------------------------------------------------------------------- era


def test_a_bare_dump_never_claims_to_be_legacy() -> None:
    """It is byte-identical from either era, so absence proves nothing."""
    service, findings = load_manifest(_manifest(_tool()))
    assert service.bindings["mcp"]["era"] == "unknown"
    assert "MCP-PROTOCOL-ERA-UNOBSERVED" in {f.rule_id for f in findings}


def test_a_recorded_protocol_version_establishes_the_era() -> None:
    modern, _ = load_manifest(
        _manifest(_tool(), _meta={"io.modelcontextprotocol/protocolVersion": "2026-07-28"})
    )
    legacy, _ = load_manifest(
        _manifest(_tool(), _meta={"io.modelcontextprotocol/protocolVersion": "2025-06-18"})
    )
    assert modern.bindings["mcp"]["era"] == "modern"
    assert legacy.bindings["mcp"]["era"] == "legacy"


# ---------------------------------------------------------------- findings


def test_a_tool_without_an_input_schema_is_a_broken_contract() -> None:
    """Recognised, and reported -- not skipped. The spec makes inputSchema mandatory."""
    _, findings = load_manifest(_manifest({"name": "bare"}))
    assert "MCP-INPUT-SCHEMA-MISSING" in {f.rule_id for f in findings}


def test_duplicate_tool_names_are_an_error() -> None:
    _, findings = load_manifest(_manifest(_tool(), _tool()))
    assert "MCP-TOOL-DUPLICATE" in {f.rule_id for f in findings}


def test_unmodelled_schema_keywords_are_reported_rather_than_dropped() -> None:
    """Silently dropping them would assert a simpler schema than the document has.

    `unevaluatedProperties` is one of the four that remain: its meaning depends
    on which other keywords have already matched, which is real work rather
    than an oversight.
    """
    tool = _tool(
        inputSchema={
            "type": "object",
            "properties": {"a": {"type": "string"}},
            "unevaluatedProperties": False,
        }
    )
    _, findings = load_manifest(_manifest(tool))
    assert "MCP-SCHEMA-KEYWORD-UNMODELED" in {f.rule_id for f in findings}


def test_a_keyword_that_is_now_modelled_is_no_longer_reported_as_unmodelled() -> None:
    """`dependentRequired` used to be on that list, and is a rule now.

    The warning existed because the constraint was invisible to the diff and to
    the validator. Leaving it in place after modelling the keyword would tell a
    reader to distrust a check that works.
    """
    tool = _tool(
        inputSchema={
            "type": "object",
            "properties": {"a": {"type": "string"}, "b": {"type": "string"}},
            "dependentRequired": {"a": ["b"]},
        }
    )
    service, findings = load_manifest(_manifest(tool))
    assert "MCP-SCHEMA-KEYWORD-UNMODELED" not in {f.rule_id for f in findings}

    body = service.operations[0].request_body
    assert body is not None
    schema = next(iter(body.content.values()))
    assert schema.dependent_required == {"a": ["b"]}


def test_the_response_status_is_not_an_invented_http_code() -> None:
    """A JSON-RPC result has no status code.

    `"200"` would assert an HTTP outcome the protocol never produces, and
    `diff/compat.py` classifies on `startswith("2")`, so the invented code
    would draw HTTP-flavoured severities out of the rule engine.
    """
    service, _ = load_manifest(_manifest(_tool(outputSchema={"type": "object", "properties": {}})))
    assert [r.status for r in service.operations[0].responses] == ["result"]


def test_a_tool_without_an_output_schema_declares_no_response() -> None:
    """An empty Response would be a contract we made up."""
    service, _ = load_manifest(_manifest(_tool()))
    assert service.operations[0].responses == []
