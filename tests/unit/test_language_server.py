"""The language server, driven over its own wire format.

A server tested by calling its handlers directly is a server whose framing has
never run. The framing is where a hand-rolled LSP goes wrong, and the symptom
is an editor that hangs with nothing in any log — so these tests speak the
protocol: real `Content-Length` frames, in and out.

The subprocess test at the bottom goes further and runs `apiverity lsp` the way
an editor launches it, because stdout *is* the protocol stream and a single
stray `print` anywhere in the import path would break every client.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from apiverity.lsp import protocol
from apiverity.lsp.diagnostics import analyze, diagnostics, lintable
from apiverity.lsp.server import LanguageServer, uri_to_path

_ROOT = Path(__file__).resolve().parents[2]
_SPEC = _ROOT / "fixtures" / "apis" / "crud" / "openapi.yaml"


def _frame(message: dict[str, Any]) -> bytes:
    body = json.dumps(message).encode("utf-8")
    return b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body


def _drive(messages: list[dict[str, Any]], *, debounce: float = 0.0) -> list[dict[str, Any]]:
    """Feed messages through a real server and collect what it wrote back."""
    reader = io.BytesIO(b"".join(_frame(m) for m in messages))
    writer = io.BytesIO()
    LanguageServer(reader, writer, debounce=debounce).serve()

    writer.seek(0)
    out = []
    while True:
        message = protocol.read_message(writer)
        if message is None:
            break
        out.append(message)
    return out


def _open(uri: str, text: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "method": "textDocument/didOpen",
        "params": {"textDocument": {"uri": uri, "languageId": "yaml", "text": text}},
    }


def _uri(path: Path) -> str:
    return path.as_uri()


# -- framing --------------------------------------------------------------


def test_content_length_counts_bytes_not_characters() -> None:
    """A message quoting a contract's unicode desynchronises the stream from
    that frame onward if the length is computed from `len(str)`."""
    stream = io.BytesIO()
    protocol.write_message(stream, {"m": "café — ünïcode"})
    header, body = stream.getvalue().split(b"\r\n\r\n", 1)
    declared = int(header.split(b":")[1].strip())
    assert declared == len(body)
    assert declared != len(body.decode("utf-8"))


def test_a_frame_written_is_a_frame_read() -> None:
    stream = io.BytesIO()
    for message in ({"a": 1}, {"b": "ü"}, {"c": [1, 2, 3]}):
        protocol.write_message(stream, message)
    stream.seek(0)
    assert [protocol.read_message(stream) for _ in range(3)] == [
        {"a": 1},
        {"b": "ü"},
        {"c": [1, 2, 3]},
    ]


def test_end_of_stream_is_not_an_error() -> None:
    """An editor that quits closes the pipe without `shutdown`. Treating that
    as a crash would put an error in the log on every normal exit."""
    assert protocol.read_message(io.BytesIO(b"")) is None


def test_a_header_with_no_content_length_is_refused() -> None:
    with pytest.raises(protocol.ProtocolError, match="no Content-Length"):
        protocol.read_message(io.BytesIO(b"X-Thing: 1\r\n\r\n{}"))


def test_a_truncated_body_is_refused_rather_than_parsed_short() -> None:
    with pytest.raises(protocol.ProtocolError, match="stream ended after"):
        protocol.read_message(io.BytesIO(b"Content-Length: 40\r\n\r\n{}"))


# -- lifecycle ------------------------------------------------------------


def test_initialize_declares_what_the_server_actually_does() -> None:
    out = _drive([{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}])
    capabilities = out[0]["result"]["capabilities"]
    assert capabilities["hoverProvider"] is True
    assert capabilities["textDocumentSync"]["openClose"] is True
    assert out[0]["result"]["serverInfo"]["name"] == "apiverity"


def test_an_unknown_request_is_answered_and_an_unknown_notification_is_not() -> None:
    """The specification requires both. A request left unanswered hangs the
    client forever; a notification answered with an error confuses it."""
    out = _drive(
        [
            {"jsonrpc": "2.0", "id": 7, "method": "textDocument/formatting", "params": {}},
            {"jsonrpc": "2.0", "method": "textDocument/willSave", "params": {}},
        ]
    )
    assert len(out) == 1
    assert out[0]["id"] == 7
    assert out[0]["error"]["code"] == protocol.METHOD_NOT_FOUND


def test_a_handler_that_raises_does_not_take_the_server_down() -> None:
    out = _drive(
        [
            {"jsonrpc": "2.0", "id": 1, "method": "textDocument/hover", "params": None},
            {"jsonrpc": "2.0", "id": 2, "method": "initialize", "params": {}},
        ]
    )
    # Whatever the first one did, the second still got an answer.
    assert [m.get("id") for m in out][-1] == 2


# -- diagnostics ----------------------------------------------------------


def test_a_real_contract_produces_the_rules_the_cli_produces() -> None:
    """Not a reimplementation: the same loader and the same checks, so a rule
    added to `validate` appears in the editor without anything here changing."""
    out = _drive([_open(_uri(_SPEC), _SPEC.read_text(encoding="utf-8"))])
    published = [m for m in out if m.get("method") == "textDocument/publishDiagnostics"]
    assert published, "nothing was published for a contract full of findings"

    codes = {d["code"] for d in published[0]["params"]["diagnostics"]}
    from apiverity.security import run_security_checks
    from apiverity.specs.loader import detect_and_load

    service, findings, _ = detect_and_load(str(_SPEC))
    expected = {f.rule_id for f in list(findings) + list(run_security_checks(service))}
    assert codes == expected


def test_every_diagnostic_has_a_range_somebody_can_see() -> None:
    """A zero-width range renders as a caret between two characters that the
    reader has to hunt for."""
    text = _SPEC.read_text(encoding="utf-8")
    for diagnostic in diagnostics(str(_SPEC), text, _uri(_SPEC)):
        start, end = diagnostic["range"]["start"], diagnostic["range"]["end"]
        assert (end["line"], end["character"]) > (start["line"], start["character"])


def test_no_diagnostic_points_past_the_end_of_the_document() -> None:
    """A range beyond the buffer is silently dropped by some clients and draws
    on the wrong line in others."""
    text = _SPEC.read_text(encoding="utf-8")
    lines = text.split("\n")
    for diagnostic in diagnostics(str(_SPEC), text, _uri(_SPEC)):
        line = diagnostic["range"]["start"]["line"]
        assert 0 <= line < len(lines)
        assert diagnostic["range"]["end"]["character"] <= len(lines[line]) + 1


def test_the_rule_id_is_the_code_and_links_to_the_catalogue() -> None:
    text = _SPEC.read_text(encoding="utf-8")
    first = diagnostics(str(_SPEC), text, _uri(_SPEC))[0]
    assert first["code"].isupper()
    assert first["code"].lower() in first["codeDescription"]["href"]


def test_a_document_that_will_not_parse_says_so_rather_than_reporting_nothing() -> None:
    """An empty diagnostic list means "this is fine". A file that will not load
    is not fine, and somebody mid-edit should see why."""
    found = diagnostics(str(_SPEC), "openapi: 3.0.0\npaths:\n  - [unclosed", "file:///x.yaml")
    assert len(found) == 1
    assert found[0]["code"] == "PARSE"
    assert found[0]["severity"] == 1


def test_analysis_reads_the_buffer_not_the_file_on_disk(tmp_path: Path) -> None:
    """The whole point of a language server. A version on disk that differs
    from the screen would mean diagnostics describing a document nobody has."""
    path = tmp_path / "openapi.yaml"
    path.write_text(_SPEC.read_text(encoding="utf-8"), encoding="utf-8")
    findings, failure = analyze(str(path), "not: a contract\n")
    assert failure is not None or not findings
    # And the file on disk is untouched.
    assert "openapi" in path.read_text(encoding="utf-8")


def test_the_directory_is_left_clean(tmp_path: Path) -> None:
    """A linter that litters the directory it is linting is worse than one that
    does not run."""
    path = tmp_path / "openapi.yaml"
    path.write_text(_SPEC.read_text(encoding="utf-8"), encoding="utf-8")
    before = sorted(p.name for p in tmp_path.iterdir())
    analyze(str(path), _SPEC.read_text(encoding="utf-8"))
    analyze(str(path), "{ not valid")
    assert sorted(p.name for p in tmp_path.iterdir()) == before


def test_a_sibling_ref_still_resolves(tmp_path: Path) -> None:
    """This is the test that justifies putting the scratch file beside the
    document instead of in the system temp directory. A contract's
    `$ref: ./money.yaml` resolves relative to the file holding it, so linting a
    copy elsewhere reports every sibling reference as unresolvable -- a wall of
    errors caused entirely by the linter."""
    (tmp_path / "money.yaml").write_text(
        "type: object\nproperties:\n  amount: {type: integer}\n", encoding="utf-8"
    )
    text = (
        "openapi: 3.0.3\n"
        "info: {title: Refs, version: 1.0.0}\n"
        "paths:\n"
        "  /prices:\n"
        "    get:\n"
        "      responses:\n"
        "        '200':\n"
        "          description: ok\n"
        "          content:\n"
        "            application/json:\n"
        "              schema:\n"
        "                $ref: './money.yaml'\n"
    )
    found = diagnostics(str(tmp_path / "openapi.yaml"), text, "file:///x")
    assert not [d for d in found if "unresolved" in d["message"].lower()]
    assert not [d for d in found if d["code"] == "PARSE"]


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("openapi.yaml", True),
        ("schema.JSON", True),
        ("api.graphql", True),
        ("service.proto", True),
        ("main.py", False),
        ("README.md", False),
    ],
)
def test_which_files_the_server_offers_an_opinion_about(name: str, expected: bool) -> None:
    """Running the full loader over every file an editor opens would be rude,
    and publishing an empty list for a `.py` would wipe another linter's
    diagnostics from the problem list."""
    assert lintable(name) is expected


def test_a_file_it_has_no_opinion_about_gets_no_publish() -> None:
    out = _drive([_open("file:///project/main.py", "print('hi')\n")])
    assert not [m for m in out if m.get("method") == "textDocument/publishDiagnostics"]


# -- document lifecycle ---------------------------------------------------


def test_closing_a_document_clears_its_diagnostics() -> None:
    """Otherwise they sit in the editor's problem list forever, for a file
    nobody has open."""
    uri = _uri(_SPEC)
    out = _drive(
        [
            _open(uri, _SPEC.read_text(encoding="utf-8")),
            {
                "jsonrpc": "2.0",
                "method": "textDocument/didClose",
                "params": {"textDocument": {"uri": uri}},
            },
        ]
    )
    published = [m for m in out if m.get("method") == "textDocument/publishDiagnostics"]
    assert len(published) == 2
    assert published[-1]["params"]["diagnostics"] == []


def test_a_change_republishes() -> None:
    uri = _uri(_SPEC)
    out = _drive(
        [
            _open(uri, _SPEC.read_text(encoding="utf-8")),
            {
                "jsonrpc": "2.0",
                "method": "textDocument/didChange",
                "params": {
                    "textDocument": {"uri": uri, "version": 2},
                    "contentChanges": [{"text": "still: not a contract\n"}],
                },
            },
        ]
    )
    published = [m for m in out if m.get("method") == "textDocument/publishDiagnostics"]
    assert len(published) == 2
    assert published[1]["params"]["diagnostics"] != published[0]["params"]["diagnostics"]


def test_typing_coalesces_into_one_analysis() -> None:
    """`didChange` fires per keystroke. Loading a contract, resolving its refs
    and running every rule on each one would keep a core busy while somebody
    types, so a change inside the window replaces the one before it."""
    import threading
    import time

    server = LanguageServer(io.BytesIO(), io.BytesIO(), debounce=0.25)
    runs: list[str] = []
    done = threading.Event()

    def record(uri: str) -> None:
        runs.append(uri)
        done.set()

    server._run = record  # type: ignore[method-assign]
    server.documents["file:///x.yaml"] = "{}"
    for _ in range(8):
        server.analyze("file:///x.yaml")
        time.sleep(0.01)

    assert runs == [], "analysis started while the keystrokes were still arriving"
    assert done.wait(5), "the debounced analysis never ran"
    assert runs == ["file:///x.yaml"]


def test_opening_and_saving_do_not_wait() -> None:
    """A debounce on open would leave a freshly opened file blank for half a
    second, which reads as the server not working."""
    server = LanguageServer(io.BytesIO(), io.BytesIO(), debounce=10.0)
    runs: list[str] = []
    server._run = runs.append  # type: ignore[method-assign]
    server._on_textDocument_didOpen({"textDocument": {"uri": "file:///x.yaml", "text": "{}"}})
    assert runs == ["file:///x.yaml"]


def test_hover_answers_from_what_the_editor_is_showing() -> None:
    uri = _uri(_SPEC)
    text = _SPEC.read_text(encoding="utf-8")
    line = diagnostics(str(_SPEC), text, uri)[0]["range"]["start"]["line"]
    out = _drive(
        [
            _open(uri, text),
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "textDocument/hover",
                "params": {
                    "textDocument": {"uri": uri},
                    "position": {"line": line, "character": 0},
                },
            },
        ]
    )
    hover = next(m for m in out if m.get("id") == 5)["result"]
    assert hover["contents"]["kind"] == "markdown"
    assert "apiverity" in hover["contents"]["value"]


def test_hover_on_a_clean_line_returns_nothing() -> None:
    """`null`, not an empty popup. Clients render an empty hover as a blank box
    that hides the code under it."""
    uri = _uri(_SPEC)
    out = _drive(
        [
            _open(uri, _SPEC.read_text(encoding="utf-8")),
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "textDocument/hover",
                "params": {
                    "textDocument": {"uri": uri},
                    "position": {"line": 9999, "character": 0},
                },
            },
        ]
    )
    assert next(m for m in out if m.get("id") == 5)["result"] is None


# -- uris -----------------------------------------------------------------


def test_a_file_uri_becomes_a_path_this_machine_has() -> None:
    """`urlparse().path` leaves a leading slash before a Windows drive letter
    and leaves percent-escapes intact, and the result exists nowhere."""
    assert uri_to_path(_SPEC.as_uri()) == str(_SPEC)


def test_a_uri_with_an_escaped_space_round_trips(tmp_path: Path) -> None:
    directory = tmp_path / "my project"
    directory.mkdir()
    path = directory / "openapi.yaml"
    path.write_text("{}", encoding="utf-8")
    assert Path(uri_to_path(path.as_uri())) == path


# -- launched the way an editor launches it -------------------------------


def test_the_command_speaks_the_protocol_on_stdio() -> None:
    """stdout *is* the stream. A stray `print` anywhere in the import path --
    a deprecation notice, a plugin banner -- breaks every client, and only a
    real process launch would catch it."""
    requests = b"".join(
        _frame(m)
        for m in (
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "shutdown", "params": {}},
            {"jsonrpc": "2.0", "method": "exit", "params": {}},
        )
    )
    result = subprocess.run(
        [sys.executable, "-m", "apiverity.cli.main", "lsp"],
        input=requests,
        capture_output=True,
        cwd=_ROOT,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    stream = io.BytesIO(result.stdout)
    first = protocol.read_message(stream)
    assert first is not None
    assert first["id"] == 1
    assert first["result"]["serverInfo"]["name"] == "apiverity"
    second = protocol.read_message(stream)
    assert second is not None
    assert second["id"] == 2
