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
    #: Model Context Protocol. The contract is a server's `tools/list`
    #: manifest: the tools an agent can call, and the JSON Schemas they accept
    #: and return.
    MCP = "mcp"
    #: SOAP, described by a WSDL 1.1 document. The oldest format here and the
    #: one most likely to be read only by generated stubs, which is exactly why
    #: an unnoticed change to it surfaces as a deserialization failure rather
    #: than as a confused developer.
    SOAP = "soap"


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
    #: OpenAPI discriminator: {"propertyName": ..., "mapping": {value: ref}}.
    #: Kept as a plain dict because only its identity matters to the diff --
    #: which values map to which variant -- not the resolved schemas.
    # --- protobuf ---------------------------------------------------------
    #: Field number -> field name, for a message. Protobuf identity is the
    #: number, not the name: renaming a field is source-breaking and wire-safe,
    #: while reusing a number for a different field silently corrupts data
    #: written by older clients. A name-keyed comparison cannot tell those two
    #: apart, so the numbering is carried alongside.
    field_numbers: dict[int, str] = Field(default_factory=dict)
    #: Field numbers a message has retired. Reusing one is the mistake
    #: `reserved` exists to prevent.
    reserved_numbers: list[int] = Field(default_factory=list)
    #: Field names a message has retired.
    reserved_names: list[str] = Field(default_factory=list)
    #: Fields with explicit presence -- proto3 `optional`, or membership in a
    #: oneof. Removing explicit presence is a behaviour change: a field that
    #: could be distinguished from its default no longer can be.
    explicit_presence: list[str] = Field(default_factory=list)
    #: oneof name -> the fields in it. Moving a field into or out of a oneof
    #: changes what a message is allowed to contain.
    oneofs: dict[str, list[str]] = Field(default_factory=dict)

    discriminator: dict[str, Any] | None = None
    one_of: list[SchemaNode] | None = None
    any_of: list[SchemaNode] | None = None
    all_of: list[SchemaNode] | None = None
    not_: SchemaNode | None = Field(default=None, alias="not")

    # --- JSON Schema 2020-12 ------------------------------------------------
    #
    # Everything below was parsed away and dropped. A schema using
    # `dependentRequired` carried a rule the differ could not see, so
    # tightening it was invisible and `validate_value` accepted data the
    # document forbids -- the two worst outcomes a contract tool has, in one
    # keyword. Modeled now, and the keywords still missing are listed in
    # `docs/spec-support.md` rather than left to be discovered.
    #
    #: Positional item schemas. `prefixItems: [string, integer]` is a tuple,
    #: and is a different contract from `items: {string|integer}`.
    prefix_items: list[SchemaNode] | None = None
    #: `contains` with its bounds. An array that must hold at least one member
    #: of a shape is a constraint no other keyword expresses.
    contains: SchemaNode | None = None
    min_contains: int | None = None
    max_contains: int | None = None
    #: Regex -> schema for properties whose *name* matches.
    pattern_properties: dict[str, SchemaNode] = Field(default_factory=dict)
    #: A schema every property name must satisfy.
    property_names: SchemaNode | None = None
    #: Property -> properties it makes required. Adding an entry narrows what
    #: a caller may send, which is exactly a breaking change.
    dependent_required: dict[str, list[str]] = Field(default_factory=dict)
    #: Property -> schema applied when that property is present.
    dependent_schemas: dict[str, SchemaNode] = Field(default_factory=dict)
    #: `if`/`then`/`else`. Named with a suffix because two of the three are
    #: Python keywords; the aliases keep round-tripping honest.
    if_schema: SchemaNode | None = Field(default=None, alias="if")
    then_schema: SchemaNode | None = Field(default=None, alias="then")
    else_schema: SchemaNode | None = Field(default=None, alias="else")
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
    #: OpenAPI 3.2: the entire query string as one Schema Object, for APIs
    #: whose filters are a structured document rather than a list of pairs.
    #: Distinct from QUERY -- a change to it is a change to every filter at
    #: once, not to one parameter.
    QUERYSTRING = "querystring"


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


class Link(BaseModel):
    """An OpenAPI `links` entry: what you can call next, and with what.

    This is the only relationship between operations that a spec states
    outright. Everything else -- naming conventions, path prefixes, the shape
    of an id -- is inference, and inference is how a tool ends up suggesting a
    DELETE nobody asked for. `stateful/infer.py` uses only this.
    """

    name: str
    #: Exactly one of these is set, per the specification.
    operation_id: str | None = None
    operation_ref: str | None = None
    description: str | None = None
    #: Parameter name -> runtime expression, e.g. `id` -> `$response.body#/id`.
    parameters: dict[str, str] = Field(default_factory=dict)
    request_body: Any = None


class Response(BaseModel):
    status: str  # "200", "4XX", "default"
    description: str | None = None
    headers: dict[str, SchemaNode] = Field(default_factory=dict)
    content: dict[str, SchemaNode] = Field(default_factory=dict)
    links: list[Link] = Field(default_factory=list)
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
    scopes: dict[str, str] = Field(default_factory=dict)  # union of all flow scopes
    #: Declared OAuth2 flow names -> the scopes each grants. Kept per-flow as
    #: well as unioned into `scopes`, because dropping a *flow* is breaking in a
    #: way that dropping one scope from one flow is not.
    #:
    #: OpenAPI 3.2 adds `deviceAuthorization`, for inputs a browser cannot
    #: reach -- TVs, kiosks, CLIs on headless machines.
    oauth_flows: dict[str, dict[str, str]] = Field(default_factory=dict)
    #: 3.2 `oauth2MetadataUrl`: where a client discovers the provider's
    #: configuration.
    metadata_url: str | None = None
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
    MCP_TOOL = "mcp_tool"  # a tool an MCP server exposes through tools/list
    #: A WSDL `portType` operation. Deliberately has no branch in `key` below:
    #: `portType.operation` is already the identity SOAP dispatches on, which
    #: is what the fallback produces. Method and path are left unset on
    #: purpose -- every operation on a port shares one URL and one verb, so
    #: keying on them would collapse the whole service into one entry.
    SOAP_OPERATION = "soap_operation"


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
    #: `x-*` keys the document carried on this operation, verbatim.
    #:
    #: Kept because a contract says things the specification has no field for,
    #: and dropping them means a check cannot see what the author wrote down.
    #: `x-sunset` is the case that forced it: a deprecation with a retirement
    #: date is a plan, one without is an intention, and only the extension
    #: distinguishes them.
    extensions: dict[str, Any] = Field(default_factory=dict)
    # gRPC streaming. Captured because changing either of these changes the
    # wire protocol: a client generated against a unary RPC cannot call a
    # streaming one, so the two are not the same method with a new shape --
    # they are incompatible methods with the same name.
    client_streaming: bool = False
    server_streaming: bool = False

    # Event-driven extensions (AsyncAPI channels, SSE events, WebSocket messages)
    channel: str | None = None  # topic/channel/event name
    message_name: str | None = None
    #: Normalized to the application's point of view: "send" means the
    #: application produces this message, "receive" means it consumes one.
    #:
    #: AsyncAPI 2 and 3 disagree about this and the disagreement is inverted,
    #: which is why it is normalized rather than stored raw. In 2.x,
    #: `subscribe` describes messages *produced by* the application, and
    #: `publish` describes messages *consumed by* it -- the words read
    #: backwards because they are written from the client's side. AsyncAPI 3
    #: replaced them with `send`/`receive` from the application's side. Storing
    #: the raw word made a 2.x document and its own 3.x migration look like
    #: two unrelated contracts.
    direction: str | None = None  # "send" | "receive" | "request" | "response"
    #: The word the document actually used, kept so a report can quote it.
    source_action: str | None = None
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
        if self.kind == OperationKind.EVENT:
            # The channel and the direction are part of the identity. Without
            # them two channels carrying a message of the same name collide,
            # and a message moving between channels -- or flipping from
            # received to sent -- is invisible to the diff.
            channel = self.channel or self.path or ""
            return f"{self.direction or '?'} {channel}#{self.message_name or self.rpc_name}"
        if self.kind == OperationKind.MCP_TOOL:
            # The tool name is the whole identity. `tools/call` dispatches on
            # it, `title` is display-only, and a Tool carries no version and no
            # namespace. This has to be its own branch rather than falling
            # through to `service_name.rpc_name` below: `service_name` holds
            # the manifest label, which is a filename, so two dumps of the same
            # server would diff as a total replacement.
            return f"tool {self.rpc_name}"
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
    #: OpenAPI 3.2 tag objects: `name`, and optionally `summary`, `parent` and
    #: `kind`. Structured navigation was previously only expressible through
    #: the `x-tagGroups` vendor extension, so a contract that declares it is
    #: saying something a diff should be able to see.
    tags: list[dict[str, Any]] = Field(default_factory=list)
    # Ownership / governance metadata (CODEOWNERS-style mapping target)
    owner: str | None = None
    team: str | None = None
    product: str | None = None
    lifecycle_state: LifecycleState | None = None
    source_file: str | None = None
    source_location: SourceLocation | None = None
    #: External references this contract declares, as the document writes them
    #: -- `../shared/customer.yaml`, `https://schemas.example.com/money.yaml`.
    #:
    #: The bundler has always recorded them (`BundleResult.rewritten`) and
    #: nothing read the list, so a run that pulled four files reported a
    #: `contract_hash` for the entry document and said nothing about the other
    #: three. Provenance that does not name what it came from is worse than
    #: absent, and a `$ref` to somebody else's server is a supply chain.
    #:
    #: Out of the diffable surface on purpose: which files a contract is
    #: assembled from is provenance, not contract. Splitting one document into
    #: three is not a change to the API.
    dependencies: list[str] = Field(default_factory=list)
    #: Protocol-specific facts about the contract as a whole, mirroring
    #: :attr:`Operation.bindings`. Kept out of the diffable surface on purpose:
    #: an MCP manifest records here whether it was a truncated page and which
    #: protocol era it came from, neither of which is a change to the contract.
    bindings: dict[str, Any] = Field(default_factory=dict)

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
    # JSON Schema 2020-12. Distinct kinds rather than a generic
    # SCHEMA_CHANGED, so `breaking.py` can classify them structurally instead
    # of matching on the wording of a description.
    DEPENDENT_REQUIRED_CHANGED = "dependent_required_changed"
    DEPENDENT_SCHEMA_CHANGED = "dependent_schema_changed"
    TUPLE_SHAPE_CHANGED = "tuple_shape_changed"
    PATTERN_PROPERTIES_CHANGED = "pattern_properties_changed"
    CONDITIONAL_SCHEMA_CHANGED = "conditional_schema_changed"
    CONTAINS_CHANGED = "contains_changed"
    PROPERTY_NAMES_CHANGED = "property_names_changed"
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
    RPC_STREAMING_CHANGED = "rpc_streaming_changed"
    FIELD_PRESENCE_CHANGED = "field_presence_changed"
    ONEOF_MEMBERSHIP_CHANGED = "oneof_membership_changed"
    RESERVATION_CHANGED = "reservation_changed"
    # MCP-specific
    TOOL_ANNOTATION_CHANGED = "tool_annotation_changed"
    TOOL_DESCRIPTION_CHANGED = "tool_description_changed"
    TOOL_OUTPUT_SCHEMA_CHANGED = "tool_output_schema_changed"
    TOOL_RENAME_SUSPECTED = "tool_rename_suspected"
    MANIFEST_TRUNCATED = "manifest_truncated"
    # SOAP-specific. All three are invisible to every schema rule and break
    # every generated stub, which is the combination that earns a kind of its
    # own rather than a description a classifier has to read.
    SOAP_ACTION_CHANGED = "soap_action_changed"
    SOAP_STYLE_CHANGED = "soap_style_changed"
    SOAP_VERSION_CHANGED = "soap_version_changed"


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
