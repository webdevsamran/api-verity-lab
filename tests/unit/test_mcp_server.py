"""apiverity exposed to an agent over MCP.

The surface itself is small and was designed in `docs/mcp-exposure.md` before
any of it existed. What these tests are really for is the three properties that
turn a one-shot CLI into a long-lived server safely, each of which fails
silently rather than loudly:

* provenance must not leak between calls -- the CLI keeps it in process
  globals, which is correct for one command per process and wrong for N;
* a path argument chosen by a model must be confined, and the *resolved* path
  is what has to reach the loader, because the loader re-reads the string;
* nothing may write to stdout, because stdout is the JSON-RPC frame stream.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import pytest

from apiverity.mcp.paths import PathRefused, resolve_within
from apiverity.mcp.server import handle, serve
from apiverity.mcp.tools import MCP_TOOLS_SCHEMA_VERSION, TOOLS, TOOLS_BY_NAME

_ROOT = Path(__file__).resolve().parents[2]


_ONES = (
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
)
_TENS = ("", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety")


def _word(n: int) -> str:
    """Spell a small number, so a growing CLI does not need this test edited.

    A hardcoded lookup broke twice in one session as commands were added --
    which is the guard working, but the guard should be about the document
    being wrong, not about the table being short.
    """
    if n < 20:
        return _ONES[n]
    tens, ones = divmod(n, 10)
    return _TENS[tens] + (f"-{_ONES[ones]}" if ones else "")


def _call(tool: str, arguments: dict[str, Any], *, root: Path = _ROOT) -> dict[str, Any]:
    reply = handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
        },
        root,
    )
    assert reply is not None
    return reply


# ------------------------------------------------------------------ surface


def test_the_documented_tool_count_matches_the_code() -> None:
    """docs/mcp-exposure.md said "Nine of the nineteen" over a table of seven.

    It said that for its whole life, in a repository whose stated rule is that
    counts are derived. Bound here to `len(TOOLS)` and to the table's own row
    count, so the prose, the table and the code cannot drift apart again.
    """
    from apiverity.cli.main import build_parser

    doc = (_ROOT / "docs" / "mcp-exposure.md").read_text(encoding="utf-8")
    exposed = _word(len(TOOLS)).capitalize()
    total = _word(len(build_parser()._subparsers._group_actions[0].choices))
    assert f"{exposed} of the {total} commands" in doc, (
        f"the document should say {exposed!r} of the {total!r} commands"
    )
    table_rows = [line for line in doc.splitlines() if line.startswith("| `") and "|" in line[3:]]
    assert len(table_rows) == len(TOOLS), (
        f"the table lists {len(table_rows)} tools; the code exposes {len(TOOLS)}"
    )


def test_the_exposed_surface_is_read_only_and_matches_the_assessment() -> None:
    """`docs/mcp-exposure.md` chose these seven; the code must not quietly grow."""
    assert [tool.name for tool in TOOLS] == [
        "validate",
        "diff",
        "breaking",
        "changelog",
        "coverage",
        "rules",
        "plugins",
    ]


@pytest.mark.parametrize(
    "excluded",
    ["drift", "replay", "baseline", "regression", "mock", "serve", "server-db", "export", "test"],
)
def test_commands_that_reach_out_or_hold_state_are_not_exposed(excluded: str) -> None:
    """The boundary is the one SAFETY_MODEL.md already draws.

    An agent must not be able to send traffic to an arbitrary base URL because
    a prompt told it to, and a tool call that leaves a process running is not a
    tool call.
    """
    assert excluded not in TOOLS_BY_NAME


def test_every_tool_declares_itself_read_only() -> None:
    for tool in TOOLS:
        annotations = tool.manifest_entry()["annotations"]
        assert annotations["readOnlyHint"] is True
        assert annotations["destructiveHint"] is False


def test_tools_list_is_a_wellformed_modern_list_result() -> None:
    reply = handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, _ROOT)
    assert reply is not None
    result = reply["result"]
    # The fields this project's own drift checker reports other servers for
    # omitting. It would be poor form to omit them here.
    assert "ttlMs" in result and "cacheScope" in result
    for entry in result["tools"]:
        assert isinstance(entry["name"], str) and entry["name"]
        assert entry["inputSchema"]["type"] == "object"
    assert result["_meta"]["dev.apiverity/toolsSchemaVersion"] == MCP_TOOLS_SCHEMA_VERSION


def test_the_server_can_govern_its_own_manifest() -> None:
    """The tool surface is itself a contract this engine reads.

    Not a stunt: it is the cheapest possible check that what the server
    advertises is a well-formed MCP manifest.
    """
    from apiverity.specs.mcp import load_manifest

    reply = handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, _ROOT)
    assert reply is not None
    service, findings = load_manifest(reply["result"])
    assert [op.rpc_name for op in service.operations] == [t.name for t in TOOLS]
    assert [f for f in findings if f.severity.value == "ERROR"] == []


# -------------------------------------------------------- path confinement


def test_a_path_outside_the_root_is_refused() -> None:
    reply = _call("validate", {"spec": "../../../etc/passwd"})
    assert reply["result"]["isError"] is True
    assert "outside the configured root" in reply["result"]["content"][0]["text"]


def test_a_remote_source_is_refused() -> None:
    """`specs.read_source` accepts http(s) and would fetch it.

    In a server documented as making no network calls, that is server-side
    request forgery reachable through an argument a model chooses.
    """
    reply = _call("validate", {"spec": "https://evil.example.com/spec.yaml"})
    assert reply["result"]["isError"] is True
    assert "remote sources are not accepted" in reply["result"]["content"][0]["text"]


def test_a_sibling_directory_sharing_a_prefix_is_refused(tmp_path: Path) -> None:
    """`/srv/rootkit` starts with `/srv/root` as text and is a different place."""
    root = tmp_path / "root"
    root.mkdir()
    sibling = tmp_path / "rootkit"
    sibling.mkdir()
    (sibling / "secret.yaml").write_text("openapi: 3.0.0", encoding="utf-8")
    with pytest.raises(PathRefused):
        resolve_within(root, str(sibling / "secret.yaml"))


def test_the_resolved_path_is_what_reaches_the_loader(monkeypatch: Any) -> None:
    """Confinement that stops at the check is not confinement.

    `detect_and_load` reads the caller's string twice -- once to sniff the
    format and again inside the winning plugin -- so passing the original
    string onward would leave both reads unconfined.
    """
    seen: list[str] = []
    import apiverity.specs.loader as loader_module

    original = loader_module.detect_and_load

    def spy(source: str, registry: Any = None) -> Any:
        seen.append(source)
        return original(source, registry)

    monkeypatch.setattr(loader_module, "detect_and_load", spy)
    _call("validate", {"spec": "fixtures/mcp/tools_v1.json"})

    assert seen, "the loader was never called"
    for source in seen:
        assert Path(source).is_absolute(), f"loader received an unresolved path: {source!r}"
        assert Path(source).resolve().is_relative_to(_ROOT)


def test_an_error_never_discloses_an_absolute_path() -> None:
    """Loader errors embed the resolved path; echoing them leaks the layout."""
    reply = _call("validate", {"spec": "no/such/file.yaml"})
    text = reply["result"]["content"][0]["text"]
    assert reply["result"]["isError"] is True
    assert str(_ROOT) not in text
    assert text == "no such file: no/such/file.yaml"


def test_a_file_that_is_not_a_contract_says_so_without_a_traceback() -> None:
    reply = _call("validate", {"spec": "fixtures/mcp/not-a-manifest.json"})
    assert reply["result"]["isError"] is True
    assert "not a contract in any recognized format" in reply["result"]["content"][0]["text"]


# ------------------------------------------------------- process isolation


def test_provenance_does_not_leak_between_calls() -> None:
    """The reason handlers may not use the CLI's emit path.

    `cli/commands/common.py` keeps `_LAST_SPEC` and `_LAST_PROTOCOL` in process
    globals set by `_load`. In a server, a `rules` call -- which loads no
    contract at all -- would otherwise report the previous caller's spec and
    protocol as its own provenance.
    """
    first = _call("validate", {"spec": "fixtures/mcp/tools_v1.json"})
    assert first["result"]["structuredContent"]["protocol_version"] == "mcp"

    second = _call("rules", {})
    provenance = second["result"]["structuredContent"]
    # "unknown" rather than None is the repo's own rule -- a field that cannot
    # be derived says so. What must never happen is inheriting "mcp" from the
    # call before it.
    assert provenance.get("protocol_version") != "mcp"
    assert provenance.get("protocol_version") in (None, "unknown")
    assert set(str(provenance.get("contract_hash", ""))) <= {"0"}, (
        "a call that loaded no contract reported a contract hash"
    )

    third = _call("validate", {"spec": "fixtures/apis/versioned/v1.yaml"})
    assert third["result"]["structuredContent"]["protocol_version"] == "openapi"


def test_a_handler_failure_does_not_take_the_server_down() -> None:
    """`_load` calls `sys.exit` on a bad path; a server must survive one."""
    reply = _call("diff", {"old": "nope.yaml", "new": "also-nope.yaml"})
    assert reply["result"]["isError"] is True
    # And the next call still works.
    assert _call("rules", {})["result"]["structuredContent"]["command"] == "rules"


# --------------------------------------------------------------- framing


def test_stdout_carries_only_jsonrpc_frames() -> None:
    """stdout *is* the frame stream. One stray print corrupts the session."""
    requests = "\n".join(
        json.dumps(r)
        for r in [
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "rules", "arguments": {}},
            },
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "validate", "arguments": {"spec": "nope.yaml"}},
            },
        ]
    )
    out = io.StringIO()
    serve(_ROOT, io.StringIO(requests), out)

    lines = [line for line in out.getvalue().splitlines() if line.strip()]
    assert len(lines) == 3
    for line in lines:
        assert json.loads(line)["jsonrpc"] == "2.0"


def test_an_unknown_tool_is_a_protocol_error_not_a_tool_failure() -> None:
    reply = _call("drift", {})
    assert "error" in reply
    assert reply["error"]["code"] == -32601


def test_a_notification_gets_no_reply() -> None:
    """JSON-RPC: a request with no id expects no response."""
    assert handle({"jsonrpc": "2.0", "method": "notifications/whatever"}, _ROOT) is None


def test_malformed_json_produces_a_parse_error_frame_not_a_crash() -> None:
    out = io.StringIO()
    serve(_ROOT, io.StringIO("{not json\n"), out)
    assert json.loads(out.getvalue())["error"]["code"] == -32700
