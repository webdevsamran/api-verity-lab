"""Whether a live MCP server asks anyone who they are.

Roughly seven thousand internet-exposed MCP servers had been catalogued by
early 2026 and about half of them required no authentication at all. That is
not a subtle misconfiguration: an anonymous caller reading `tools/list` gets a
complete map of what the server can do, and on a server that also serves the
calls, gets to do it.

`drift` already opens a connection and reads the tool list, so establishing the
posture costs at most one extra read-only request. What that request is depends
on what the caller supplied:

* **No credentials given, and the list came back.** Nothing further to ask.
  The run has already demonstrated that an unauthenticated caller gets the
  inventory.
* **Credentials given.** One more `tools/list` with the headers stripped, which
  is the only way to learn whether the credentials were doing anything. The
  interesting answer is not "anonymous access is refused" but "anonymous access
  returns the same twenty tools", and no amount of authenticated probing can
  distinguish those.

Severity follows the target classification rather than being flat. A laptop
serving its own MCP server without a token is the normal case and grading it
the same as a public host would train people to ignore the finding. The
classifier is `traffic/safety.py::classify_target`, the same one the replay
gate uses, and every finding names the classification it applied so a reader
can disagree with it.

Nothing here is a specification citation. The MCP authorization story has moved
more than once, and this module reports what the run observed -- what the
server returned, to which request, with which headers -- rather than which
clause of which revision that violates. "A 401 with no `WWW-Authenticate`
header leaves a client no way to discover where to authenticate" is true
regardless of what any revision says about it.
"""

from __future__ import annotations

from typing import Any

from apiverity.runtime.mcp_drift import McpFinding
from apiverity.specs.mcp.runner import (
    DEFAULT_MAX_PAGES,
    McpClient,
    McpHttpError,
    McpTransportError,
    Observation,
    list_tools,
)
from apiverity.traffic.safety import classify_target

#: Target classification -> severity for serving a tool inventory to an
#: unauthenticated caller. A local server doing it is a development loop; a
#: server on a public hostname doing it is the finding this module exists for.
_ANONYMOUS_SEVERITY = {
    "local": "INFO",
    "dev": "WARN",
    "staging": "WARN",
    "unknown": "WARN",
    "production": "ERROR",
}

_AUTH_HEADERS = ("authorization", "proxy-authorization", "x-api-key", "api-key")


def presents_credentials(headers: dict[str, str] | None) -> bool:
    """Whether these headers would authenticate the caller to anything."""
    return any(name.lower() in _AUTH_HEADERS for name in (headers or {}))


def _anonymous_headers(headers: dict[str, str] | None) -> dict[str, str]:
    return {k: v for k, v in (headers or {}).items() if k.lower() not in _AUTH_HEADERS}


def assess_auth_posture(
    endpoint: str,
    *,
    tools_served: int,
    headers: dict[str, str] | None = None,
    timeout: float = 10.0,
    max_pages: int = DEFAULT_MAX_PAGES,
    client_factory: Any = None,
    recorder: Any = None,
) -> tuple[list[McpFinding], dict[str, Any]]:
    """Findings plus the posture record, from at most one extra request."""
    classification = classify_target(endpoint).classification
    credentialed = presents_credentials(headers)
    posture: dict[str, Any] = {
        "credentials_presented": credentialed,
        "target_classification": classification,
        "anonymous_access": "not-established",
        "anonymous_tool_count": None,
        "challenge_header_present": None,
    }
    findings: list[McpFinding] = []

    if endpoint.startswith("http://") and classification != "local":
        findings.append(
            McpFinding(
                rule_id="MCP-AUTH-PLAINTEXT-TRANSPORT",
                severity="WARN",
                message=(
                    f"the endpoint is plain HTTP and classifies as {classification}; any "
                    "credential presented to it, and every tool schema it returns, crosses "
                    "the network in the clear"
                ),
            )
        )

    if not credentialed:
        # The run itself is the evidence. `tools_served` came back from a
        # request that carried no credential, so no second request is needed
        # and making one would be theatre.
        posture["anonymous_access"] = "served"
        posture["anonymous_tool_count"] = tools_served
        findings.append(
            McpFinding(
                rule_id="MCP-AUTH-ANONYMOUS-LIST",
                severity=_ANONYMOUS_SEVERITY.get(classification, "WARN"),
                message=(
                    f"the server returned all {tools_served} tools to a request carrying no "
                    f"credential; the target classifies as {classification}. An anonymous "
                    "caller has the complete map of what this server can do"
                ),
            )
        )
        return findings, posture

    anonymous_headers = _anonymous_headers(headers)

    def make_client() -> McpClient:
        if client_factory is not None:
            return client_factory(anonymous_headers)  # type: ignore[no-any-return]
        return McpClient(endpoint, timeout=timeout, headers=anonymous_headers, recorder=recorder)

    # The span of the anonymous probe, captured on the way out whether it
    # succeeded or failed: a refusal is evidence too, and the call that was
    # refused is the one a reader wants to look at.
    probe_span: str | None = None

    try:
        with make_client() as client:
            observation = Observation(endpoint=endpoint)
            try:
                anonymous_tools, _ = list_tools(client, observation, max_pages=max_pages)
            finally:
                probe_span = client.last_span_id
    except McpHttpError as exc:
        challenged = "www-authenticate" in exc.headers
        posture["anonymous_access"] = f"refused-{exc.status}"
        posture["challenge_header_present"] = challenged
        findings.append(
            McpFinding(
                span_id=probe_span,
                rule_id="MCP-AUTH-ENFORCED",
                severity="INFO",
                message=(
                    f"tools/list without credentials was refused with HTTP {exc.status}; "
                    "authentication is enforced on the inventory"
                ),
            )
        )
        if exc.status in (401, 403) and not challenged:
            findings.append(
                McpFinding(
                    span_id=probe_span,
                    rule_id="MCP-AUTH-NO-CHALLENGE",
                    severity="WARN",
                    message=(
                        f"the {exc.status} carried no `WWW-Authenticate` header, so a client "
                        "holding no credential has no way to discover where to obtain one; it "
                        "can only fail"
                    ),
                )
            )
        return findings, posture
    except McpTransportError as exc:
        # Not evidence either way. A connection that fails without credentials
        # may be enforcement or may be the network, and reporting a posture
        # from it would be asserting what the run did not establish.
        posture["anonymous_access"] = "indeterminate"
        findings.append(
            McpFinding(
                span_id=probe_span,
                rule_id="MCP-AUTH-INDETERMINATE",
                severity="INFO",
                message=(
                    f"the unauthenticated probe did not complete ({exc}); whether this server "
                    "requires credentials was not established by this run"
                ),
            )
        )
        return findings, posture

    count = len(anonymous_tools)
    posture["anonymous_access"] = "served"
    posture["anonymous_tool_count"] = count

    if count == 0:
        findings.append(
            McpFinding(
                span_id=probe_span,
                rule_id="MCP-AUTH-ENFORCED",
                severity="INFO",
                message=(
                    "tools/list without credentials succeeded but returned no tools; the "
                    "inventory is gated even though the method is not"
                ),
            )
        )
        return findings, posture

    if count == tools_served:
        message = (
            f"the server returned the same {count} tools with and without a credential. The "
            "credential this run presented changed nothing about what is exposed"
        )
    else:
        message = (
            f"the server returned {count} of {tools_served} tools to a request carrying no "
            "credential; part of the tool surface is public"
        )
    findings.append(
        McpFinding(
            span_id=probe_span,
            rule_id="MCP-AUTH-ANONYMOUS-LIST",
            severity=_ANONYMOUS_SEVERITY.get(classification, "WARN"),
            message=f"{message}. The target classifies as {classification}",
        )
    )
    return findings, posture


__all__ = ["assess_auth_posture", "presents_credentials"]
