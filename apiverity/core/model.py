"""Normalized, spec-neutral contract model.

Every supported specification format (OpenAPI, GraphQL SDL, protobuf) is
compiled into these types. All downstream engines (diff, rules, fuzz,
drift, coverage, reports) operate exclusively on this model.

Every entity preserves a :class:`SourceLocation` pointing at the original
spec document so findings can link to exact lines.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Protocol(StrEnum):
    """Wire protocol of a contract."""

    OPENAPI = "openapi"
    GRAPHQL = "graphql"
    GRPC = "grpc"
    ASYNCAPI = "asyncapi"
    SSE = "sse"
    WEBSOCKET = "websocket"


class SourceLocation(BaseModel):
    """Precise location in the original spec document."""

    model_config = ConfigDict(frozen=True)

    file: str
    line: int = 0
    column: int = 0
    pointer: str = ""  # JSON pointer, e.g. /paths/~1users/get

    def __str__(self) -> str:  # pragma: no cover - trivial
        loc = f"{self.file}:{self.line}:{self.column}" if self.line else self.file
        if self.pointer:
            loc += f" ({self.pointer})"
        return loc


class SchemaNode(BaseModel):
    """Recursive, JSON-Schema-like type tree used for all protocols."""

    type: str | None = None  # object|array|string|integer|number|boolean|null
    format: str | None = None
    title: str | None = None
    description: str | None = None
    nullable: bool = False
    deprecated: bool = False
    enum: list[Any] | None = None
    const: Any | None = None
    default: Any | None = None
    example: Any | None = None
    # object constraints
    properties: dict[str, SchemaNode] = Field(default_factory=dict)
    required: list[str] = Field(default_factory=list)
    additional_properties: bool | SchemaNode | None = None
    min_properties: int | None = None
    max_properties: int | None = None
    # array constraints
    items: SchemaNode | None = None
    min_items: int | None = None
    max_items: int | None = None
    unique_items: bool | None = None
    # string constraints
    min_length: int | None = None
    max_length: int | None = None
    pattern: str | None = None
    # numeric constraints
    minimum: float | None = None
    maximum: float | None = None
    exclusive_minimum: float | None = None
    exclusive_maximum: float | None = None
    multiple_of: float | None = None
    # composition
    one_of: list[SchemaNode] | None = None
    any_of: list[SchemaNode] | None = None
    all_of: list[SchemaNode] | None = None
    not_: SchemaNode | None = Field(default=None, alias="not")
    # provenance
    source_location: SourceLocation | None = None

    model_config = ConfigDict(populate_by_name=True)

    def iter_property_names(self) -> list[str]:
        return list(self.properties.keys())


class ParameterLocation(StrEnum):
    PATH = "path"
    QUERY = "query"
    HEADER = "header"
    COOKIE = "cookie"


class Parameter(BaseModel):
    name: str
    location: ParameterLocation
    required: bool = False
    deprecated: bool = False
    description: str | None = None
    schema_node: SchemaNode | None = None
    example: Any | None = None
    source_location: SourceLocation | None = None


class RequestBody(BaseModel):
    required: bool = False
    description: str | None = None
    content: dict[str, SchemaNode] = Field(default_factory=dict)  # media type -> schema
    source_location: SourceLocation | None = None


class Response(BaseModel):
    status: str  # "200", "4XX", "default"
    description: str | None = None
    headers: dict[str, SchemaNode] = Field(default_factory=dict)
    content: dict[str, SchemaNode] = Field(default_factory=dict)
    source_location: SourceLocation | None = None


class SecurityRequirement(BaseModel):
    """A named security scheme plus required scopes."""

    scheme_name: str
    scopes: list[str] = Field(default_factory=list)


class SecurityScheme(BaseModel):
    name: str
    type: str  # apiKey | http | oauth2 | openIdConnect | mutualTLS
    location: ParameterLocation | None = None  # for apiKey
    scheme: str | None = None  # bearer, basic, digest for http
    bearer_format: str | None = None
    scopes: dict[str, str] = Field(default_factory=dict)  # OAuth flow scopes
    deprecated: bool = False
    source_location: SourceLocation | None = None


class Example(BaseModel):
    name: str
    value: Any | None = None
    summary: str | None = None
    source_location: SourceLocation | None = None


class DeprecationInfo(BaseModel):
    """Deprecation lifecycle metadata for an operation or schema node."""

    announced_date: str | None = None  # ISO date the deprecation was announced
    sunset_date: str | None = None  # ISO date after which removal is expected
    migration_guide: str | None = None
    consumer_impact: str | None = None


class LifecycleState(StrEnum):
    """API lifecycle states with ordered transition rules."""

    EXPERIMENTAL = "experimental"
    BETA = "beta"
    STABLE = "stable"
    DEPRECATED = "deprecated"
    RETIRED = "retired"


# Allowed forward transitions; anything else requires an explicit override.
LIFECYCLE_TRANSITIONS: dict[LifecycleState, set[LifecycleState]] = {
    LifecycleState.EXPERIMENTAL: {LifecycleState.BETA, LifecycleState.RETIRED},
    LifecycleState.BETA: {LifecycleState.STABLE, LifecycleState.RETIRED},
    LifecycleState.STABLE: {LifecycleState.DEPRECATED},
    LifecycleState.DEPRECATED: {LifecycleState.RETIRED},
    LifecycleState.RETIRED: set(),
}


class OperationKind(StrEnum):
    HTTP = "http"
    GRAPHQL_FIELD = "graphql_field"
    GRPC_RPC = "grpc_rpc"
    EVENT = "event"  # AsyncAPI publish/subscribe or SSE event stream
    WS_MESSAGE = "ws_message"  # documented WebSocket bidirectional message type


class Operation(BaseModel):
    """A single callable unit of the contract.

    For HTTP: ``method`` + ``path``. For GraphQL: a field on a root type.
    For gRPC: an RPC on a service.
    """

    kind: OperationKind = OperationKind.HTTP
    operation_id: str | None = None
    method: str | None = None  # GET/POST/... (HTTP)
    path: str | None = None  # /users/{id} (HTTP)
    rpc_name: str | None = None  # gRPC
    service_name: str | None = None  # gRPC / GraphQL root type
    summary: str | None = None
    description: str | None = None
    deprecated: bool = False
    tags: list[str] = Field(default_factory=list)
    parameters: list[Parameter] = Field(default_factory=list)
    request_body: RequestBody | None = None
    responses: list[Response] = Field(default_factory=list)
    security: list[SecurityRequirement] | None = None  # None = inherit global
    examples: list[Example] = Field(default_factory=list)
    # Event-driven extensions (AsyncAPI channels, SSE events, WebSocket messages)
    channel: str | None = None  # topic/channel/event name
    message_name: str | None = None
    direction: str | None = None  # "publish" | "subscribe" | "send" | "receive"
    bindings: dict[str, Any] = Field(default_factory=dict)
    # Governance metadata
    lifecycle_state: LifecycleState | None = None
    deprecation: DeprecationInfo | None = None
    idempotent: bool | None = None  # explicitly declared idempotency expectation
    pagination: dict[str, Any] | None = None  # explicitly modeled pagination semantics
    source_location: SourceLocation | None = None

    @property
    def key(self) -> str:
        """Canonical, stable operation key used for diffing and hashing."""
        if self.kind == OperationKind.HTTP:
            return f"{(self.method or '').upper()} {self.path}"
        if self.kind == OperationKind.GRAPHQL_FIELD:
            return f"{self.service_name}.{self.rpc_name}"
        return f"{self.service_name}.{self.rpc_name}"


class Server(BaseModel):
    url: str
    description: str | None = None


class Service(BaseModel):
    """Top-level normalized contract."""

    title: str
    version: str
    protocol: Protocol
    description: str | None = None
    servers: list[Server] = Field(default_factory=list)
    operations: list[Operation] = Field(default_factory=list)
    security_schemes: dict[str, SecurityScheme] = Field(default_factory=dict)
    global_security: list[SecurityRequirement] = Field(default_factory=list)
    # Ownership / governance metadata (CODEOWNERS-style mapping target)
    owner: str | None = None
    team: str | None = None
    product: str | None = None
    lifecycle_state: LifecycleState | None = None
    source_file: str | None = None
    source_location: SourceLocation | None = None

    def operation_keys(self) -> list[str]:
        return [op.key for op in self.operations]

    def find_operation(self, key: str) -> Operation | None:
        for op in self.operations:
            if op.key == key:
                return op
        return None


# --- Findings ---------------------------------------------------------------


class Severity(StrEnum):
    ERROR = "ERROR"
    WARN = "WARN"
    INFO = "INFO"


class Finding(BaseModel):
    """A single actionable result produced by any engine."""

    rule_id: str
    severity: Severity
    message: str
    operation_key: str | None = None
    location: SourceLocation | None = None
    new_location: SourceLocation | None = None
    change_id: str | None = None
    hint: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


# --- Changes ----------------------------------------------------------------


class ChangeKind(StrEnum):
    OPERATION_ADDED = "operation_added"
    OPERATION_REMOVED = "operation_removed"
    PARAMETER_ADDED = "parameter_added"
    PARAMETER_REMOVED = "parameter_removed"
    PARAMETER_REQUIREDNESS = "parameter_requiredness"
    PARAMETER_TYPE_CHANGED = "parameter_type_changed"
    PARAMETER_CONSTRAINT_CHANGED = "parameter_constraint_changed"
    ENUM_CHANGED = "enum_changed"
    REQUEST_SCHEMA_CHANGED = "request_schema_changed"
    RESPONSE_SCHEMA_CHANGED = "response_schema_changed"
    RESPONSE_ADDED = "response_added"
    RESPONSE_REMOVED = "response_removed"
    HEADER_ADDED = "header_added"
    HEADER_REMOVED = "header_removed"
    HEADER_CHANGED = "header_changed"
    SECURITY_CHANGED = "security_changed"
    DEPRECATION_ADDED = "deprecation_added"
    DEPRECATION_REMOVED = "deprecation_removed"
    DESCRIPTION_CHANGED = "description_changed"
    EXAMPLE_CHANGED = "example_changed"
    SERVER_CHANGED = "server_changed"
    # GraphQL-specific
    FIELD_REMOVED = "field_removed"
    FIELD_ADDED = "field_added"
    NULLABILITY_CHANGED = "nullability_changed"
    ARGUMENT_ADDED = "argument_added"
    # gRPC-specific
    RPC_REMOVED = "rpc_removed"
    RPC_ADDED = "rpc_added"
    FIELD_NUMBER_REUSED = "field_number_reused"
    WIRE_TYPE_CHANGED = "wire_type_changed"


class Change(BaseModel):
    """A semantic difference between two contracts."""

    id: str  # stable change ID
    kind: ChangeKind
    direction: str  # "request" | "response" | "meta" | "security"
    operation_key: str
    description: str
    old_location: SourceLocation | None = None
    new_location: SourceLocation | None = None
    old_value: Any | None = None
    new_value: Any | None = None
    breaking_hint: str | None = None


SchemaNode.model_rebuild()


# SDK-facing alias: a Service IS the normalized contract.
Contract = Service
