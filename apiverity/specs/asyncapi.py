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

#: How each version's words map onto the application's point of view.
#:
#: This table is the whole reason the two versions can be compared at all.
#: AsyncAPI 2 names operations from the *client's* side: `publish` is what a
#: client publishes, so the application receives it; `subscribe` is what a
#: client subscribes to, so the application sends it. AsyncAPI 3 renamed them
#: to `send`/`receive` from the *application's* side, which inverts the
#: reading. Storing the raw word made a 2.x document and its own 3.x migration
#: look like two unrelated contracts -- every operation removed, every
#: operation added.
DIRECTION = {
    "publish": "receive",
    "subscribe": "send",
    "send": "send",
    "receive": "receive",
}


class AsyncApiParser:
    """Converts an AsyncAPI 2.x or 3.x document into a normalized `Service`."""

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

        version = str(root.get("asyncapi") or "")
        operations = (
            self._operations_v3(root, info, findings)
            if version.startswith("3")
            else self._operations_v2(root, info, findings)
        )

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

    def _operations_v2(
        self, root: dict[str, Any], info: dict[str, Any], findings: list[Finding]
    ) -> list[Operation]:
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
                        direction=DIRECTION[action],
                        source_action=action,
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
        return operations

    def _operations_v3(
        self, root: dict[str, Any], info: dict[str, Any], findings: list[Finding]
    ) -> list[Operation]:
        """Walk an AsyncAPI 3 document.

        The shape differs enough that sharing the 2.x walk would be worse than
        having two: operations move to the top level and point at a channel by
        reference rather than nesting inside one, and the messages live on the
        channel rather than on the operation. What comes out is the same
        normalized Operation, which is the point of an adapter.
        """
        operations: list[Operation] = []
        channels = root.get("channels") or {}
        for op_name, onode in (root.get("operations") or {}).items():
            if not isinstance(onode, dict):
                continue
            pointer = f"/operations/{OpenApiParser._escape_pointer(str(op_name))}"
            action = str(onode.get("action") or "")
            if action not in DIRECTION:
                findings.append(
                    Finding(
                        rule_id="ASYNCAPI-OPERATION-BAD-ACTION",
                        severity=Severity.WARN,
                        message=(
                            f"operation '{op_name}' has action {action!r}; "
                            "AsyncAPI 3 defines only 'send' and 'receive'"
                        ),
                    )
                )
                continue

            channel_name, channel_node = self._channel_of(root, channels, onode)
            if channel_node is None:
                findings.append(
                    Finding(
                        rule_id="ASYNCAPI-OPERATION-NO-CHANNEL",
                        severity=Severity.WARN,
                        message=f"operation '{op_name}' does not resolve to a channel",
                    )
                )
                continue

            address = str(channel_node.get("address") or channel_name)
            messages = self._messages_v3(root, onode, channel_node, pointer)
            if not messages:
                findings.append(
                    Finding(
                        rule_id="ASYNCAPI-CHANNEL-NO-MESSAGE",
                        severity=Severity.WARN,
                        message=f"operation '{op_name}' declares no message",
                    )
                )
            for msg_name, payload_schema in messages:
                operations.append(
                    Operation(
                        kind=OperationKind.EVENT,
                        operation_id=str(op_name),
                        method=action,
                        path=address,
                        rpc_name=msg_name,
                        service_name=str(info.get("title") or "asyncapi"),
                        summary=onode.get("summary"),
                        description=onode.get("description"),
                        deprecated=bool(onode.get("deprecated", False)),
                        tags=[
                            str(t.get("name") if isinstance(t, dict) else t)
                            for t in (onode.get("tags") or [])
                        ],
                        channel=address,
                        message_name=msg_name,
                        direction=DIRECTION[action],
                        source_action=action,
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
                )
        return operations

    def _channel_of(
        self, root: dict[str, Any], channels: dict[str, Any], onode: dict[str, Any]
    ) -> tuple[str, dict[str, Any] | None]:
        """Resolve an operation's channel reference to (name, node)."""
        raw = onode.get("channel")
        if isinstance(raw, dict) and "$ref" in raw:
            ref = str(raw["$ref"])
            name = ref.rsplit("/", 1)[-1].replace("~1", "/").replace("~0", "~")
            node = channels.get(name)
            if isinstance(node, dict):
                return name, node
            resolved = self.oas.deref(root, raw, "/operations/channel")
            return name, resolved if isinstance(resolved, dict) else None
        if isinstance(raw, dict):
            return str(raw.get("address") or ""), raw
        return "", None

    def _messages_v3(
        self,
        root: dict[str, Any],
        onode: dict[str, Any],
        channel_node: dict[str, Any],
        pointer: str,
    ) -> list[tuple[str, Any]]:
        """Messages for an AsyncAPI 3 operation.

        An operation may name a subset of its channel's messages; naming none
        means all of them.
        """
        selected = onode.get("messages")
        nodes: list[tuple[str, Any]] = []
        channel_messages = channel_node.get("messages")
        if isinstance(selected, list) and selected:
            for idx, ref in enumerate(selected):
                name = ""
                if isinstance(ref, dict) and "$ref" in ref:
                    name = str(ref["$ref"]).rsplit("/", 1)[-1]
                resolved = self.oas.deref(root, ref, f"{pointer}/messages/{idx}")
                if not isinstance(resolved, dict) and isinstance(channel_messages, dict):
                    resolved = channel_messages.get(name)
                nodes.append((name, resolved))
        elif isinstance(channel_messages, dict):
            for name, node in channel_messages.items():
                nodes.append((str(name), self.oas.deref(root, node, f"{pointer}/messages")))

        out: list[tuple[str, Any]] = []
        for idx, (name, node) in enumerate(nodes):
            if not isinstance(node, dict):
                continue
            label = str(node.get("name") or name or f"message-{idx}")
            payload = node.get("payload")
            schema = (
                self.oas.to_schema(root, payload, f"{pointer}/messages/{idx}/payload")
                if isinstance(payload, dict)
                else None
            )
            out.append((label, schema))
        return out

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
    """Spec plugin for AsyncAPI 2.x and 3.x documents."""

    #: Inherited from SpecPlugin, restated so the contract version this
    #: adapter implements is visible where the adapter is.
    PLUGIN_API_VERSION = "1"

    #: Major versions this adapter understands. A 4.x document is refused
    #: rather than parsed on the assumption it resembles 3.x: guessing at a
    #: format nobody has published yields a contract that looks parsed and is
    #: wrong, which is worse than saying so.
    SUPPORTED_MAJORS = ("2", "3")

    def protocol(self) -> Protocol:
        return Protocol.ASYNCAPI

    def detect(self, source: str, raw: bytes | None = None) -> bool:
        from . import parse_document

        try:
            doc = parse_document(raw) if raw is not None else None
        except Exception:
            return False
        if not isinstance(doc, dict):
            return False
        version = str(doc.get("asyncapi", ""))
        return any(version.startswith(major) for major in self.SUPPORTED_MAJORS)

    def load(self, source: str) -> tuple[Service, list[Finding]]:
        return load_asyncapi(source)
