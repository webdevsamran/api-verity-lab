"""Findings mapped onto published security frameworks, with the gaps stated.

An auditor asking "show me your MCP03 coverage" does not want a list of rule
ids. They want the control, the evidence, and — the part most tools omit —
which controls this evidence does *not* speak to.

That omission is the reason this module is shaped the way it is. A mapping
report that lists three controls with findings and says nothing about the other
seven reads as a clean bill of health for all ten. It is the single easiest way
for a governance tool to mislead the person relying on it, so every control
appears in every report with one of four states:

``findings``
    this run produced evidence against the control.
``clear``
    rules that map to this control ran in this artifact and found nothing.
``not-exercised``
    rules map to it, and the command that produces them was not the command
    that wrote this artifact. The report names the command that would.
``not-assessable``
    nothing this tool can see speaks to the control at all, and the entry says
    why. Command injection inside a server's implementation is not visible from
    its tool manifest, and no amount of contract analysis will make it so.

Telling ``clear`` from ``not-exercised`` needs to know which rules could have
fired, so `_PRODUCED_BY` maps a rule-id prefix to the commands that emit it and
the artifact's own `command` decides. Without that distinction a control has
"no findings" whether it was checked or never looked at, which is precisely the
ambiguity an audit is trying to remove.

Framework contents are quoted from the published sources, each fetched and
dated:

* OWASP MCP Top 10 — v0.1 beta, https://owasp.org/www-project-mcp-top-10/
  (read 2026-09-09)
* OWASP Top 10 for Agentic Applications — v1.0, published 2025-12-09,
  https://genai.owasp.org/ (read 2026-09-09)
* OWASP API Security Top 10 — 2023 edition,
  https://owasp.org/API-Security/editions/2023/en/0x11-t10/ (read 2026-09-09)

The mappings between those controls and this project's rules are *this
project's own reading*, not an OWASP endorsement, and the report says so in
its own footer rather than only here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

NL = chr(10)


@dataclass(frozen=True)
class Control:
    """One numbered entry of a published framework."""

    id: str
    title: str
    #: Rule-id prefixes whose findings are evidence for this control.
    rules: tuple[str, ...] = ()
    #: Why this tool cannot speak to the control. Required when `rules` is
    #: empty: a control with no mapping and no reason is an unexplained blank.
    limitation: str = ""
    #: What the mapped rules do and do not establish, when the coverage is
    #: real but partial. Rendered next to the evidence.
    caveat: str = ""


@dataclass(frozen=True)
class Framework:
    key: str
    name: str
    version: str
    published: str
    url: str
    read_on: str
    controls: tuple[Control, ...] = field(default_factory=tuple)


#: Rule-id prefix -> the commands whose artifacts can carry it.
#:
#: Longest prefix wins, so `MCP-DRIFT-` is resolved before `MCP-`.
_PRODUCED_BY: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("MCP-POISON-", ("validate",)),
    ("MCP-ANNOTATION-", ("validate",)),
    ("MCP-AUTH-", ("drift",)),
    ("MCP-DRIFT-", ("drift",)),
    ("MCP-CONF-", ("drift",)),
    ("MCP-LOCK-", ("mcp-lock",)),
    ("MCP-SHADOW-", ("mcp-inventory",)),
    ("MCP-INVENTORY-", ("mcp-inventory",)),
    ("MCP-CALL-RESULT-", ("drift",)),
    ("DRIFT-RESPONSE-CREDENTIAL", ("drift",)),
    ("BRK-", ("breaking", "drift", "mcp-lock")),
    ("SEMVER-", ("breaking",)),
    ("SEC-", ("validate",)),
    ("DRIFT-", ("drift",)),
    ("SCHEMA-", ("validate",)),
)


def producing_commands(rule_prefix: str) -> tuple[str, ...]:
    for prefix, commands in sorted(_PRODUCED_BY, key=lambda kv: -len(kv[0])):
        if rule_prefix.startswith(prefix) or prefix.startswith(rule_prefix):
            return commands
    return ()


MCP_TOP_10 = Framework(
    key="owasp-mcp",
    name="OWASP MCP Top 10",
    version="v0.1 (beta)",
    published="2025",
    url="https://owasp.org/www-project-mcp-top-10/",
    read_on="2026-09-09",
    controls=(
        Control(
            "MCP01",
            "Token Mismanagement & Secret Exposure",
            rules=(
                "MCP-AUTH-PLAINTEXT-TRANSPORT",
                "MCP-CALL-RESULT-CREDENTIAL",
                "MCP-SHADOW-INLINE-CREDENTIAL",
            ),
            caveat=(
                "the transport, a credential written into a client config, and a credential "
                "coming back in a tool result. How a server stores, scopes or rotates a token "
                "is still not something a manifest reveals"
            ),
        ),
        Control(
            "MCP02",
            "Privilege Escalation via Scope Creep",
            rules=("MCP-LOCK-TOOL-ADDED", "MCP-DRIFT-TOOL-UNDECLARED", "BRK-RPC-ADDED"),
            caveat=(
                "a growing tool surface is scope creep the contract can see; privileges the "
                "server holds behind those tools are not declared anywhere it can read"
            ),
        ),
        Control(
            "MCP03",
            "Tool Poisoning",
            rules=(
                "MCP-POISON-",
                "BRK-MCP-TOOL-DESCRIPTION-CHANGED",
                "MCP-DRIFT-SCHEMA",
            ),
        ),
        Control(
            "MCP04",
            "Software Supply Chain Attacks & Dependency Tampering",
            rules=(
                "MCP-LOCK-SIGNATURE-",
                "MCP-LOCK-UNSIGNED",
                "MCP-LOCK-TOOL-",
                "MCP-SHADOW-FETCHED-AT-LAUNCH",
            ),
            caveat=(
                "the tool surface you depend on changing under you, and a server launched with "
                "`npx`/`uvx`, where the code that starts is whatever the registry serves today. "
                "It says nothing about the packages the server itself installs"
            ),
        ),
        Control(
            "MCP05",
            "Command Injection & Execution",
            limitation=(
                "what a tool does with its arguments happens inside the server. A manifest "
                "declares the shape of an input, never what is done with it, and nothing this "
                "tool reads would distinguish a safe implementation from an injectable one"
            ),
        ),
        Control(
            "MCP06",
            "Intent Flow Subversion",
            rules=("MCP-POISON-CROSS-TOOL", "MCP-POISON-INSTRUCTION"),
        ),
        Control(
            "MCP07",
            "Insufficient Authentication & Authorization",
            rules=("MCP-AUTH-",),
            caveat=(
                "established by probing tools/list with and without a credential. Whether "
                "individual tool *calls* are authorized is not tested, because testing it "
                "would mean calling them"
            ),
        ),
        Control(
            "MCP08",
            "Lack of Audit and Telemetry",
            limitation=(
                "whether a server logs what it did is a property of its deployment. This tool "
                "produces an audit record of its own runs -- every artifact conforms to "
                "schemas/result-v1 and the self-hosted server hash-chains its events -- but "
                "that is evidence about this tool, not about the server it looked at"
            ),
        ),
        Control(
            "MCP09",
            "Shadow MCP Servers",
            rules=("MCP-SHADOW-SERVER", "MCP-DRIFT-TOOL-UNDECLARED", "MCP-LOCK-TOOL-ADDED"),
            caveat=(
                "`apiverity mcp-inventory` finds servers configured on this machine and absent "
                "from an approved list, by reading client configuration rather than scanning a "
                "network. A server nobody configured here, on a host nobody named, is out of "
                "reach of both"
            ),
        ),
        Control(
            "MCP10",
            "Context Injection & Over-Sharing",
            rules=("MCP-POISON-INVISIBLE-TEXT", "MCP-POISON-HIDDEN-MARKUP"),
        ),
    ),
)


ASI_TOP_10 = Framework(
    key="owasp-asi",
    name="OWASP Top 10 for Agentic Applications",
    version="v1.0",
    published="2025-12-09",
    url="https://genai.owasp.org/",
    read_on="2026-09-09",
    controls=(
        Control(
            "ASI01",
            "Agent Goal Hijack",
            rules=("MCP-POISON-INSTRUCTION", "MCP-POISON-CROSS-TOOL", "MCP-POISON-INVISIBLE-TEXT"),
            caveat=(
                "covers hijacking delivered through a tool manifest, which is the surface this "
                "tool reads. A prompt reaching the agent by any other route is out of view"
            ),
        ),
        Control(
            "ASI02",
            "Tool Misuse",
            rules=("MCP-ANNOTATION-", "MCP-DRIFT-", "BRK-MCP-"),
            caveat=(
                "a tool whose declared safety hints contradict its name or its served "
                "behaviour is misuse waiting to happen; whether an agent actually misused one "
                "is a trace question, not a contract question"
            ),
        ),
        Control(
            "ASI03",
            "Identity & Privilege Abuse",
            rules=(
                "MCP-AUTH-",
                "SEC-AUTH-",
                "MCP-CALL-RESULT-CREDENTIAL",
                "MCP-SHADOW-INLINE-CREDENTIAL",
            ),
            caveat=(
                "a credential returned in a tool result enters the agent's context on every "
                "call, which is where inherited privilege starts"
            ),
        ),
        Control(
            "ASI04",
            "Agentic Supply Chain Vulnerabilities",
            rules=("MCP-LOCK-", "MCP-SHADOW-FETCHED-AT-LAUNCH"),
            caveat=(
                "the tool surface as the dependency, and a server fetched from a registry at "
                "launch; not the server's own dependencies"
            ),
        ),
        Control(
            "ASI05",
            "Unexpected Code Execution",
            limitation=(
                "execution happens inside a tool implementation this tool never runs. The "
                "opt-in `--invoke-tool` path sends a call and checks the result against the "
                "declared outputSchema; it does not observe what executed"
            ),
        ),
        Control(
            "ASI06",
            "Memory & Context Poisoning",
            rules=("MCP-POISON-INVISIBLE-TEXT", "MCP-POISON-HIDDEN-MARKUP"),
            caveat=(
                "a poisoned description enters the agent's context every time the tool list "
                "is read. Poisoning of an agent's own stored memory is not visible here"
            ),
        ),
        Control(
            "ASI07",
            "Insecure Inter-Agent Communication",
            rules=("MCP-AUTH-PLAINTEXT-TRANSPORT",),
            caveat=(
                "one leg of it: the transport between this client and one server. Agent-to-"
                "agent protocols are not among the six this engine reads"
            ),
        ),
        Control(
            "ASI08",
            "Cascading Failures",
            limitation=(
                "a cascade is a runtime property of several agents interacting. Nothing in a "
                "contract, a diff or a single-server probe would show one"
            ),
        ),
        Control(
            "ASI09",
            "Human-Agent Trust Exploitation",
            rules=("MCP-POISON-INSTRUCTION", "MCP-POISON-HIDDEN-MARKUP"),
            caveat=(
                "text that a client renders differently from what the model reads is exactly "
                "this: the human approves one thing and the agent acts on another"
            ),
        ),
        Control(
            "ASI10",
            "Rogue Agents",
            limitation=(
                "identifying an agent that has gone rogue needs observation of the agent. "
                "This tool looks at the contracts an agent is given, not at the agent"
            ),
        ),
    ),
)


API_TOP_10 = Framework(
    key="owasp-api",
    name="OWASP API Security Top 10",
    version="2023",
    published="2023",
    url="https://owasp.org/API-Security/editions/2023/en/0x11-t10/",
    read_on="2026-09-09",
    controls=(
        Control(
            "API1",
            "Broken Object Level Authorization",
            limitation=(
                "BOLA is proved by calling one tenant's object with another tenant's "
                "credential. That is an authorization probe, not a contract check, and this "
                "tool does not perform one"
            ),
        ),
        Control(
            "API2",
            "Broken Authentication",
            rules=("SEC-AUTH-", "SEC-SCHEME-", "MCP-AUTH-"),
            caveat=(
                "the contract's authentication *declarations*, plus what a live MCP server "
                "serves anonymously. An endpoint protected by an undeclared gateway looks "
                "identical to an unprotected one from here"
            ),
        ),
        Control(
            "API3",
            "Broken Object Property Level Authorization",
            rules=("SEC-ADDL-PROPERTIES", "BRK-RESP-FIELD-", "DRIFT-RESPONSE-CREDENTIAL"),
            caveat=(
                "a response that grew a field, or a schema that accepts any property, is "
                "where over-exposure hides. Whether a returned field should have been visible "
                "to that caller is not something the contract states"
            ),
        ),
        Control(
            "API4",
            "Unrestricted Resource Consumption",
            rules=("SEC-RATE-LIMIT-METADATA", "BRK-CONSTRAINT-"),
            caveat="undeclared limits, not measured ones. `apiverity regression` measures",
        ),
        Control(
            "API5",
            "Broken Function Level Authorization",
            rules=("SEC-UNAUTH-WRITE", "SEC-AUTH-MISSING"),
            caveat="a mutating operation with no declared authentication is the documented case",
        ),
        Control(
            "API6",
            "Unrestricted Access to Sensitive Business Flows",
            limitation=(
                "which flows are sensitive is a business judgement no contract encodes. The "
                "stateful workflow engine can exercise a flow; it cannot decide it mattered"
            ),
        ),
        Control(
            "API7",
            "Server Side Request Forgery",
            limitation=(
                "SSRF is a property of what a server does with a URL it was handed. A "
                "contract declares that it takes a URL and stops there"
            ),
        ),
        Control(
            "API8",
            "Security Misconfiguration",
            rules=("SEC-HTTPS-POLICY", "SEC-SENSITIVE-HEADER", "MCP-AUTH-PLAINTEXT-TRANSPORT"),
        ),
        Control(
            "API9",
            "Improper Inventory Management",
            rules=("DRIFT-", "MCP-DRIFT-TOOL-UNDECLARED", "MCP-LOCK-TOOL-ADDED", "BRK-OP-"),
            caveat=(
                "this is the control this project is closest to being *about*: an endpoint "
                "serving something the contract does not declare, and a tool surface that "
                "moved without review"
            ),
        ),
        Control(
            "API10",
            "Unsafe Consumption of APIs",
            rules=("MCP-DRIFT-", "MCP-CONF-"),
            caveat=(
                "consuming an MCP server whose behaviour has diverged from its manifest is "
                "exactly this risk, from the consumer's side"
            ),
        ),
    ),
)


FRAMEWORKS: dict[str, Framework] = {
    MCP_TOP_10.key: MCP_TOP_10,
    ASI_TOP_10.key: ASI_TOP_10,
    API_TOP_10.key: API_TOP_10,
}


def _findings(data: dict[str, Any]) -> list[dict[str, Any]]:
    raw = data.get("findings", [])
    return [f for f in raw if isinstance(f, dict)] if isinstance(raw, list) else []


def assess(control: Control, data: dict[str, Any]) -> dict[str, Any]:
    """One control's state against one result artifact."""
    if not control.rules:
        return {
            "control": control.id,
            "title": control.title,
            "state": "not-assessable",
            "detail": control.limitation,
            "findings": [],
        }

    evidence = [
        finding
        for finding in _findings(data)
        if any(str(finding.get("rule_id", "")).startswith(prefix) for prefix in control.rules)
    ]
    if evidence:
        return {
            "control": control.id,
            "title": control.title,
            "state": "findings",
            "detail": control.caveat,
            "findings": evidence,
        }

    command = str(data.get("command", ""))
    producers: set[str] = set()
    for prefix in control.rules:
        producers.update(producing_commands(prefix))

    if command and command in producers:
        return {
            "control": control.id,
            "title": control.title,
            "state": "clear",
            "detail": control.caveat,
            "findings": [],
        }
    return {
        "control": control.id,
        "title": control.title,
        "state": "not-exercised",
        "detail": (
            f"no rule mapped to this control can be produced by `apiverity {command}`. "
            f"Run {', '.join(f'`apiverity {c}`' for c in sorted(producers))} to assess it"
            if producers
            else "no command in this build produces a rule mapped to this control"
        ),
        "findings": [],
    }


def report(framework: Framework, data: dict[str, Any]) -> dict[str, Any]:
    """The whole framework against one artifact, every control present."""
    controls = [assess(control, data) for control in framework.controls]
    counts: dict[str, int] = {}
    for entry in controls:
        counts[entry["state"]] = counts.get(entry["state"], 0) + 1
    return {
        "framework": {
            "key": framework.key,
            "name": framework.name,
            "version": framework.version,
            "published": framework.published,
            "url": framework.url,
            "read_on": framework.read_on,
        },
        "subject": data.get("spec") or data.get("target") or data.get("source") or "unknown",
        "command": data.get("command", "unknown"),
        "controls": controls,
        "counts": counts,
    }


_STATE_LABEL = {
    "findings": "Findings",
    "clear": "Assessed, clear",
    "not-exercised": "Not exercised by this run",
    "not-assessable": "Not assessable by this tool",
}


def render_markdown(framework: Framework, data: dict[str, Any]) -> str:
    """An audit-legible table: every control, its state, its evidence."""
    result = report(framework, data)
    counts = result["counts"]
    lines = [
        f"# {framework.name} {framework.version}",
        "",
        f"Subject: `{result['subject']}` · produced by `apiverity {result['command']}`",
        "",
        "| # | Control | State | Evidence |",
        "|---|---|---|---|",
    ]
    for entry in result["controls"]:
        rule_ids = sorted({str(f.get("rule_id", "")) for f in entry["findings"]})
        evidence = ", ".join(f"`{r}`" for r in rule_ids) if rule_ids else "--"
        lines.append(
            f"| {entry['control']} | {entry['title']} | {_STATE_LABEL[entry['state']]} | "
            f"{evidence} |"
        )

    lines += ["", "## What each state means", ""]
    for state, label in _STATE_LABEL.items():
        lines.append(f"- **{label}** — {_STATE_HELP[state]} ({counts.get(state, 0)} of 10)")

    detailed = [e for e in result["controls"] if e["detail"]]
    if detailed:
        lines += ["", "## Limits of this evidence", ""]
        for entry in detailed:
            lines.append(f"- **{entry['control']}** — {entry['detail']}")

    findings_present = [e for e in result["controls"] if e["findings"]]
    if findings_present:
        lines += ["", "## Findings", ""]
        for entry in findings_present:
            lines.append(f"### {entry['control']} {entry['title']}")
            lines.append("")
            for finding in entry["findings"]:
                severity = str(finding.get("severity", "INFO"))
                lines.append(
                    f"- `{finding.get('rule_id', '')}` [{severity}] {finding.get('message', '')}"
                )
            lines.append("")

    lines += [
        "",
        "---",
        "",
        f"Control names and numbering are quoted from {framework.name} {framework.version}"
        f"{(', published ' + framework.published) if framework.published else ''} "
        f"(<{framework.url}>, read {framework.read_on}). **The mapping from those controls to "
        "this project's rules is api-verity-lab's own reading and is not endorsed by OWASP.** "
        "A control marked *Assessed, clear* means the rules mapped to it ran and produced "
        "nothing; it is not a statement that the system is secure against that risk.",
    ]
    return NL.join(lines) + NL


_STATE_HELP = {
    "findings": "this run produced evidence against the control",
    "clear": "rules mapped to this control ran here and found nothing",
    "not-exercised": "rules exist for it, but not in the command that wrote this artifact",
    "not-assessable": "nothing this tool can see speaks to the control; the reason is below",
}


__all__ = [
    "API_TOP_10",
    "ASI_TOP_10",
    "FRAMEWORKS",
    "MCP_TOP_10",
    "Control",
    "Framework",
    "assess",
    "producing_commands",
    "render_markdown",
    "report",
]
