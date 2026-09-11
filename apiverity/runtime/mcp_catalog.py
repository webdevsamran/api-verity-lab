"""Catalogue entries for every MCP rule.

MCP is this project's wedge — the protocol nothing else governs the way this
does — and not one of its fifty-one rules could be looked up. `apiverity explain
MCP-POISON-INSTRUCTION` answered *"no rule with id ..."* about the rule that
exists because a tool description is executable text.

That gap mattered more here than anywhere else. `BRK-RESP-FIELD-REMOVED` is
legible from its name; `MCP-CONF-LIST-UNSTABLE` is not, and neither is
`MCP-AUTH-INDETERMINATE`. A reader who cannot tell those two apart cannot act
on either.

## Six families, and they answer different questions

* **Manifest** — is this document a well-formed tool surface?
* **Poisoning** — is a description instructing the agent rather than describing
  the tool? The description is what an agent routes on, which makes it the one
  field a schema cannot constrain and an attacker most wants.
* **Runtime and conformance** — does the running server serve what the manifest
  declares, and does it obey the specification?
* **Authentication** — will this server hand its tool list to a stranger?
* **Inventory and shadow servers** — what is this machine configured to reach?
* **Lockfile** — did the tool surface change without anyone reviewing it?

## Three of these report the absence of an answer

`MCP-AUTH-INDETERMINATE`, `MCP-PROTOCOL-ERA-UNOBSERVED` and
`MCP-DRIFT-PAGINATION-CAPPED` say that a probe did not establish something.
They are not findings about the server; they are findings about the run, and
their remediation says how to get an answer rather than what to fix. Reporting
them as faults would be the tool claiming a measurement it did not make;
dropping them would let an unfinished run read as a clean one.
"""

from __future__ import annotations

from apiverity.core.model import Severity
from apiverity.rules.check_catalog import CheckRuleSpec, spec

_MANIFEST = "MCP manifests"
_POISON = "MCP tool poisoning"
_RUNTIME = "MCP runtime and conformance"
_AUTH = "MCP authentication"
_INVENTORY = "MCP inventory"
_LOCK = "MCP lockfile"

MCP_MANIFEST_CATALOG: dict[str, CheckRuleSpec] = dict(
    [
        spec(
            "MCP-TOOL-NAME-MISSING",
            Severity.ERROR,
            "A tool in the manifest has no `name`, which the specification requires.",
            "Give it one. `tools/call` dispatches on the name, so a nameless tool is one no "
            "agent can invoke and no diff can track.",
            family=_MANIFEST,
        ),
        spec(
            "MCP-TOOL-INVALID",
            Severity.ERROR,
            "An entry in the tools list is not an object.",
            "Fix the document. A non-object entry is skipped entirely, which quietly "
            "shrinks the surface every other rule sees.",
            family=_MANIFEST,
        ),
        spec(
            "MCP-TOOL-DUPLICATE",
            Severity.ERROR,
            "A tool name is declared more than once.",
            "Rename or remove one. `tools/call` dispatches on the name, so which of the two "
            "an agent reaches is the server's implementation detail rather than your "
            "decision.",
            family=_MANIFEST,
        ),
        spec(
            "MCP-INPUT-SCHEMA-MISSING",
            Severity.ERROR,
            "A tool declares no `inputSchema`, which the specification makes mandatory.",
            'Declare one, even `{"type": "object"}`. Without it there is nothing to '
            "validate a call against, and an agent constructs arguments from the "
            "description alone.",
            family=_MANIFEST,
        ),
        spec(
            "MCP-INPUT-SCHEMA-NOT-OBJECT",
            Severity.ERROR,
            "A tool's `inputSchema` declares a type other than `object`.",
            "Make it an object schema. Tool arguments are named, so anything else cannot "
            "describe a call.",
            family=_MANIFEST,
        ),
        spec(
            "MCP-LIST-RESULT-INCOMPLETE",
            Severity.WARN,
            "The envelope carries `resultType` without both `ttlMs` and `cacheScope`.",
            "Declare all three or none. A partial caching envelope leaves a client to guess "
            "how long the tool list is good for.",
            family=_MANIFEST,
        ),
        spec(
            "MCP-MANIFEST-TRUNCATED",
            Severity.WARN,
            "This is one page of a paginated `tools/list`: `nextCursor` is set.",
            "Capture the remaining pages before diffing. Every tool past this page reads as "
            "removed, which is a very loud way to discover pagination.",
            family=_MANIFEST,
        ),
        spec(
            "MCP-PROTOCOL-ERA-UNOBSERVED",
            Severity.INFO,
            "Which protocol era this manifest came from was not established.",
            "Nothing, unless era matters to you -- capture the manifest with the negotiated "
            "version recorded. A saved document carries no record of the handshake that "
            "produced it, and guessing would be inventing a fact.",
            family=_MANIFEST,
        ),
        spec(
            "MCP-SCHEMA-KEYWORD-UNMODELED",
            Severity.WARN,
            "A JSON Schema keyword in a tool's schema is not represented in the normalized model.",
            "Nothing to fix in the manifest. It is reported so that what the rules cannot "
            "see is visible, rather than being assumed absent.",
            family=_MANIFEST,
        ),
    ]
)

MCP_POISON_CATALOG: dict[str, CheckRuleSpec] = dict(
    [
        spec(
            "MCP-POISON-INSTRUCTION",
            Severity.WARN,
            "A tool description contains a sentence addressed to the agent rather than a "
            "description of the tool.",
            "Rewrite it to describe what the tool does. In MCP the description is what the "
            "agent routes on, so a sentence aimed at the agent is executable text, not "
            "documentation.",
            family=_POISON,
        ),
        spec(
            "MCP-POISON-CREDENTIAL-PATH",
            Severity.ERROR,
            "A tool description names a credential location in prose.",
            "Declare what the tool reads in `inputSchema`, where a caller can see it. A "
            "tool that legitimately reads a credential says so in its schema; one that "
            "points the agent at a path in prose is asking for something nobody approved.",
            family=_POISON,
        ),
        spec(
            "MCP-POISON-INVISIBLE-TEXT",
            Severity.ERROR,
            "A tool description carries characters that reach the model and not the human "
            "reviewing the manifest -- zero-width spaces, direction overrides, unicode tag "
            "characters.",
            "Remove them. There is no legitimate reason for text the reviewer cannot see "
            "and the model can, which is the only reason to put it there.",
            family=_POISON,
        ),
        spec(
            "MCP-POISON-HIDDEN-MARKUP",
            Severity.WARN,
            "A tool description hides text inside markup -- an HTML comment, say.",
            "Remove it. A client rendering the description as markdown shows nothing while "
            "the model reads all of it.",
            family=_POISON,
        ),
        spec(
            "MCP-POISON-CROSS-TOOL",
            Severity.WARN,
            "A tool description names another tool alongside an instruction.",
            "Keep each description about its own tool. A description that changes how a "
            "*different* tool is used is a change nobody reviewing that tool would see.",
            family=_POISON,
        ),
        spec(
            "MCP-POISON-DESCRIPTION-OUTSIZED",
            Severity.INFO,
            "A tool description is far longer than the rest of the manifest's.",
            "Nothing on its own -- length is not an attack. It is a place to look, because "
            "an injected payload has to go somewhere and a description is where it fits.",
            family=_POISON,
        ),
        spec(
            "MCP-ANNOTATION-CONTRADICTORY",
            Severity.WARN,
            "A tool declares `readOnlyHint` and `destructiveHint` both true.",
            "Pick one. The specification defines `destructiveHint` only when `readOnlyHint` "
            "is false, so these say two incompatible things and a client believing either "
            "is guessing which.",
            family=_POISON,
        ),
        spec(
            "MCP-ANNOTATION-CONTRADICTS-NAME",
            Severity.WARN,
            "A tool claims `readOnlyHint` while its name says otherwise.",
            "Check which is true and fix the other. The specification says annotations are "
            "untrusted unless the server is, so this is reported for a human to decide -- "
            "no gate in this tool consults the hint either way.",
            family=_POISON,
        ),
        spec(
            "MCP-ANNOTATION-ABSENT",
            Severity.INFO,
            "Some tools declare no annotations at all.",
            "Declare them. The specification's default for an undeclared `destructiveHint` "
            "is true, so a client honouring defaults must treat every one of those tools as "
            "destructive.",
            family=_POISON,
        ),
    ]
)

MCP_RUNTIME_CATALOG: dict[str, CheckRuleSpec] = dict(
    [
        spec(
            "MCP-DRIFT-TOOL-MISSING",
            Severity.ERROR,
            "A tool declared in the manifest is not served by the running server.",
            "Deploy it or take it out of the manifest. An agent planning against the "
            "manifest will call a tool that is not there.",
            produced_by="drift",
            family=_RUNTIME,
        ),
        spec(
            "MCP-DRIFT-TOOL-UNDECLARED",
            Severity.WARN,
            "A tool is served and is absent from the manifest.",
            "Add it, or stop serving it. Agents will discover it from `tools/list` and use "
            "it, which means a capability reached production without review.",
            produced_by="drift",
            family=_RUNTIME,
        ),
        spec(
            "MCP-DRIFT-SCHEMA",
            Severity.ERROR,
            "A served tool's schema differs from the one the manifest declares.",
            "The finding names the change. The manifest is what a reviewer approved and the "
            "server is what agents call.",
            produced_by="drift",
            family=_RUNTIME,
        ),
        spec(
            "MCP-DRIFT-SCHEMA-COMPATIBLE",
            Severity.WARN,
            "A served tool's schema differs from the declared one in a way no breaking rule "
            "objected to.",
            "Update the manifest so it describes what is served. The difference breaks "
            "nobody today; the manifest being wrong about the server is the thing that "
            "compounds.",
            produced_by="drift",
            family=_RUNTIME,
        ),
        spec(
            "MCP-DRIFT-ANNOTATION",
            Severity.WARN,
            "A served tool's annotation hint differs from the declared one.",
            "Reconcile them. Annotations are what a client uses to decide whether to ask a "
            "human first.",
            produced_by="drift",
            family=_RUNTIME,
        ),
        spec(
            "MCP-DRIFT-LEGACY-SERVER",
            Severity.INFO,
            "The server negotiated a pre-2026-07-28 protocol version.",
            "Nothing, if that is expected. It is reported because the older era has "
            "different requirements, and a rule written for the new one would be wrong "
            "about this server.",
            produced_by="drift",
            family=_RUNTIME,
        ),
        spec(
            "MCP-DRIFT-PROTOCOL-UNSUPPORTED",
            Severity.ERROR,
            "The server negotiated a protocol version this tool cannot speak.",
            "Nothing was checked past the handshake. Upgrade one side, or capture a "
            "manifest and check that instead.",
            produced_by="drift",
            family=_RUNTIME,
        ),
        spec(
            "MCP-DRIFT-PAGINATION-CAPPED",
            Severity.WARN,
            "`tools/list` was still returning a cursor when the page limit was reached.",
            "Raise `--max-pages`. Everything past the cap was not read, so tools there are "
            "neither confirmed present nor reported missing.",
            produced_by="drift",
            family=_RUNTIME,
        ),
        spec(
            "MCP-DRIFT-CALL-OUTPUT-SCHEMA",
            Severity.ERROR,
            "A tool's `structuredContent` violates the `outputSchema` it declares.",
            "Fix the handler or the schema. An agent parsing the result against the "
            "declared shape gets something else.",
            produced_by="drift",
            family=_RUNTIME,
        ),
        spec(
            "MCP-DRIFT-CALL-NO-STRUCTURED-CONTENT",
            Severity.WARN,
            "A tool declares an `outputSchema` and returned no `structuredContent`.",
            "Return it, or drop the schema. A declared output shape that never arrives is a "
            "promise the client cannot use.",
            produced_by="drift",
            family=_RUNTIME,
        ),
        spec(
            "MCP-DRIFT-CALL-ERROR-SHAPE",
            Severity.WARN,
            "`tools/call` returned a JSON-RPC error rather than a tool result.",
            "Tool failures belong in the result with `isError`, not in the transport. A "
            "protocol-level error is for a call that could not be dispatched.",
            produced_by="drift",
            family=_RUNTIME,
        ),
        spec(
            "MCP-CALL-RESULT-CREDENTIAL",
            Severity.ERROR,
            "A tool's result contains something shaped like a credential.",
            "Rotate it if it is one, and stop returning it. A tool result goes into the "
            "model's context, which is the last place a secret should be.",
            produced_by="drift",
            family=_RUNTIME,
        ),
        spec(
            "MCP-CONF-TOOL-NAME-MISSING",
            Severity.ERROR,
            "A served tool has no `name`, which the specification requires.",
            "Fix the server. Nothing can call a tool that has no name.",
            produced_by="drift",
            family=_RUNTIME,
        ),
        spec(
            "MCP-CONF-INPUT-SCHEMA-MISSING",
            Severity.ERROR,
            "A served tool has no `inputSchema`, which the specification requires.",
            "Fix the server. An agent with no schema builds arguments out of the description.",
            produced_by="drift",
            family=_RUNTIME,
        ),
        spec(
            "MCP-CONF-INPUT-SCHEMA-NOT-OBJECT",
            Severity.ERROR,
            "A served tool's `inputSchema` is not an object schema.",
            "Fix the server. Tool arguments are named, so no other type can describe them.",
            produced_by="drift",
            family=_RUNTIME,
        ),
        spec(
            "MCP-CONF-SCHEMA-DIALECT",
            Severity.INFO,
            "A served tool declares a JSON Schema dialect other than the one MCP specifies.",
            "Usually nothing -- it is reported because a validator honouring the declared "
            "dialect may accept or reject arguments differently from one assuming MCP's.",
            produced_by="drift",
            family=_RUNTIME,
        ),
        spec(
            "MCP-CONF-LIST-RESULT-INCOMPLETE",
            Severity.WARN,
            "A `tools/list` result omitted a key the specification requires on it.",
            "Fix the server. A client written to the specification reads that key.",
            produced_by="drift",
            family=_RUNTIME,
        ),
        spec(
            "MCP-CONF-LIST-UNSTABLE",
            Severity.ERROR,
            "Two `tools/list` calls on separate connections returned different tool sets.",
            "Make the tool set the same for every connection. The specification says it MUST "
            "NOT vary by connection, and an agent that saw one set and called from the other "
            "gets a tool that is not there.",
            produced_by="drift",
            family=_RUNTIME,
        ),
        spec(
            "MCP-CONF-LIST-ORDER-NONDETERMINISTIC",
            Severity.INFO,
            "`tools/list` returned the same tools in a different order across two calls.",
            "Nothing is broken -- order is not specified. It is reported because a lockfile "
            "or a diff taken across two runs will show noise that is not change.",
            produced_by="drift",
            family=_RUNTIME,
        ),
        spec(
            "MCP-CONF-CALL-CONTENT-BLOCK-UNKNOWN",
            Severity.WARN,
            "A tool result carried a content block of a type the specification does not define.",
            "Use a defined block type. A client that does not recognise it will drop it, so "
            "the part of the answer it carries silently disappears.",
            produced_by="drift",
            family=_RUNTIME,
        ),
    ]
)

MCP_AUTH_CATALOG: dict[str, CheckRuleSpec] = dict(
    [
        spec(
            "MCP-AUTH-ANONYMOUS-LIST",
            Severity.ERROR,
            "The server returned its whole tool list to a request carrying no credentials.",
            "Require authentication on `tools/list`. The tool list is the map of what this "
            "server can be made to do, and roughly half of the internet-exposed MCP servers "
            "catalogued in 2026 handed it to anybody who asked.",
            produced_by="drift",
            family=_AUTH,
        ),
        spec(
            "MCP-AUTH-ENFORCED",
            Severity.INFO,
            "An unauthenticated `tools/list` was refused.",
            "Nothing, this is the good outcome, and it is recorded so a clean run still "
            "shows what was established.",
            produced_by="drift",
            family=_AUTH,
        ),
        spec(
            "MCP-AUTH-NO-CHALLENGE",
            Severity.WARN,
            "The refusal carried no `WWW-Authenticate` header.",
            "Send one. Without it a client cannot tell what kind of credential to get, so "
            "it retries with whatever it already has.",
            produced_by="drift",
            family=_AUTH,
        ),
        spec(
            "MCP-AUTH-INDETERMINATE",
            Severity.INFO,
            "The unauthenticated probe did not complete, so whether this server requires "
            "credentials was not established.",
            "Re-run when the server is reachable. This is the absence of an answer, not an "
            "answer -- and reporting it as either would be a claim nobody measured.",
            produced_by="drift",
            family=_AUTH,
        ),
        spec(
            "MCP-AUTH-PLAINTEXT-TRANSPORT",
            Severity.WARN,
            "The endpoint is plain HTTP.",
            "Use TLS. Every tool call, argument and result on this connection is readable by "
            "anything on the path, including the credentials that authorise them.",
            produced_by="drift",
            family=_AUTH,
        ),
    ]
)

MCP_INVENTORY_CATALOG: dict[str, CheckRuleSpec] = dict(
    [
        spec(
            "MCP-SHADOW-SERVER",
            Severity.ERROR,
            "A configured server is not on the approved list.",
            "Approve it or remove it. A server nobody approved is a set of tools nobody "
            "reviewed, reachable by every agent on this machine.",
            produced_by="mcp-inventory",
            family=_INVENTORY,
        ),
        spec(
            "MCP-SHADOW-INLINE-CREDENTIAL",
            Severity.ERROR,
            "A server configuration carries a literal credential value.",
            "Move it to the environment or a secret store and rotate it. A client config "
            "file is synced, backed up and frequently committed.",
            produced_by="mcp-inventory",
            family=_INVENTORY,
        ),
        spec(
            "MCP-SHADOW-FETCHED-AT-LAUNCH",
            Severity.WARN,
            "A server is started by a command that fetches its code at launch.",
            "Pin the version, or vendor the package. The code that starts tomorrow is "
            "whatever the registry serves tomorrow, which is the supply-chain shape behind "
            "OWASP MCP04.",
            produced_by="mcp-inventory",
            family=_INVENTORY,
        ),
        spec(
            "MCP-SHADOW-PLAINTEXT-URL",
            Severity.WARN,
            "A server is configured over plain HTTP.",
            "Use HTTPS. Every tool call to it, and every result from it, is readable on the path.",
            produced_by="mcp-inventory",
            family=_INVENTORY,
        ),
        spec(
            "MCP-INVENTORY-UNCONFIGURED",
            Severity.INFO,
            "An approved server was not found in any configuration this run read.",
            "Nothing, if it is meant to be available and unused. It is reported so the "
            "approved list does not quietly accumulate entries nobody has.",
            produced_by="mcp-inventory",
            family=_INVENTORY,
        ),
        spec(
            "MCP-INVENTORY-CONFIG-UNREADABLE",
            Severity.WARN,
            "A configuration file exists and could not be read, so the servers it "
            "configures were not inventoried.",
            "Fix the permissions or the syntax. An unread config is a set of servers this "
            "run says nothing about, which is not the same as none.",
            produced_by="mcp-inventory",
            family=_INVENTORY,
        ),
        spec(
            "MCP-INVENTORY-UNREADABLE",
            Severity.ERROR,
            "A source named on the command line could not be read.",
            "Check the path. Named explicitly and missing is an error, where a config file "
            "this tool merely knows about is not.",
            produced_by="mcp-inventory",
            family=_INVENTORY,
        ),
    ]
)

MCP_LOCK_CATALOG: dict[str, CheckRuleSpec] = dict(
    [
        spec(
            "MCP-LOCK-TOOL-ADDED",
            Severity.ERROR,
            "A served tool is not in the baseline lockfile.",
            "Review the tool and re-lock. Adding a tool broadens what every agent using "
            "this server can be talked into doing, which is a change worth a review even "
            "when the tool is benign.",
            produced_by="mcp-lock",
            family=_LOCK,
        ),
        spec(
            "MCP-LOCK-SIGNATURE-INVALID",
            Severity.ERROR,
            "The lockfile's signature does not match its contents.",
            "Do not trust this lock. It was edited by something that did not have the key, "
            "which is the case the signature exists for.",
            produced_by="mcp-lock",
            family=_LOCK,
        ),
        spec(
            "MCP-LOCK-SIGNATURE-UNVERIFIED",
            Severity.WARN,
            "The lockfile is signed and the key is not available here, so the signature was "
            "not checked.",
            "Set the key environment variable. An unverified signature offers exactly as "
            "much assurance as no signature, and looks like more.",
            produced_by="mcp-lock",
            family=_LOCK,
        ),
        spec(
            "MCP-LOCK-UNSIGNED",
            Severity.INFO,
            "The lockfile carries no signature.",
            "Sign it if the lock matters. Unsigned, an edit to it is indistinguishable from "
            "a legitimate re-lock -- which makes the baseline as trustworthy as the file "
            "permissions on it.",
            produced_by="mcp-lock",
            family=_LOCK,
        ),
    ]
)


def merged() -> dict[str, CheckRuleSpec]:
    """Every MCP family, for the one place that merges catalogues."""
    out: dict[str, CheckRuleSpec] = {}
    for family in (
        MCP_MANIFEST_CATALOG,
        MCP_POISON_CATALOG,
        MCP_RUNTIME_CATALOG,
        MCP_AUTH_CATALOG,
        MCP_INVENTORY_CATALOG,
        MCP_LOCK_CATALOG,
    ):
        out.update(family)
    return out


__all__ = [
    "MCP_AUTH_CATALOG",
    "MCP_INVENTORY_CATALOG",
    "MCP_LOCK_CATALOG",
    "MCP_MANIFEST_CATALOG",
    "MCP_POISON_CATALOG",
    "MCP_RUNTIME_CATALOG",
    "merged",
]
