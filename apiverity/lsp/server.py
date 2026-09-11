"""A language server for API contracts.

Editor integration for a linter is usually five plugins, each reimplementing
the same checks against the same rules, each drifting from the tool at its own
speed. One language server is the alternative: VS Code, Neovim, JetBrains,
Helix, Zed and Emacs all speak LSP, and all of them get exactly the rules the
CLI runs, because it is the CLI's engine answering.

    apiverity lsp            # stdio, which is what every client launches

## What it implements, and what it deliberately does not

**Diagnostics** on open, change and save — every rule `apiverity validate`
runs, including the security checks, with the rule id as the diagnostic code
and a link to the catalogue entry.

**Hover** over a diagnostic's line, showing the finding in full. Editors
truncate diagnostic text in the gutter, and the sentence that says what to do
about it is usually the part that gets cut.

Not completion, not formatting, not go-to-definition. A spec-aware completion
provider is a real piece of work and there are editor plugins that already do
it well for OpenAPI; shipping a thin one would put this server in their way for
no gain. This server does the thing no other plugin does: it runs *these*
rules.

## Debouncing, and why it is not optional

`didChange` fires per keystroke. Loading a contract, resolving its refs and
running every rule on each one would keep a core busy while somebody types, so
a change schedules a run and a further change inside the window replaces it.

## One thread, no asyncio

The work is IO-bound on a pipe and CPU-bound in the analyser, and there is
exactly one client. A timer thread for the debounce and a lock around the
writer is the whole concurrency story; an event loop here would be ceremony
around a loop that reads one message at a time.
"""

from __future__ import annotations

import threading
import urllib.parse
import urllib.request
from typing import Any, BinaryIO

from apiverity.lsp import protocol
from apiverity.lsp.diagnostics import diagnostics, lintable

#: Seconds a keystroke delays analysis. Long enough that typing a path does not
#: run the rules eight times, short enough that a pause feels like an answer.
DEBOUNCE_SECONDS = 0.4

#: `textDocument/didChange` sends the whole document. Incremental sync means
#: reimplementing range patching, and getting that subtly wrong shows up as
#: diagnostics on the wrong lines rather than as an error.
SYNC_FULL = 1


def uri_to_path(uri: str) -> str:
    """`file:///c%3A/x/y.yaml` to a filesystem path.

    Written out rather than `urlparse().path`, because that leaves a leading
    slash before a Windows drive letter and percent-escapes intact -- and the
    resulting path exists on no machine.
    """
    parsed = urllib.parse.urlparse(uri)
    if parsed.scheme and parsed.scheme != "file":
        return uri
    return urllib.request.url2pathname(parsed.path)


class LanguageServer:
    """The message loop and the document state."""

    def __init__(
        self,
        reader: BinaryIO,
        writer: BinaryIO,
        *,
        debounce: float = DEBOUNCE_SECONDS,
    ) -> None:
        self._reader = reader
        self._writer = writer
        self._debounce = debounce
        self._write_lock = threading.Lock()
        self._timers: dict[str, threading.Timer] = {}
        #: uri -> current buffer text.
        self.documents: dict[str, str] = {}
        #: uri -> the diagnostics last published, kept so hover can answer from
        #: what the editor is actually showing rather than re-running the rules.
        self.published: dict[str, list[dict[str, Any]]] = {}
        self.shutdown_requested = False
        self.running = True

    # -- transport -------------------------------------------------------

    def send(self, message: dict[str, Any]) -> None:
        with self._write_lock:
            protocol.write_message(self._writer, message)

    def notify(self, method: str, params: Any) -> None:
        self.send(protocol.notification(method, params))

    # -- lifecycle -------------------------------------------------------

    def serve(self) -> int:
        while self.running:
            try:
                message = protocol.read_message(self._reader)
            except protocol.ProtocolError:
                # A desynchronised stream cannot be recovered from: every
                # subsequent frame is garbage. Stopping is the honest response.
                return 1
            if message is None:
                # The client closed the pipe. Editors do this on quit.
                break
            self._dispatch(message)
        self._cancel_all()
        return 0

    def _dispatch(self, message: dict[str, Any]) -> None:
        method = str(message.get("method") or "")
        request_id = message.get("id")
        params = message.get("params") or {}

        handler = getattr(self, "_on_" + method.replace("/", "_").replace("$", ""), None)
        if handler is None:
            if request_id is not None:
                # A *request* must be answered; an unknown notification is
                # ignored, which is what the specification requires.
                self.send(
                    protocol.error(request_id, protocol.METHOD_NOT_FOUND, f"unsupported: {method}")
                )
            return
        try:
            result = handler(params)
        except Exception as exc:  # a handler bug must not take the server down
            if request_id is not None:
                self.send(protocol.error(request_id, protocol.INTERNAL_ERROR, str(exc)))
            return
        if request_id is not None:
            self.send(protocol.response(request_id, result))

    def _on_initialize(self, _params: dict[str, Any]) -> dict[str, Any]:
        from apiverity import __version__

        return {
            "capabilities": {
                "textDocumentSync": {
                    "openClose": True,
                    "change": SYNC_FULL,
                    "save": {"includeText": True},
                },
                "hoverProvider": True,
                "diagnosticProvider": {
                    "identifier": "apiverity",
                    "interFileDependencies": True,
                    "workspaceDiagnostics": False,
                },
            },
            "serverInfo": {"name": "apiverity", "version": __version__},
        }

    def _on_initialized(self, _params: dict[str, Any]) -> None:
        return None

    def _on_shutdown(self, _params: dict[str, Any]) -> None:
        self.shutdown_requested = True
        self._cancel_all()
        return None

    def _on_exit(self, _params: dict[str, Any]) -> None:
        self.running = False
        return None

    # -- documents -------------------------------------------------------

    def _on_textDocument_didOpen(self, params: dict[str, Any]) -> None:
        document = params.get("textDocument") or {}
        uri = str(document.get("uri") or "")
        self.documents[uri] = str(document.get("text") or "")
        self.analyze(uri, immediate=True)
        return None

    def _on_textDocument_didChange(self, params: dict[str, Any]) -> None:
        document = params.get("textDocument") or {}
        uri = str(document.get("uri") or "")
        changes = params.get("contentChanges") or []
        if not changes:
            return None
        # Full sync: the last change carries the whole document.
        self.documents[uri] = str(changes[-1].get("text") or "")
        self.analyze(uri)
        return None

    def _on_textDocument_didSave(self, params: dict[str, Any]) -> None:
        document = params.get("textDocument") or {}
        uri = str(document.get("uri") or "")
        if "text" in params:
            self.documents[uri] = str(params.get("text") or "")
        self.analyze(uri, immediate=True)
        return None

    def _on_textDocument_didClose(self, params: dict[str, Any]) -> None:
        document = params.get("textDocument") or {}
        uri = str(document.get("uri") or "")
        self._cancel(uri)
        self.documents.pop(uri, None)
        self.published.pop(uri, None)
        # Diagnostics for a closed file stay in the editor's problem list
        # forever unless they are explicitly cleared.
        self.notify("textDocument/publishDiagnostics", {"uri": uri, "diagnostics": []})
        return None

    def _on_textDocument_hover(self, params: dict[str, Any]) -> dict[str, Any] | None:
        uri = str((params.get("textDocument") or {}).get("uri") or "")
        line = int((params.get("position") or {}).get("line", -1))
        found = [d for d in self.published.get(uri, []) if d["range"]["start"]["line"] == line]
        if not found:
            return None
        parts = [f"**{d['code']}** ({d['source']})\n\n{d['message']}" for d in found]
        return {"contents": {"kind": "markdown", "value": "\n\n---\n\n".join(parts)}}

    # -- analysis --------------------------------------------------------

    def analyze(self, uri: str, *, immediate: bool = False) -> None:
        self._cancel(uri)
        if immediate or self._debounce <= 0:
            self._run(uri)
            return
        timer = threading.Timer(self._debounce, self._run, args=(uri,))
        timer.daemon = True
        self._timers[uri] = timer
        timer.start()

    def _run(self, uri: str) -> None:
        self._timers.pop(uri, None)
        text = self.documents.get(uri)
        if text is None:
            return
        path = uri_to_path(uri)
        if not lintable(path):
            # Nothing published, and nothing cleared: a file this server has no
            # opinion about should not have its other linters' diagnostics
            # wiped by an empty publish from this one.
            return
        try:
            found = diagnostics(path, text, uri)
        except Exception as exc:
            self.notify(
                "window/logMessage",
                {"type": 1, "message": f"apiverity: analysing {path} raised {exc}"},
            )
            return
        self.published[uri] = found
        self.notify("textDocument/publishDiagnostics", {"uri": uri, "diagnostics": found})

    def _cancel(self, uri: str) -> None:
        timer = self._timers.pop(uri, None)
        if timer is not None:
            timer.cancel()

    def _cancel_all(self) -> None:
        for uri in list(self._timers):
            self._cancel(uri)


def serve(reader: BinaryIO, writer: BinaryIO, *, debounce: float = DEBOUNCE_SECONDS) -> int:
    return LanguageServer(reader, writer, debounce=debounce).serve()


def main() -> int:
    """stdio, which is how every client launches a language server."""
    import sys

    # `.buffer`, never the text streams: on Windows a text-mode stdout
    # translates `\n` to `\r\n`, which corrupts every frame.
    return serve(sys.stdin.buffer, sys.stdout.buffer)


__all__ = ["DEBOUNCE_SECONDS", "LanguageServer", "main", "serve", "uri_to_path"]


if __name__ == "__main__":  # pragma: no cover - launched by an editor
    raise SystemExit(main())
