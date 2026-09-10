"""Stdlib-based deterministic mock server (no extra dependencies)."""

from __future__ import annotations

import json
import random
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from apiverity.core.model import Operation, Service
from apiverity.fuzz.generate import generate_valid


@dataclass
class FaultConfig:
    """Development fault modes — never enabled by default."""

    latency_ms: int = 0
    force_status: int | None = None
    malformed_json: bool = False
    rate_limit_after: int | None = None  # return 429 after N requests
    seed: int = 0


@dataclass
class _State:
    request_count: int = 0
    store: dict[str, dict[str, Any]] = field(default_factory=dict)  # resource -> id -> item
    next_id: int = 1
    #: resource -> ids a DELETE removed. Kept rather than only dropping them
    #: from `store`, so a GET for one answers 404 instead of falling through
    #: to a freshly generated body -- which is what made a deleted resource
    #: still readable.
    deleted: dict[str, set[str]] = field(default_factory=dict)


#: Statuses RFC 9110 says carry no content.
_NO_BODY_STATUS = frozenset({204, 304})


def _address(path: str) -> tuple[str, str]:
    """`/widgets/7` -> `("widgets", "7")`; a collection path has no id."""
    parts = [p for p in path.strip("/").split("/") if p]
    return (parts[0] if parts else ""), (parts[-1] if len(parts) > 1 else "")


class MockServer:
    """Serves deterministic responses derived from the contract."""

    def __init__(
        self,
        service: Service,
        *,
        host: str = "127.0.0.1",
        port: int = 0,
        faults: FaultConfig | None = None,
    ) -> None:
        self.service = service
        self.host = host
        self.port = port
        self.faults = faults or FaultConfig()
        self.state = _State()
        self._rng = random.Random(self.faults.seed)
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        ops = {op.key: op for op in service.operations}
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt: str, *args: Any) -> None:  # silence
                return

            def _handle(self) -> None:
                # Drain the request body so keep-alive connections stay in sync.
                try:
                    length = int(self.headers.get("Content-Length") or 0)
                except ValueError:
                    length = 0
                request_body: Any = None
                if length > 0:
                    raw_body = self.rfile.read(length)
                    try:
                        request_body = json.loads(raw_body.decode("utf-8"))
                    except (ValueError, UnicodeDecodeError):
                        request_body = None
                outer.state.request_count += 1
                if (
                    outer.faults.rate_limit_after is not None
                    and outer.state.request_count > outer.faults.rate_limit_after
                ):
                    self._respond(429, {"error": "rate limit exceeded"})
                    return
                if outer.faults.latency_ms:
                    time.sleep(outer.faults.latency_ms / 1000.0)

                method = self.command
                path = self.path.split("?")[0]
                key = f"{method} {path}"
                op = ops.get(key)
                if op is None:
                    # try template match: /users/1 vs GET /users/{id}
                    op = self._match_template(method, path)
                if op is None:
                    self._respond(404, {"error": f"no mock for {key}"})
                    return

                status_code = outer.faults.force_status or self._pick_status(op)
                if outer.faults.force_status is None and self._is_gone(method, op, path):
                    # A resource this mock deleted. Answering 200 with the old
                    # body would make every "delete, then read it back" check
                    # pass against a mock where nothing was ever deleted.
                    self._respond(404, {"error": "not found"})
                    return

                # Before the body: a 204 has no response schema, so
                # `_build_body` returns early and a DELETE recorded nothing --
                # which is how a deleted resource stayed readable.
                self._apply_state(method, op, path, request_body)

                body = self._build_body(op, status_code, method, path, request_body=request_body)

                if outer.faults.malformed_json:
                    payload = b'{"truncated...'
                elif status_code in _NO_BODY_STATUS:
                    # RFC 9110: a 204 or a 304 carries no content. This sent
                    # `{"error": "mock error 204"}`, because `_build_body`
                    # treats "no response schema" as an error case.
                    self._respond(status_code, b"", raw=True, content_type=None)
                    return
                else:
                    payload = json.dumps(body).encode("utf-8")
                self._respond(status_code, payload, raw=True)

            def _apply_state(
                self, method: str, op: Operation, path: str, request_body: Any
            ) -> None:
                """Record what this request does to the mock's store."""
                if "{" not in (op.path or ""):
                    return
                resource, item_id = _address(path)
                if method == "DELETE":
                    outer.state.store.get(resource, {}).pop(item_id, None)
                    outer.state.deleted.setdefault(resource, set()).add(item_id)
                elif method in ("PATCH", "PUT"):
                    stored = outer.state.store.get(resource, {}).get(item_id)
                    if stored is None:
                        return
                    # PATCH merges, PUT replaces. A mock that merged on PUT
                    # would let a client believe a field it stopped sending was
                    # still being cleared.
                    updated = dict(stored) if method == "PATCH" else {}
                    if isinstance(request_body, dict):
                        updated.update(request_body)
                    updated["id"] = item_id
                    outer.state.store.setdefault(resource, {})[item_id] = updated

            def _is_gone(self, method: str, op: Operation, path: str) -> bool:
                """Whether this addresses a resource a DELETE has removed."""
                if method in ("POST",) or "{" not in (op.path or ""):
                    return False
                resource, item_id = _address(path)
                return item_id in outer.state.deleted.get(resource, set())

            def _match_template(self, method: str, path: str) -> Operation | None:
                parts = [p for p in path.split("/") if p]
                for candidate in outer.service.operations:
                    if candidate.method != method or not candidate.path:
                        continue
                    cparts = [p for p in candidate.path.split("/") if p]
                    if len(cparts) != len(parts):
                        continue
                    ok = True
                    for cp, pp in zip(cparts, parts, strict=True):
                        if not ((cp.startswith("{") and cp.endswith("}")) or cp == pp):
                            ok = False
                            break
                        if cp.startswith("{"):
                            # remember the value for body building
                            name = cp[1:-1]
                            outer.state.store.setdefault("__path__", {})[name] = pp
                    if ok:
                        return candidate
                return None

            def _pick_status(self, op: Operation) -> int:
                for resp in op.responses:
                    if resp.status.isdigit():
                        return int(resp.status)
                return 200

            def _build_body(
                self,
                op: Operation,
                status: int,
                method: str,
                path: str,
                *,
                request_body: Any = None,
            ) -> Any:
                # prefer declared examples
                for ex in op.examples:
                    if ex.value is not None:
                        return ex.value
                schema = None
                for resp in op.responses:
                    if resp.status == str(status) and resp.content:
                        media = sorted(resp.content)[0]
                        schema = resp.content[media]
                        break
                if status >= 400 or schema is None:
                    return {"error": f"mock error {status}"}

                value = generate_valid(schema, outer._rng)
                resource, item_id = _address(path)
                if method == "POST" and isinstance(value, dict):
                    new_id = str(outer.state.next_id)
                    outer.state.next_id += 1
                    value.setdefault("id", new_id)
                    if isinstance(request_body, dict):
                        value.update(request_body)
                        value["id"] = new_id
                    outer.state.store.setdefault(resource, {})[new_id] = value
                    outer.state.deleted.get(resource, set()).discard(new_id)
                elif method in ("GET", "PATCH", "PUT") and "{" in (op.path or ""):
                    # `_apply_state` has already merged an update, so reading
                    # the store here answers a PATCH with what it stored.
                    stored = outer.state.store.get(resource, {}).get(item_id)
                    if stored is not None:
                        return stored
                return value

            def _respond(
                self,
                status: int,
                body: Any,
                *,
                raw: bool = False,
                content_type: str | None = "application/json",
            ) -> None:
                data = body if raw else json.dumps(body).encode("utf-8")
                self.send_response(status)
                if content_type is not None:
                    self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = _handle

        self._handler_cls = Handler

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def start(self) -> None:
        self._httpd = ThreadingHTTPServer((self.host, self.port), self._handler_cls)
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def __enter__(self) -> MockServer:
        self.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.stop()


def serve(
    service: Service,
    host: str = "127.0.0.1",
    port: int = 8090,
    faults: FaultConfig | None = None,
) -> None:
    """Run the mock server in the foreground until interrupted."""
    server = MockServer(service, host=host, port=port, faults=faults)
    server.start()
    print(f"mock server serving {service.title} at {server.base_url} (Ctrl+C to stop)")
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
