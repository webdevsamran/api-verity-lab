"""Normalized, spec-neutral contract model.

Every supported specification format (OpenAPI, GraphQL SDL, protobuf) is
compiled into these types. All downstream engines (diff, rules, fuzz,
drift, coverage, reports) operate exclusively on this model.

Every entity preserves a :class:`SourceLocation` pointing at the original
spec document so findings can link to exact lines.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


class Protocol(str, Enum):
    """Wire protocol of a contract."""

    OPENAPI = "openapi"
    GRAPHQL = "graphql"
    GRPC = "grpc"


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

    type: Optional[str] = None  # object|array|string|integer|number|boolean|null
    format: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    nullable: bool = False
    deprecated: bool = False
    enum: Optional[list[Any]] = None
    const: Optional[Any] = None
    default: Optional[Any] = None
    example: Optional[Any] = None
    # object constraints
    properties: dict[str, "SchemaNode"] = Field(default_factory=dict)
    required: list[str] = Field(default_factory=list)
    additional_properties: Optional[Union[bool, "SchemaNode"]] = None
    min_properties: Optional[int] = None
    max_properties: Optional[int] = None
    # array constraints
    items: Optional["SchemaNode"] = None
    min_items: Optional[int] = None
    max_items: Optional[int] = None
    unique_items: Optional[bool] = None
    # string constraints
    min_length: Optional[int] = None
    max_length: Optional[int] = None
    pattern: Optional[str] = None
    # numeric constraints
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    exclusive_minimum: Optional[float] = None
    exclusive_maximum: Optional[float] = None
    multiple_of: Optional[float] = None
    # composition
    one_of: Optional[list["SchemaNode"]] = None
    any_of: Optional[list["SchemaNode"]] = None
    all_of: Optional[list["SchemaNode"]] = None
    not_: Optional["SchemaNode"] = Field(default=None, alias="not")
    # provenance
    source_location: Optional[SourceLocation] = None

    model_config = ConfigDict(populate_by_name=True)

    def iter_property_names(self) -> list[str]:
        return list(self.properties.keys())


class ParameterLocation(str, Enum):
    PATH = "path"
    QUERY = "query"
    HEADER = "header"
    COOKIE = "cookie"


class Parameter(BaseModel):
    name: str
    location: ParameterLocation
    required: bool = False
    deprecated: bool = False
    description: Optional[str] = None
    schema_node: Optional[SchemaNode] = None
    example: Optional[Any] = None
    source_location: Optional[SourceLocation] = None


class RequestBody(BaseModel):
    required: bool = False
    description: Optional[str] = None
    content: dict[str, SchemaNode] = Field(default_factory=dict)  # media type -> schema
    source_location: Optional[SourceLocation] = None


class Response(BaseModel):
    status: str  # "200", "4XX", "default"
    description: Optional[str] = None
    headers: dict[str, SchemaNode] = Field(default_factory=dict)
    content: dict[str, SchemaNode] = Field(default_factory=dict)
    source_location: Optional[SourceLocation] = None


class SecurityRequirement(BaseModel):
    """A named security scheme plus required scopes."""

    scheme_name: str
    scopes: list[str] = Field(default_factory=list)


class SecurityScheme(BaseModel):
    name: str
    type: str  # apiKey | http | oauth2 | openIdConnect | mutualTLS
    location: Optional[ParameterLocation] = None  # for apiKey
    scheme: Optional[str] = None  # bearer, basic, digest for http
    bearer_format: Optional[str] = None
    deprecated: bool = False
    source_location: Optional[SourceLocation] = None


class Example(BaseModel):
    name: str
    value: Optional[Any] = None
    summary: Optional[str] = None
    source_location: Optional[SourceLocation] = None


class OperationKind(str, Enum):
    HTTP = "http"
    GRAPHQL_FIELD = "graphql_field"
    GRPC_RPC = "grpc_rpc"


class Operation(BaseModel):
    """A single callable unit of the contract.

    For HTTP: ``method`` + ``path``. For GraphQL: a field on a root type.
    For gRPC: an RPC on a service.
    """

    kind: OperationKind = OperationKind.HTTP
    operation_id: Optional[str] = None
    method: Optional[str] = None  # GET/POST/... (HTTP)
    path: Optional[str] = None  # /users/{id} (HTTP)
    rpc_name: Optional[str] = None  # gRPC
    service_name: Optional[str] = None  # gRPC / GraphQL root type
    summary: Optional[str] = None
    description: Optional[str] = None
    deprecated: bool = False
    tags: list[str] = Field(default_factory=list)
    parameters: list[Parameter] = Field(default_factory=list)
    request_body: Optional[RequestBody] = None
    responses: list[Response] = Field(default_factory=list)
    security: Optional[list[SecurityRequirement]] = None  # None = inherit global
    examples: list[Example] = Field(default_factory=list)
    source_location: Optional[SourceLocation] = None

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
    description: Optional[str] = None


class Service(BaseModel):
    """Top-level normalized contract."""

    title: str
    version: str
    protocol: Protocol
    description: Optional[str] = None
    servers: list[Server] = Field(default_factory=list)
    operations: list[Operation] = Field(default_factory=list)
    security_schemes: dict[str, SecurityScheme] = Field(default_factory=dict)
    global_security: list[SecurityRequirement] = Field(default_factory=list)
    source_file: Optional[str] = None
    source_location: Optional[SourceLocation] = None

    def operation_keys(self) -> list[str]:
        return [op.key for op in self.operations]

    def find_operation(self, key: str) -> Optional[Operation]:
        for op in self.operations:
            if op.key == key:
                return op
        return None


# --- Findings ---------------------------------------------------------------


class Severity(str, Enum):
    ERROR = "ERROR"
    WARN = "WARN"
    INFO = "INFO"


class Finding(BaseModel):
    """A single actionable result produced by any engine."""

    rule_id: str
    severity: Severity
    message: str
    operation_key: Optional[str] = None
    location: Optional[SourceLocation] = None
    new_location: Optional[SourceLocation] = None
    change_id: Optional[str] = None
    hint: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


# --- Changes ----------------------------------------------------------------


class ChangeKind(str, Enum):
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
    old_location: Optional[SourceLocation] = None
    new_location: Optional[SourceLocation] = None
    old_value: Optional[Any] = None
    new_value: Optional[Any] = None
    breaking_hint: Optional[str] = None

SchemaNode.model_rebuild()


# SDK-facing alias: a Service IS the normalized contract.
Contract = Service
