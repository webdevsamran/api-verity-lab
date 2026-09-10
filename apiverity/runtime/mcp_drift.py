"""Declared MCP tool manifest vs what a live server actually serves.

Two families with different subjects, and keeping them apart is the whole
point of the report:

``MCP-DRIFT-*``
    the declared manifest against the live one. Needs a manifest.
``MCP-CONF-*``
    the live server against the specification. Needs no manifest, and answers
    a question a diff cannot: is this server well-formed at all?

The prefix is `MCP-DRIFT-` rather than the bare `DRIFT-` used by the HTTP path,
following `GQL-DRIFT-*` in `specs/graphql/operations.py`, so a mixed report
never collides.

Schema drift is computed by feeding the live payload through the *same*
`load_manifest` the declared side went through and handing both to
`diff_services`. That is deliberate: two contracts compared by the differ must
have been built the same way, or the differences it reports include the ones
the loader invented. It also means the ranking work is already done -- every
finding carries the `CHG-*` id and the `BRK-*` rule that classified it.
"""

from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel, Field

from apiverity.core.model import ChangeKind, Service, Severity
from apiverity.diff.engine import diff_services
from apiverity.rules.breaking import evaluate_breaking
from apiverity.specs.mcp.manifest import ANNOTATION_HINTS, load_manifest
from apiverity.specs.mcp.runner import (
    DEFAULT_MAX_PAGES,
    McpClient,
    McpTransportError,
    Observation,
    list_tools,
    probe,
)

#: Content block types the current revision defines.
_CONTENT_BLOCKS = {"text", "image", "audio", "resource_link", "resource"}


class McpFinding(BaseModel):
    rule_id: str
    severity: str = "WARN"
    message: str
    tool: str | None = None
    #: The `CHG-*` id and `BRK-*` rule behind a schema finding, so a reader can
    #: trace it back to the shared engine rather than take it on trust.
    change_id: str | None = None
    source_rule_id: str | None = None


class McpDriftReport(BaseModel):
    target: str
    findings: list[McpFinding] = Field(default_factory=list)
    tools_declared: int = 0
    tools_served: int = 0
    duration_ms: int = 0
    observation: dict[str, Any] = Field(default_factory=dict)
    #: What the run established about who this server will talk to. Present
    #: even when every check passed, because a posture report that only speaks
    #: when something is wrong cannot be used as evidence that it is not.
    auth_posture: dict[str, Any] = Field(default_factory=dict)
    #: Trace id and per-call spans, when tracing was configured. Empty
    #: otherwise -- an empty dict says "not traced", where a fabricated id
    #: would say "traced, look it up" and send the reader somewhere nothing
    #: exists.
    trace: dict[str, Any] = Field(default_factory=dict)


def _conformance(tools: list[dict[str, Any]], envelope: dict[str, Any]) -> list[McpFinding]:
    """The live server against the specification, with no manifest involved."""
    findings: list[McpFinding] = []

    for key in ("ttlMs", "cacheScope"):
        if key not in envelope:
            findings.append(
                McpFinding(
                    rule_id="MCP-CONF-LIST-RESULT-INCOMPLETE",
                    severity="WARN",
                    message=(
                        f"tools/list omitted `{key}`, which is required on a list result "
                        "from revision 2026-07-28"
                    ),
                )
            )

    for tool in tools:
        name = tool.get("name")
        if not isinstance(name, str) or not name.strip():
            findings.append(
                McpFinding(
                    rule_id="MCP-CONF-TOOL-NAME-MISSING",
                    severity="ERROR",
                    message="a served tool has no `name`; the specification requires one",
                )
            )
            continue
        schema = tool.get("inputSchema")
        if not isinstance(schema, dict):
            findings.append(
                McpFinding(
                    rule_id="MCP-CONF-INPUT-SCHEMA-MISSING",
                    severity="ERROR",
                    tool=name,
                    message=f"tool {name!r} serves no `inputSchema`; the specification requires one",
                )
            )
            continue
        if schema.get("type") != "object":
            findings.append(
                McpFinding(
                    rule_id="MCP-CONF-INPUT-SCHEMA-NOT-OBJECT",
                    severity="ERROR",
                    tool=name,
                    message=(
                        f"tool {name!r} serves inputSchema.type={schema.get('type')!r}; "
                        "tool arguments are an object"
                    ),
                )
            )
        dialect = schema.get("$schema")
        if isinstance(dialect, str) and "2020-12" not in dialect:
            findings.append(
                McpFinding(
                    rule_id="MCP-CONF-SCHEMA-DIALECT",
                    severity="INFO",
                    tool=name,
                    message=(
                        f"tool {name!r} declares JSON Schema dialect {dialect!r}; MCP schemas "
                        "default to 2020-12 and this tool is compared under those semantics"
                    ),
                )
            )
    return findings


def _stability(first: list[dict[str, Any]], second: list[dict[str, Any]]) -> list[McpFinding]:
    """Two `tools/list` calls on separate connections, compared.

    The specification says the tool set MUST NOT vary per connection, and only
    SHOULD be ordered deterministically. Those are different strengths and get
    different severities: a set that changes is an error, an order that changes
    is worth knowing and nothing more.
    """
    first_names = sorted(str(t.get("name")) for t in first if t.get("name"))
    second_names = sorted(str(t.get("name")) for t in second if t.get("name"))
    if first_names != second_names:
        only_first = sorted(set(first_names) - set(second_names))
        only_second = sorted(set(second_names) - set(first_names))
        return [
            McpFinding(
                rule_id="MCP-CONF-LIST-UNSTABLE",
                severity="ERROR",
                message=(
                    "two tools/list calls on separate connections returned different tool "
                    f"sets (only in the first: {only_first or 'none'}; only in the second: "
                    f"{only_second or 'none'}). The specification says the tool set MUST NOT "
                    "vary per connection"
                ),
            )
        ]

    raw_first = [str(t.get("name")) for t in first if t.get("name")]
    raw_second = [str(t.get("name")) for t in second if t.get("name")]
    if raw_first != raw_second:
        return [
            McpFinding(
                rule_id="MCP-CONF-LIST-ORDER-NONDETERMINISTIC",
                severity="INFO",
                message=(
                    "tools/list returned the same tools in a different order across two "
                    "connections; the specification only SHOULDs a deterministic order, so "
                    "this is not a defect -- but a consumer keyed on position is wrong"
                ),
            )
        ]
    return []


#: Change kinds the diff produces that this report already covers better
#: elsewhere.
#:
#: Without this, `list_regions` -- declared and not served -- is reported twice:
#: once as MCP-DRIFT-TOOL-MISSING, with a message about agents calling it and
#: failing, and again as MCP-DRIFT-SCHEMA carrying BRK-RPC-REMOVED. Same fact,
#: two rule ids, and the second one is phrased for a version diff rather than
#: for a live server. A drift report that says everything twice is how a tool
#: earns "it found four hundred things and none of them mattered".
_COVERED_ELSEWHERE = {
    ChangeKind.RPC_REMOVED,  # -> MCP-DRIFT-TOOL-MISSING
    ChangeKind.RPC_ADDED,  # -> MCP-DRIFT-TOOL-UNDECLARED
    ChangeKind.OPERATION_REMOVED,
    ChangeKind.OPERATION_ADDED,
    ChangeKind.TOOL_RENAME_SUSPECTED,  # a rename across declared/served is presence
    ChangeKind.TOOL_ANNOTATION_CHANGED,  # -> MCP-DRIFT-ANNOTATION
}


def _schema_drift(declared: Service, observed: Service) -> list[McpFinding]:
    """Declared vs served, through the shared differ and rule engine."""
    findings: list[McpFinding] = []
    changes = diff_services(declared, observed)
    classified = {f.change_id: f for f in evaluate_breaking(changes)}

    for change in changes:
        if change.kind in _COVERED_ELSEWHERE:
            continue
        finding = classified.get(change.id)
        if finding is None:
            continue
        # A finding the shared engine grades ERROR is drift that will break an
        # agent generated from the manifest. WARN and INFO are reported at the
        # severity the engine already assigned rather than being re-graded
        # here, so one change means one severity everywhere it appears.
        breaking = finding.severity is Severity.ERROR
        findings.append(
            McpFinding(
                rule_id="MCP-DRIFT-SCHEMA" if breaking else "MCP-DRIFT-SCHEMA-COMPATIBLE",
                severity=finding.severity.value,
                tool=change.operation_key.removeprefix("tool ") or None,
                message=f"declared and served differ: {change.description}",
                change_id=change.id,
                source_rule_id=finding.rule_id,
            )
        )
    return findings


def _presence(
    declared: Service, observed: Service, *, pagination_exhausted: bool
) -> list[McpFinding]:
    declared_names = {op.rpc_name for op in declared.operations if op.rpc_name}
    served_names = {op.rpc_name for op in observed.operations if op.rpc_name}
    findings: list[McpFinding] = []

    for name in sorted(declared_names - served_names):
        if not pagination_exhausted:
            # A tool on page fifty-one is not a tool that was removed. Saying
            # nothing is the only honest option once the page cap was hit.
            continue
        findings.append(
            McpFinding(
                rule_id="MCP-DRIFT-TOOL-MISSING",
                severity="ERROR",
                tool=name,
                message=(
                    f"tool {name!r} is declared in the manifest but not served; an agent "
                    "generated from this manifest will call it and fail"
                ),
            )
        )

    for name in sorted(served_names - declared_names):
        findings.append(
            McpFinding(
                rule_id="MCP-DRIFT-TOOL-UNDECLARED",
                severity="WARN",
                tool=name,
                message=(
                    f"tool {name!r} is served but absent from the manifest; agents will "
                    "discover and may call a capability nobody agreed to support"
                ),
            )
        )
    return findings


def _annotations(declared: Service, observed: Service) -> list[McpFinding]:
    findings: list[McpFinding] = []
    served = {op.rpc_name: op for op in observed.operations}
    for op in declared.operations:
        other = served.get(op.rpc_name)
        if other is None:
            continue
        want = (op.bindings.get("mcp") or {}).get("annotations") or {}
        got = (other.bindings.get("mcp") or {}).get("annotations") or {}
        for hint in ANNOTATION_HINTS:
            if want.get(hint) != got.get(hint):
                findings.append(
                    McpFinding(
                        rule_id="MCP-DRIFT-ANNOTATION",
                        severity="WARN",
                        tool=op.rpc_name,
                        message=(
                            f"tool {op.rpc_name!r} declares {hint}={want.get(hint)!r} but "
                            f"serves {got.get(hint)!r}; an agent that planned around the "
                            "declared hint planned wrong"
                        ),
                    )
                )
    return findings


def detect_mcp_drift(
    declared: Service | None,
    endpoint: str,
    *,
    timeout: float = 10.0,
    headers: dict[str, str] | None = None,
    max_pages: int = DEFAULT_MAX_PAGES,
    check_stability: bool = True,
    check_auth: bool = True,
    client_factory: Any = None,
    recorder: Any = None,
) -> McpDriftReport:
    """Compare a declared manifest against a live server, read-only.

    Nothing here invokes a tool. `tools/list` and `server/discover` are reads;
    `tools/call` has side effects and lives behind an explicit opt-in.

    `declared` may be None, which runs the conformance half alone -- useful
    against a server whose manifest nobody has captured yet.

    `recorder` is an optional `exporters.otel.TraceRecorder`. When given, every
    MCP call this run makes becomes a span following the OpenTelemetry GenAI
    conventions, and the report records the trace id -- so a drift finding can
    be read next to the call that produced it in whatever the team already
    uses, rather than in a viewer only this tool can open.
    """
    started = time.monotonic()

    def make_client() -> McpClient:
        if client_factory is not None:
            return client_factory()  # type: ignore[no-any-return]
        return McpClient(endpoint, timeout=timeout, headers=headers, recorder=recorder)

    with make_client() as client:
        observation = probe(client, headers=headers)

        if observation.discover_status == "unsupported-protocol-version":
            # Stop before any tool comparison. Reporting every declared tool as
            # missing because the server refused our revision would be a
            # confident lie; `specs/graphql/runner.py::introspect` already
            # refuses the equivalent for the same reason.
            return McpDriftReport(
                target=endpoint,
                tools_declared=len(declared.operations) if declared else 0,
                findings=[
                    McpFinding(
                        rule_id="MCP-DRIFT-PROTOCOL-UNSUPPORTED",
                        severity="ERROR",
                        message=observation.reason,
                    )
                ],
                observation=observation.as_dict(),
                duration_ms=int((time.monotonic() - started) * 1000),
            )

        findings: list[McpFinding] = []
        if observation.discover_status == "method-not-found":
            findings.append(
                McpFinding(
                    rule_id="MCP-DRIFT-LEGACY-SERVER",
                    severity="INFO",
                    message=observation.reason,
                )
            )

        tools, envelope = list_tools(client, observation, max_pages=max_pages)

        second: list[dict[str, Any]] = []
        if check_stability:
            with make_client() as other:
                second, _ = list_tools(other, Observation(endpoint=endpoint), max_pages=max_pages)

    auth_findings: list[McpFinding] = []
    posture: dict[str, Any] = {}
    if check_auth:
        # Imported here, not at module level: mcp_auth reports its results as
        # `McpFinding`, which is defined above. A top-level import in both
        # directions is a cycle.
        from apiverity.runtime.mcp_auth import assess_auth_posture

        auth_findings, posture = assess_auth_posture(
            endpoint,
            tools_served=len(tools),
            headers=headers,
            timeout=timeout,
            max_pages=max_pages,
        )

    if not observation.pagination_exhausted:
        findings.append(
            McpFinding(
                rule_id="MCP-DRIFT-PAGINATION-CAPPED",
                severity="WARN",
                message=(
                    f"stopped after {observation.pages_read} pages of tools/list with a cursor "
                    "still set; declared tools absent from what was read are NOT reported as "
                    "missing, because they may simply be on a later page"
                ),
            )
        )

    findings.extend(auth_findings)
    findings.extend(_conformance(tools, envelope))
    if check_stability:
        findings.extend(_stability(tools, second))

    observed, load_findings = load_manifest({"tools": tools}, label="served")
    findings.extend(
        McpFinding(
            rule_id=f.rule_id,
            severity=f.severity.value,
            message=f"served manifest: {f.message}",
        )
        for f in load_findings
        if f.severity is not Severity.INFO
    )

    if declared is not None:
        findings.extend(
            _presence(declared, observed, pagination_exhausted=observation.pagination_exhausted)
        )
        findings.extend(_schema_drift(declared, observed))
        findings.extend(_annotations(declared, observed))

    return McpDriftReport(
        target=endpoint,
        findings=findings,
        tools_declared=len(declared.operations) if declared else 0,
        tools_served=len(observed.operations),
        observation=observation.as_dict(),
        auth_posture=posture,
        duration_ms=int((time.monotonic() - started) * 1000),
    )


__all__ = [
    "McpDriftReport",
    "McpFinding",
    "McpTransportError",
    "detect_mcp_drift",
]
