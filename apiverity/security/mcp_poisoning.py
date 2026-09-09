"""Tool-poisoning and annotation-integrity checks for an MCP manifest.

Why a tool description gets its own scanner
-------------------------------------------
For every other protocol in this engine a description is documentation: a
human reads it, and changing it changes nothing about how software behaves. In
MCP the description **is the routing input**. An agent decides which tool to
call, and with what arguments, by reading it. So a description is executable in
the only sense that matters here, and editing one silently is the whole shape
of the attack -- OWASP's MCP Top 10 lists it as MCP03 *Tool Poisoning*, and the
first public proof of concept hid instructions inside an `<IMPORTANT>` block
that no client displayed.

That gives this module a subject the rest of `security/` does not have. The
static packs look for secrets a contract accidentally committed. This looks for
text a manifest deliberately aims at whoever reads it next.

What it will and will not claim
-------------------------------
Nothing here asserts intent. A description that says "ignore previous
instructions" may be a poisoned tool or may be a tool that manages prompts;
`MCP-POISON-INSTRUCTION` says the sentence addresses the agent rather than
describing the tool, which is true either way and is the thing a reviewer needs
pointed at. Only two families are graded ERROR, and both are for content with
no benign reading: characters that reach the model and cannot reach a human
reviewer, and a description naming a private-key or credential path.

Severities also respect what the specification says about trust. Annotations
are declared untrusted -- a client MUST NOT rely on them unless the server is
trusted -- so an annotation that contradicts the tool's own name is reported as
something to look at, never as an authorization decision. `SAFETY_MODEL.md`
section 11 already refuses to let annotations open any gate; this refuses to
let them close one.
"""

from __future__ import annotations

import re
import statistics
import unicodedata
from collections.abc import Iterator

from apiverity.core.model import (
    Finding,
    Operation,
    SchemaNode,
    Service,
    Severity,
    SourceLocation,
)
from apiverity.specs.mcp.manifest import ANNOTATION_HINTS

#: Characters that reach a model and do not reach a human reading the same
#: text: zero-width formatting, bidirectional overrides that reorder what is
#: displayed, and the Unicode tag block, which encodes ASCII invisibly and is
#: the carrier every published invisible-prompt-injection demonstration uses.
_INVISIBLE = {
    "\u200b": "zero-width space",
    "\u200c": "zero-width non-joiner",
    "\u200d": "zero-width joiner",
    "\u2060": "word joiner",
    "\ufeff": "zero-width no-break space",
    "\u202a": "left-to-right embedding",
    "\u202b": "right-to-left embedding",
    "\u202c": "pop directional formatting",
    "\u202d": "left-to-right override",
    "\u202e": "right-to-left override",
    "\u2066": "left-to-right isolate",
    "\u2067": "right-to-left isolate",
    "\u2068": "first strong isolate",
    "\u2069": "pop directional isolate",
}

#: U+E0000..U+E007F. Held as a range rather than enumerated because the whole
#: block is invisible and the point is that any of it is disqualifying.
_TAG_BLOCK = range(0xE0000, 0xE0080)

#: Sentences aimed at the agent rather than at a reader deciding whether the
#: tool is the right one. Anchored loosely on purpose: an attacker will not
#: reuse a published phrasing verbatim, and a reviewer would rather see one
#: false positive than miss the sentence that matters.
_INSTRUCTION_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"(?i)ignore\s+(all\s+|any\s+)?(previous|prior|earlier|above)\s+"),
        "tells the reader to discard earlier instructions",
    ),
    (
        re.compile(r"(?i)do\s+not\s+(tell|inform|mention|reveal|show|disclose)[^.]{0,40}\buser\b"),
        "tells the reader to keep something from the user",
    ),
    (
        re.compile(r"(?i)(?:<important>|<system>|\[system\]|<secret>)"),
        "carries a pseudo-directive tag that clients do not render",
    ),
    (
        re.compile(
            r"(?i)\bbefore\s+(?:you\s+)?(?:calling|using|invoking|running)\s+"
            r"(?:this|any)\s+tool\b"
        ),
        "conditions the reader's behaviour on a step outside this tool",
    ),
    (
        re.compile(r"(?i)\byou\s+must\s+(?:always|first|never)\b"),
        "issues an imperative to the reader",
    ),
    (
        re.compile(r"(?i)\b(?:always|never)\s+(?:pass|include|append|attach|forward)\b"),
        "directs what the reader should put in an argument",
    ),
    (
        re.compile(r"(?i)\bdo\s+not\s+(?:describe|explain|summari[sz]e)\s+(?:this|the)\b"),
        "tells the reader to hide what it is doing",
    ),
)

#: Locations that hold credentials on a developer machine. A tool that reads
#: one declares it in `inputSchema`; naming it in prose is a description
#: telling the agent where to go looking.
_CREDENTIAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)(?:~|\$HOME|/home/[^\s/]+|/users/[^\s/]+)?[/\\]?\.ssh\b"),
    re.compile(r"(?i)\bid_(?:rsa|dsa|ecdsa|ed25519)\b"),
    re.compile(r"(?i)\.aws[/\\]credentials\b"),
    re.compile(r"(?i)\.config[/\\]gcloud\b"),
    re.compile(r"(?i)[/\\]etc[/\\](?:passwd|shadow)\b"),
    re.compile(r"(?i)(?:^|[\s/\\])\.env(?:\.[a-z]+)?\b"),
    re.compile(r"(?i)\.(?:cursor|claude|codeium|continue)[/\\]\S*mcp[^\s]*\.json\b"),
    re.compile(r"(?i)\bprivate[ _-]?key\s+(?:file|path|at|in)\b"),
)

_HTML_COMMENT = re.compile(r"<!--(.*?)-->", re.DOTALL)

#: Verbs in a tool name that describe a write. Compared against a
#: `readOnlyHint: true`, which is a claim the same manifest makes about itself.
_MUTATING_VERBS = (
    "create",
    "delete",
    "destroy",
    "drop",
    "erase",
    "execute",
    "grant",
    "insert",
    "kill",
    "modify",
    "move",
    "patch",
    "post",
    "publish",
    "purge",
    "push",
    "put",
    "remove",
    "rename",
    "reset",
    "revoke",
    "run",
    "send",
    "set",
    "terminate",
    "truncate",
    "update",
    "upload",
    "write",
)

#: Below this a median is not a description of anything.
_MIN_TOOLS_FOR_OUTLIER = 3
#: A description has to be both absolutely large and a local outlier.
_OUTLIER_MIN_CHARS = 1000
_OUTLIER_RATIO = 8


_NAME_SPLIT = re.compile(r"[_\-.\s/]+|(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def _name_tokens(name: str) -> list[str]:
    """A tool name split into words, snake_case and camelCase alike.

    Substring matching was the first attempt and it read "run" out of
    `get_runtime_status`, which is a status reader. A tool named for a verb has
    that verb as a *word*, and nothing else counts.
    """
    return [token.lower() for token in _NAME_SPLIT.split(name) if token]


def _emoji_zwj(text: str, index: int) -> bool:
    """Whether a ZWJ at `index` is joining two pictographs.

    A family emoji is three zero-width joiners, and flagging one as hidden text
    would make the rule fire on friendly prose -- which is how a security check
    becomes the check everybody disables.
    """
    if index == 0 or index + 1 >= len(text):
        return False
    before, after = text[index - 1], text[index + 1]
    return all(unicodedata.category(ch) == "So" or ord(ch) > 0x1F000 for ch in (before, after))


def _invisible_runs(text: str) -> list[str]:
    """Names of the invisible characters in `text`, deduplicated and ordered."""
    found: list[str] = []
    for index, ch in enumerate(text):
        if ch == "\u200d" and _emoji_zwj(text, index):
            continue
        name = _INVISIBLE.get(ch)
        if name is None and ord(ch) in _TAG_BLOCK:
            name = "unicode tag character"
        if name is not None and name not in found:
            found.append(name)
    return found


def _schema_texts(node: SchemaNode | None, pointer: str) -> Iterator[tuple[str, str]]:
    """Every human-readable string in a schema, with a pointer to it."""
    if node is None:
        return
    for field in ("title", "description"):
        value = getattr(node, field, None)
        if isinstance(value, str) and value:
            yield value, f"{pointer}/{field}"
    for name, child in node.properties.items():
        yield from _schema_texts(child, f"{pointer}/properties/{name}")
    if node.items is not None:
        yield from _schema_texts(node.items, f"{pointer}/items")
    if isinstance(node.additional_properties, SchemaNode):
        yield from _schema_texts(node.additional_properties, f"{pointer}/additionalProperties")


def _operation_texts(op: Operation) -> Iterator[tuple[str, str]]:
    """Every string on a tool that an agent reads before choosing to call it."""
    if op.rpc_name:
        yield op.rpc_name, "name"
    if op.summary:
        yield op.summary, "title"
    if op.description:
        yield op.description, "description"
    if op.request_body is not None:
        for media, schema in sorted(op.request_body.content.items()):
            yield from _schema_texts(schema, f"inputSchema[{media}]")
    for response in op.responses:
        for media, schema in sorted(response.content.items()):
            yield from _schema_texts(schema, f"outputSchema[{media}]")


def _finding(
    rule_id: str,
    severity: Severity,
    message: str,
    op: Operation | None = None,
    location: SourceLocation | None = None,
) -> Finding:
    return Finding(
        rule_id=rule_id,
        severity=severity,
        message=message,
        operation_key=op.key if op is not None else None,
        location=location if location is not None else (op.source_location if op else None),
    )


def _scan_text(op: Operation, text: str, where: str, tool_names: set[str]) -> list[Finding]:
    findings: list[Finding] = []
    name = op.rpc_name or op.key

    invisible = _invisible_runs(text)
    if invisible:
        findings.append(
            _finding(
                "MCP-POISON-INVISIBLE-TEXT",
                Severity.ERROR,
                f"tool {name!r} carries {', '.join(invisible)} in its {where}; these reach the "
                "model and not the human reviewing the manifest, which is the only reason to "
                "put them there",
                op,
            )
        )

    for pattern, why in _INSTRUCTION_PATTERNS:
        match = pattern.search(text)
        if match:
            findings.append(
                _finding(
                    "MCP-POISON-INSTRUCTION",
                    Severity.WARN,
                    f"tool {name!r} {where} {why} ({match.group(0).strip()!r}). In MCP the "
                    "description is what the agent routes on, so a sentence addressed to the "
                    "agent is executable text, not documentation",
                    op,
                )
            )
            break

    for pattern in _CREDENTIAL_PATTERNS:
        match = pattern.search(text)
        if match:
            findings.append(
                _finding(
                    "MCP-POISON-CREDENTIAL-PATH",
                    Severity.ERROR,
                    f"tool {name!r} names {match.group(0).strip()!r} in its {where}; a tool that "
                    "legitimately reads a credential declares it in inputSchema, where a caller "
                    "can see it, rather than pointing the agent at the path in prose",
                    op,
                )
            )
            break

    for comment in _HTML_COMMENT.findall(text):
        if comment.strip():
            findings.append(
                _finding(
                    "MCP-POISON-HIDDEN-MARKUP",
                    Severity.WARN,
                    f"tool {name!r} hides text in an HTML comment in its {where} "
                    f"({comment.strip()[:60]!r}); a client rendering the description as markdown "
                    "shows nothing while the model reads all of it",
                    op,
                )
            )
            break

    others = tool_names - {op.rpc_name or ""}
    for other in sorted(others):
        if len(other) < 4 or other not in text:
            continue
        if any(pattern.search(text) for pattern, _ in _INSTRUCTION_PATTERNS):
            findings.append(
                _finding(
                    "MCP-POISON-CROSS-TOOL",
                    Severity.WARN,
                    f"tool {name!r} names another tool ({other!r}) in its {where} alongside an "
                    "instruction to the reader; a description that changes how a *different* "
                    "tool is used is a change nobody reviewing that tool would see",
                    op,
                )
            )
            break
    return findings


def _annotation_findings(operations: list[Operation]) -> list[Finding]:
    findings: list[Finding] = []
    undeclared: list[str] = []

    for op in operations:
        hints = (op.bindings.get("mcp") or {}).get("annotations") or {}
        name = op.rpc_name or op.key
        if all(hints.get(hint) is None for hint in ANNOTATION_HINTS):
            undeclared.append(name)
            continue

        if hints.get("readOnlyHint") is True and hints.get("destructiveHint") is True:
            findings.append(
                _finding(
                    "MCP-ANNOTATION-CONTRADICTORY",
                    Severity.WARN,
                    f"tool {name!r} declares readOnlyHint=true and destructiveHint=true. The "
                    "specification defines destructiveHint only when readOnlyHint is false, so "
                    "these say two incompatible things and a client believing either is "
                    "guessing which",
                    op,
                )
            )

        if hints.get("readOnlyHint") is True:
            verb = next((t for t in _name_tokens(name) if t in _MUTATING_VERBS), None)
            if verb is not None:
                findings.append(
                    _finding(
                        "MCP-ANNOTATION-CONTRADICTS-NAME",
                        Severity.WARN,
                        f"tool {name!r} claims readOnlyHint=true while its name says {verb!r}. "
                        "The specification says annotations are untrusted unless the server is; "
                        "this is reported so a human decides, and no gate in this tool consults "
                        "the hint either way",
                        op,
                    )
                )

    if undeclared and operations:
        findings.append(
            Finding(
                rule_id="MCP-ANNOTATION-ABSENT",
                severity=Severity.INFO,
                message=(
                    f"{len(undeclared)} of {len(operations)} tools declare no annotations "
                    f"({', '.join(undeclared[:5])}"
                    f"{', ...' if len(undeclared) > 5 else ''}). The specification's default for "
                    "an undeclared destructiveHint is true, so a client honouring defaults must "
                    "treat every one of them as destructive"
                ),
            )
        )
    return findings


def _outlier_findings(operations: list[Operation]) -> list[Finding]:
    """One description far longer than its neighbours is where a payload fits.

    Both conditions are required. A manifest whose descriptions are uniformly
    long is a well-documented manifest, and a short one with a single long
    description is not suspicious at four hundred characters.
    """
    lengths = [(op, len(op.description or "")) for op in operations]
    sized = [length for _, length in lengths if length]
    if len(sized) < _MIN_TOOLS_FOR_OUTLIER:
        return []
    median = statistics.median(sized)
    if median <= 0:
        return []

    findings: list[Finding] = []
    for op, length in lengths:
        if length >= _OUTLIER_MIN_CHARS and length >= median * _OUTLIER_RATIO:
            findings.append(
                _finding(
                    "MCP-POISON-DESCRIPTION-OUTSIZED",
                    Severity.INFO,
                    f"tool {op.rpc_name or op.key!r} has a {length}-character description against "
                    f"a manifest median of {int(median)}; nothing is wrong with a long "
                    "description, but it is the part of a manifest nobody reads to the end",
                    op,
                )
            )
    return findings


def scan_mcp_manifest(service: Service) -> list[Finding]:
    """Poisoning and annotation-integrity findings for one manifest."""
    operations = list(service.operations)
    tool_names = {op.rpc_name for op in operations if op.rpc_name}

    findings: list[Finding] = []
    for op in operations:
        for text, where in _operation_texts(op):
            findings.extend(_scan_text(op, text, where, tool_names))
    findings.extend(_annotation_findings(operations))
    findings.extend(_outlier_findings(operations))
    return findings


__all__ = ["scan_mcp_manifest"]
