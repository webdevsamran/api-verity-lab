"""Optionally call MCP tools, and check what comes back against what was declared.

Everything else in the MCP lane is a read. This is the one path that makes a
server *do* something, so the gate matters more than the check.

The gate, and why it is shaped like `replay`
--------------------------------------------
`apiverity replay` already answers "how do we let someone send real traffic
without letting them do it by accident", and `SAFETY_MODEL.md` documents that
answer. Copying it beats inventing a second vocabulary:

* nothing is sent unless a tool is named with ``--invoke-tool``;
* **exact names only, never globs.** A pattern matched against a live tool list
  hands the *server* the choice of what runs. That is the wrong way round;
* dry run by default. ``--invoke-tool`` alone prints the plan -- every tool,
  every generated argument -- and sends nothing. ``--execute`` sends;
* a non-local target plus ``--execute`` needs ``--i-know-this-is-production``,
  the same token replay uses.

Annotations are never part of that gate. `readOnlyHint` is exactly the kind of
claim an attacker controls, and the specification says clients MUST treat
annotations as untrusted unless the server is trusted; letting one authorise a
call would make the safest-looking tool the easiest to abuse.

Why the findings do not quote values
------------------------------------
`core/validation.py::validate_value` embeds the offending value in its message
(``value {value!r} not in enum ...``). Routing a live `structuredContent`
through it and storing the result would write real response data into a
committed artifact -- customer records, tokens, whatever the tool returns --
and `docs/privacy.md` promises the opposite. So a violation here reports the
JSON pointer, the declared constraint and the observed **type**, and never the
observed value.
"""

from __future__ import annotations

import random
from typing import Any

from pydantic import BaseModel, Field

from apiverity.core.model import Operation, SchemaNode, Service
from apiverity.fuzz.generate import generate_valid
from apiverity.runtime.mcp_drift import McpFinding
from apiverity.specs.mcp.runner import McpClient
from apiverity.traffic.safety import classify_target

#: Content block types the current revision defines.
CONTENT_BLOCKS = frozenset({"text", "image", "audio", "resource_link", "resource"})


class InvokePlan(BaseModel):
    """What would be sent. Printed by a dry run, and never inferred."""

    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    declares_output_schema: bool = False


class InvokeReport(BaseModel):
    target: str
    executed: bool = False
    classification: str = "unknown"
    plan: list[InvokePlan] = Field(default_factory=list)
    findings: list[McpFinding] = Field(default_factory=list)
    calls_made: int = 0
    seed: int = 0


class InvokeRefused(RuntimeError):
    """The request was refused by the safety gate rather than attempted."""


def _observed_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def check_against_schema(
    value: Any, schema: SchemaNode | None, pointer: str = ""
) -> list[tuple[str, str]]:
    """Structural conformance, reported as ``(pointer, what was wrong)``.

    Deliberately narrower than `core.validation.validate_value`: it reports
    shapes, never values, so a finding can be written to an artifact without
    carrying whatever the tool returned. See the module docstring.
    """
    problems: list[tuple[str, str]] = []
    if schema is None:
        return problems

    expected = schema.type
    if expected:
        actual = _observed_type(value)
        compatible = actual == expected or (expected == "number" and actual == "integer")
        if not compatible and not (value is None and schema.nullable):
            problems.append((pointer or "/", f"expected {expected}, got {actual}"))
            return problems

    if expected == "object" and isinstance(value, dict):
        for name in schema.required:
            if name not in value:
                problems.append((f"{pointer}/{name}", "required property is absent"))
        for name, child in schema.properties.items():
            if name in value:
                problems.extend(check_against_schema(value[name], child, f"{pointer}/{name}"))
    elif expected == "array" and isinstance(value, list) and schema.items is not None:
        for index, item in enumerate(value):
            problems.extend(check_against_schema(item, schema.items, f"{pointer}/{index}"))

    if schema.enum is not None and value not in schema.enum:
        # The declared set is the contract and is safe to print; the value is
        # the server's data and is not.
        problems.append(
            (pointer or "/", f"value is outside the declared enum of {len(schema.enum)}")
        )
    return problems


def _arguments_for(operation: Operation, seed: int) -> dict[str, Any]:
    """Generate a valid argument object from the *declared* input schema.

    Declared, not served, on purpose: the question this asks is whether the
    server honours what it published.
    """
    body = operation.request_body
    if body is None:
        return {}
    schema = next(iter(body.content.values()), None)
    if schema is None:
        return {}
    generated = generate_valid(schema, random.Random(seed))
    return generated if isinstance(generated, dict) else {}


def build_plan(service: Service, tool_names: list[str], *, seed: int = 0) -> list[InvokePlan]:
    """Resolve names to a plan, refusing any name the manifest does not declare."""
    by_name = {op.rpc_name: op for op in service.operations if op.rpc_name}
    unknown = [name for name in tool_names if name not in by_name]
    if unknown:
        raise InvokeRefused(
            f"not declared in this manifest: {', '.join(sorted(unknown))}. "
            f"Declared tools are: {', '.join(sorted(by_name))}"
        )
    return [
        InvokePlan(
            tool=name,
            arguments=_arguments_for(by_name[name], seed),
            declares_output_schema=bool(
                (by_name[name].bindings.get("mcp") or {}).get("declares_output_schema")
            ),
        )
        for name in tool_names
    ]


def invoke_tools(
    service: Service,
    endpoint: str,
    tool_names: list[str],
    *,
    execute: bool = False,
    allow_production: bool = False,
    timeout: float = 10.0,
    headers: dict[str, str] | None = None,
    seed: int = 0,
    client_factory: Any = None,
) -> InvokeReport:
    """Plan, gate, and (only on `execute`) call the named tools."""
    if not tool_names:
        raise InvokeRefused(
            "no tools named. --execute without --invoke-tool would let the server's "
            "tool list decide what runs"
        )

    classification = classify_target(endpoint)
    report = InvokeReport(
        target=endpoint,
        classification=classification.classification,
        plan=build_plan(service, tool_names, seed=seed),
        seed=seed,
    )

    if not execute:
        return report

    if classification.classification not in {"local", "dev", "staging"} and not allow_production:
        raise InvokeRefused(
            f"{endpoint} classifies as {classification.classification!r}; calling tools "
            "there needs --i-know-this-is-production"
        )

    report.executed = True
    findings: list[McpFinding] = []
    by_name = {op.rpc_name: op for op in service.operations if op.rpc_name}

    with McpClient(endpoint, timeout=timeout, headers=headers) as client:
        for step in report.plan:
            reply = client.call("tools/call", {"name": step.tool, "arguments": step.arguments})
            report.calls_made += 1

            if reply.error is not None:
                findings.append(
                    McpFinding(
                        rule_id="MCP-DRIFT-CALL-ERROR-SHAPE",
                        severity="WARN",
                        tool=step.tool,
                        message=(
                            f"tools/call returned a JSON-RPC error (code "
                            f"{reply.error_code}); the specification puts tool failures in a "
                            "successful result with isError: true, and reserves JSON-RPC "
                            "errors for protocol-level problems"
                        ),
                    )
                )
                continue

            result = reply.result or {}
            findings.extend(_check_result(step, result, by_name.get(step.tool)))

    report.findings = findings
    return report


def _check_result(
    step: InvokePlan, result: dict[str, Any], operation: Operation | None
) -> list[McpFinding]:
    findings: list[McpFinding] = []

    for block in result.get("content") or []:
        if isinstance(block, dict) and block.get("type") not in CONTENT_BLOCKS:
            findings.append(
                McpFinding(
                    rule_id="MCP-CONF-CALL-CONTENT-BLOCK-UNKNOWN",
                    severity="WARN",
                    tool=step.tool,
                    message=(
                        f"content block type {block.get('type')!r} is not one of "
                        f"{sorted(CONTENT_BLOCKS)}"
                    ),
                )
            )

    if not step.declares_output_schema:
        return findings

    structured = result.get("structuredContent")
    if structured is None:
        findings.append(
            McpFinding(
                rule_id="MCP-DRIFT-CALL-NO-STRUCTURED-CONTENT",
                severity="WARN",
                tool=step.tool,
                message=(
                    f"tool {step.tool!r} declares an outputSchema but returned no "
                    "structuredContent, so nothing conforms to it"
                ),
            )
        )
        return findings

    declared_schema = None
    if operation is not None and operation.responses:
        declared_schema = next(iter(operation.responses[0].content.values()), None)

    for pointer, problem in check_against_schema(structured, declared_schema):
        findings.append(
            McpFinding(
                rule_id="MCP-DRIFT-CALL-OUTPUT-SCHEMA",
                severity="ERROR",
                tool=step.tool,
                message=(
                    f"structuredContent violates the declared outputSchema at {pointer}: {problem}"
                ),
            )
        )
    return findings


__all__ = [
    "InvokePlan",
    "InvokeRefused",
    "InvokeReport",
    "build_plan",
    "check_against_schema",
    "invoke_tools",
]
