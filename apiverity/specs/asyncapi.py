"""AsyncAPI 2.x adapter foundation.

Normalizes event-driven contracts (channels, messages, servers, bindings)
into the common model as EVENT operations with explicit direction metadata.
Bindings are preserved verbatim for protocol-specific analysis.
"""

from __future__ import annotations

from typing import Any

from ..core.model import (
    Finding,
    Operation,
    OperationKind,
    Protocol,
    RequestBody,
    Server,
    Service,
    Severity,
)
from . import SpecPlugin
from .openapi.parser import OpenApiParser, load_yaml_with_lines


class AsyncApiParser:
    """Converts an AsyncAPI 2.x document into a normalized :class:`Service`."""

    def __init__(self, file_label: str) -> None:
        self.oas = OpenApiParser(file_label)

    def parse(self, source: str) -> tuple[Service, list[Finding]]:
        _label, raw = self._read(source)
        root, lines = load_yaml_with_lines(raw.decode("utf-8"))
        self.oas._lines = lines
        findings = self.oas.findings
        info = root.get("info") or {}

        servers = []
        for name, snode in (root.get("servers") or {}).items():
            if isinstance(snode, dict):
                url = str(snode.get("url") or "")
                proto = str(snode.get("protocol") or "")
                servers.append(Server(url=url, description=f"{name} ({proto})"))

        operations: list[Operation] = []
        channels = root.get("channels") or {}
        for channel_name, cnode in channels.items():
            if not isinstance(cnode, dict):
                continue
            for action in ("publish", "subscribe"):
                onode = cnode.get(action)
                if not isinstance(onode, dict):
                    continue
                pointer = f"/channels/{OpenApiParser._escape_pointer(str(channel_name))}/{action}"
                messages = self._messages(root, onode, pointer)
                if not messages:
                    findings.append(
                        Finding(
                            rule_id="ASYNCAPI-CHANNEL-NO-MESSAGE",
                            severity=Severity.WARN,
                            message=f"channel '{channel_name}' {action} declares no message",
                        )
                    )
                for msg_name, payload_schema in messages:
                    op = Operation(
                        kind=OperationKind.EVENT,
                        operation_id=onode.get("operationId"),
                        method=action,
                        path=str(channel_name),
                        rpc_name=msg_name,
                        service_name=str(info.get("title") or "asyncapi"),
                        summary=onode.get("summary"),
                        description=onode.get("description"),
                        deprecated=bool(onode.get("deprecated", False)),
                        tags=[str(t) for t in (onode.get("tags") or [])],
                        channel=str(channel_name),
                        message_name=msg_name,
                        direction=action,
                        bindings=self._safe_bindings(onode.get("bindings")),
                        request_body=(
                            RequestBody(
                                required=True,
                                content={"application/json": payload_schema},
                                source_location=payload_schema.source_location,
                            )
                            if payload_schema is not None
                            else None
                        ),
                        source_location=self.oas._loc(pointer, onode),
                    )
                    operations.append(op)

        service = Service(
            title=str(info.get("title") or "Untitled AsyncAPI document"),
            version=str(info.get("version") or "0.0.0"),
            protocol=Protocol.ASYNCAPI,
            description=info.get("description"),
            servers=servers,
            operations=operations,
            source_file=self.oas.file_label,
        )
        return service, findings

    def _messages(
        self, root: dict[str, Any], onode: dict[str, Any], pointer: str
    ) -> list[tuple[str, Any]]:
        """Return (message-name, payload SchemaNode) pairs for an operation."""
        out: list[tuple[str, Any]] = []
        raw_msgs = onode.get("message")
        if raw_msgs is None and isinstance(onode.get("messages"), dict):
            raw_msgs = list(onode["messages"].values())
        if isinstance(raw_msgs, dict) and "oneOf" in raw_msgs:
            raw_msgs = raw_msgs["oneOf"]
        if isinstance(raw_msgs, dict):
            raw_msgs = [raw_msgs]
        if not isinstance(raw_msgs, list):
            return out
        for idx, mnode in enumerate(raw_msgs):
            mnode = self.oas.deref(root, mnode, f"{pointer}/message/{idx}")
            if not isinstance(mnode, dict):
                continue
            name = str(mnode.get("name") or f"{pointer}/message/{idx}")
            payload = mnode.get("payload")
            schema = (
                self.oas.to_schema(root, payload, f"{pointer}/message/{idx}/payload")
                if isinstance(payload, dict)
                else None
            )
            out.append((name, schema))
        return out

    @staticmethod
    def _safe_bindings(node: Any) -> dict[str, Any]:
        return node if isinstance(node, dict) else {}

    def _read(self, source: str) -> tuple[str, bytes]:
        from . import read_source

        return read_source(source)


def load_asyncapi(source: str) -> tuple[Service, list[Finding]]:
    return AsyncApiParser(source).parse(source)


class AsyncApiSpecPlugin(SpecPlugin):
    """Spec plugin for AsyncAPI 2.x documents."""

    def protocol(self) -> Protocol:
        return Protocol.ASYNCAPI

    def detect(self, source: str, raw: bytes | None = None) -> bool:
        from . import parse_document

        try:
            doc = parse_document(raw) if raw is not None else None
        except Exception:
            return False
        return isinstance(doc, dict) and str(doc.get("asyncapi", "")).startswith("2")

    def load(self, source: str) -> tuple[Service, list[Finding]]:
        return load_asyncapi(source)
