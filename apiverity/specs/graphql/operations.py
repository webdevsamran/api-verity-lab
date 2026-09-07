"""Operation-level GraphQL: query generation, envelopes, drift (#16).

The SDL adapter normalizes a schema into the shared model, which is enough for
structural diffing and not enough to *exercise* an endpoint. GraphQL differs
from HTTP in three ways that the generic machinery cannot paper over, and each
one is handled here rather than bent into the HTTP shape:

- **One URL, many operations.** Every request is a POST to the same path, so
  "which operation failed" lives in the query text, not the route.
- **Errors come back as 200.** A GraphQL server answers a malformed query with
  HTTP 200 and an `errors` array. Judging success by status code -- which is
  what the HTTP runner does -- marks every failure as a pass.
- **The client picks the response shape.** There is no fixed response body to
  validate; you get back the fields you asked for, so a case has to assert
  against its own selection set.

Introspection is the drift source: it is the one way to ask a live endpoint
what it actually serves, and comparing that to the committed SDL is what
"undocumented field usage" means for GraphQL.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "INTROSPECTION_QUERY",
    "EnvelopeProblem",
    "GraphQLCase",
    "build_cases",
    "check_envelope",
    "compare_introspection",
    "load_persisted_operations",
]


@dataclass
class GraphQLCase:
    """One query to send, and what a correct server does with it."""

    name: str
    query: str
    variables: dict[str, Any] = field(default_factory=dict)
    #: "positive" -- must return data and no errors.
    #: "negative" -- must return errors; returning data instead means the
    #: server accepted something its own schema forbids.
    kind: str = "positive"
    description: str = ""
    #: Dotted paths the response must contain, for positive cases. Derived
    #: from the selection set, because that is the only thing that says what
    #: the response should look like.
    expect_paths: list[str] = field(default_factory=list)


@dataclass
class EnvelopeProblem:
    """Something wrong with a `{data, errors}` response."""

    message: str
    fatal: bool = True


# --------------------------------------------------------------- generation

#: Values used for required arguments. Deliberately boring: the point of a
#: generated positive case is to be accepted, so the interesting values belong
#: in the negative cases below.
_SCALAR_VALUES: dict[str, Any] = {
    "Int": 1,
    "Float": 1.5,
    "String": "apiverity",
    "Boolean": True,
    "ID": "1",
}

#: A value of the wrong type for each scalar, for negative cases. `Int` gets a
#: string rather than a float, because a float is a *coercion* error some
#: servers accept and a string is unambiguous.
_WRONG_VALUES: dict[str, Any] = {
    "Int": "not-an-int",
    "Float": "not-a-float",
    "String": {"nested": "object"},
    "Boolean": "yes",
    "ID": {"nested": "object"},
}


def _unwrap(type_node: Any) -> tuple[Any, bool, bool]:
    """Strip NonNull and List wrappers.

    Returns (named type, required, is_list). Requiredness has to come from the
    outermost NonNull: `[String!]` is an optional list of required strings,
    and treating it as required would generate an argument the schema does not
    demand.
    """
    from graphql import GraphQLList, GraphQLNonNull

    required = isinstance(type_node, GraphQLNonNull)
    if required:
        type_node = type_node.of_type
    is_list = isinstance(type_node, GraphQLList)
    if is_list:
        type_node = type_node.of_type
        if isinstance(type_node, GraphQLNonNull):
            type_node = type_node.of_type
    return type_node, required, is_list


def _literal(value: Any) -> str:
    """Render a Python value as a GraphQL literal.

    Not `json.dumps`: GraphQL object keys are bare names, not strings, and
    enum values are bare too. Feeding JSON into a query is a syntax error the
    server reports as *your* mistake.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if isinstance(value, list):
        return "[" + ", ".join(_literal(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{" + ", ".join(f"{k}: {_literal(v)}" for k, v in value.items()) + "}"
    return _literal(str(value))


def _argument_value(type_node: Any, *, wrong: bool = False) -> Any:
    from graphql import GraphQLEnumType, GraphQLInputObjectType, GraphQLScalarType

    named, _required, is_list = _unwrap(type_node)
    table = _WRONG_VALUES if wrong else _SCALAR_VALUES
    if isinstance(named, GraphQLScalarType):
        value = table.get(named.name, "apiverity" if not wrong else {"nested": 1})
    elif isinstance(named, GraphQLEnumType):
        values = list(named.values)
        value = (
            ("APIVERITY_NOT_A_MEMBER" if wrong else values[0])
            if values
            else "APIVERITY_NOT_A_MEMBER"
        )
        return [value] if is_list else _EnumLiteral(str(value))
    elif isinstance(named, GraphQLInputObjectType):
        value = {
            name: _argument_value(f.type, wrong=wrong)
            for name, f in named.fields.items()
            if isinstance(f.type, type(f.type)) and _unwrap(f.type)[1]
        }
    else:
        value = table.get("String", "apiverity")
    return [value] if is_list else value


class _EnumLiteral(str):
    """An enum value, which must render unquoted."""


def _render_enum(value: Any) -> str | None:
    return str(value) if isinstance(value, _EnumLiteral) else None


def _arguments(field_def: Any, *, wrong_arg: str | None = None, omit: str | None = None) -> str:
    """Render an argument list, supplying every required argument.

    `omit` drops one, which is how the "required argument missing" case is
    built. Renaming it instead would produce two violations at once -- an
    unknown argument as well as a missing one -- and a case whose name no
    longer describes what it tests.
    """
    parts: list[str] = []
    for name, arg in field_def.args.items():
        if name == omit:
            continue
        _named, required, _is_list = _unwrap(arg.type)
        if not required and name != wrong_arg:
            continue
        value = _argument_value(arg.type, wrong=name == wrong_arg)
        rendered = _render_enum(value) or _literal(value)
        parts.append(f"{name}: {rendered}")
    return f"({', '.join(parts)})" if parts else ""


def _selection(type_node: Any, depth: int = 0) -> str:
    """A selection set for a field's return type.

    Leaf scalars need no selection; object types need at least one field, and
    a query that selects an object without sub-fields is a syntax error rather
    than an empty result. Depth is capped because a schema can be cyclic --
    `User.friends: [User]` is ordinary -- and a selection set cannot be.
    """
    from graphql import (
        GraphQLInterfaceType,
        GraphQLObjectType,
        GraphQLUnionType,
    )

    named, _required, _is_list = _unwrap(type_node)
    if isinstance(named, GraphQLUnionType):
        return " { __typename }"
    if not isinstance(named, (GraphQLObjectType, GraphQLInterfaceType)):
        return ""
    if depth >= 3:
        return " { __typename }"

    parts: list[str] = []
    for name, sub in named.fields.items():
        sub_named, _r, _l = _unwrap(sub.type)
        if isinstance(sub_named, (GraphQLObjectType, GraphQLInterfaceType, GraphQLUnionType)):
            if depth >= 2:
                continue
            nested = _selection(sub.type, depth + 1)
            if nested:
                parts.append(f"{name}{_arguments(sub)}{nested}")
        else:
            parts.append(f"{name}{_arguments(sub)}")
        if len(parts) >= 6:
            break
    if not parts:
        parts.append("__typename")
    return " { " + " ".join(parts) + " }"


def _paths(field_name: str) -> list[str]:
    """Response paths a positive case should produce.

    Just the root field: a nullable field legitimately comes back null, and
    asserting on anything deeper would fail a server that is behaving
    correctly for an id that does not exist.
    """
    return [f"data.{field_name}"]


def build_cases(schema: Any, *, include_mutations: bool = False) -> list[GraphQLCase]:
    """Positive and negative cases for every root field.

    Mutations are excluded by default and gated behind a flag. A generated
    mutation is a write against whatever `--base-url` names, and a testing
    tool that performs writes nobody asked for is a tool people stop pointing
    at anything real.
    """
    cases: list[GraphQLCase] = []
    roots: list[tuple[str, Any]] = [("query", schema.query_type)]
    if include_mutations and schema.mutation_type is not None:
        roots.append(("mutation", schema.mutation_type))

    for kind, root in roots:
        if root is None:
            continue
        for field_name, field_def in root.fields.items():
            selection = _selection(field_def.type)
            args = _arguments(field_def)
            body = f"{field_name}{args}{selection}"
            cases.append(
                GraphQLCase(
                    name=f"{kind}:{field_name}",
                    query=f"{kind} {{ {body} }}",
                    kind="positive",
                    description=f"valid {kind} for '{field_name}'",
                    expect_paths=_paths(field_name),
                )
            )

            # A field the schema does not declare. The server must reject it;
            # one that answers is serving something undocumented.
            cases.append(
                GraphQLCase(
                    name=f"{kind}:{field_name}:unknown-field",
                    query=f"{kind} {{ apiverityFieldThatDoesNotExist }}",
                    kind="negative",
                    description="a field that is not in the schema",
                )
            )

            for arg_name, arg in field_def.args.items():
                _named, required, _is_list = _unwrap(arg.type)
                if required:
                    without = _arguments(field_def, omit=arg_name)
                    cases.append(
                        GraphQLCase(
                            name=f"{kind}:{field_name}:missing-{arg_name}",
                            query=f"{kind} {{ {field_name}{without}{selection} }}",
                            kind="negative",
                            description=f"required argument '{arg_name}' omitted",
                        )
                    )
                cases.append(
                    GraphQLCase(
                        name=f"{kind}:{field_name}:bad-{arg_name}",
                        query=(
                            f"{kind} {{ {field_name}"
                            f"{_arguments(field_def, wrong_arg=arg_name)}{selection} }}"
                        ),
                        kind="negative",
                        description=f"argument '{arg_name}' given the wrong type",
                    )
                )
    # Deduplicate the shared unknown-field probe; one per schema is enough.
    seen: set[str] = set()
    unique: list[GraphQLCase] = []
    for case in cases:
        key = case.query if case.name.endswith("unknown-field") else case.name
        if key in seen:
            continue
        seen.add(key)
        unique.append(case)
    return unique


# ----------------------------------------------------------------- envelopes


def _walk(data: Any, path: str) -> bool:
    cursor = data
    for part in path.split("."):
        if isinstance(cursor, list):
            cursor = cursor[0] if cursor else None
        if not isinstance(cursor, dict) or part not in cursor:
            return False
        cursor = cursor[part]
    return True


def check_envelope(case: GraphQLCase, status: int, body: Any) -> list[EnvelopeProblem]:
    """Validate a `{data, errors}` response against what the case expected.

    This is the piece the HTTP runner cannot do. A GraphQL server answers a
    malformed query with **HTTP 200** and an `errors` array, so judging by
    status alone marks every failure a pass.
    """
    problems: list[EnvelopeProblem] = []
    if status >= 500:
        return [EnvelopeProblem(f"server returned {status}; a GraphQL error should be 200")]
    if not isinstance(body, dict):
        return [EnvelopeProblem("response body is not a JSON object")]
    if "data" not in body and "errors" not in body:
        return [EnvelopeProblem("response has neither 'data' nor 'errors'")]

    errors = body.get("errors")
    if errors is not None:
        if not isinstance(errors, list) or not errors:
            problems.append(EnvelopeProblem("'errors' must be a non-empty list when present"))
        else:
            for index, error in enumerate(errors):
                if not isinstance(error, dict) or not str(error.get("message", "")).strip():
                    problems.append(EnvelopeProblem(f"errors[{index}] has no message", fatal=False))

    if case.kind == "positive":
        if errors:
            messages = "; ".join(str(e.get("message", "")) for e in errors if isinstance(e, dict))
            problems.append(EnvelopeProblem(f"valid query returned errors: {messages}"))
        if body.get("data") is None:
            problems.append(EnvelopeProblem("valid query returned no data"))
        else:
            for path in case.expect_paths:
                if not _walk(body, path):
                    problems.append(EnvelopeProblem(f"response is missing '{path}'"))
    else:
        if not errors:
            problems.append(
                EnvelopeProblem(
                    "invalid query was accepted: the server returned no errors for a "
                    "query its own schema forbids"
                )
            )
    return problems


# --------------------------------------------------------------- persisted


def _root_paths(definition: Any) -> list[str]:
    """Top-level response keys a persisted operation should produce.

    Only FieldNodes have a name -- a fragment spread or inline fragment does
    not contribute a key of its own, so it contributes no path.
    """
    from graphql import FieldNode

    return [
        f"data.{(sel.alias or sel.name).value}"
        for sel in definition.selection_set.selections
        if isinstance(sel, FieldNode)
    ]


def load_persisted_operations(text: str, label: str = "") -> list[GraphQLCase]:
    """Read a `.graphql` document of persisted operations.

    Only named operations become cases. An anonymous one cannot be referred to
    in a report or re-run from it, and a document of several anonymous
    operations is invalid GraphQL anyway.
    """
    from graphql import OperationDefinitionNode, parse, print_ast

    document = parse(text)
    cases: list[GraphQLCase] = []
    for definition in document.definitions:
        if not isinstance(definition, OperationDefinitionNode):
            continue
        if definition.name is None:
            continue
        name = definition.name.value
        cases.append(
            GraphQLCase(
                name=name,
                query=print_ast(definition),
                kind="positive",
                description=f"persisted {definition.operation.value} '{name}'"
                + (f" from {label}" if label else ""),
                expect_paths=_root_paths(definition),
            )
        )
    return cases


# ------------------------------------------------------------- introspection

#: Deliberately minimal. The full introspection query is enormous and many
#: servers cap query depth or complexity; asking only for what the comparison
#: uses is far more likely to be answered.
INTROSPECTION_QUERY = """
query ApiverityIntrospection {
  __schema {
    queryType { name }
    mutationType { name }
    types {
      kind
      name
      fields(includeDeprecated: true) {
        name
        args { name type { kind name ofType { kind name } } }
        type { kind name ofType { kind name ofType { kind name } } }
      }
      enumValues(includeDeprecated: true) { name }
    }
  }
}
"""


def _introspected_fields(payload: Any) -> dict[str, set[str]]:
    """type name -> field names, from an introspection response."""
    schema = (payload or {}).get("data", {}).get("__schema") or {}
    out: dict[str, set[str]] = {}
    for entry in schema.get("types") or []:
        name = entry.get("name") or ""
        if not name or name.startswith("__"):
            continue
        fields = entry.get("fields")
        if not fields:
            continue
        out[name] = {f.get("name") for f in fields if f.get("name")}
    return out


def _declared_fields(schema: Any) -> dict[str, set[str]]:
    from graphql import GraphQLInterfaceType, GraphQLObjectType

    out: dict[str, set[str]] = {}
    for name, type_def in schema.type_map.items():
        if name.startswith("__"):
            continue
        if isinstance(type_def, (GraphQLObjectType, GraphQLInterfaceType)):
            out[name] = set(type_def.fields)
    return out


def compare_introspection(schema: Any, payload: Any) -> list[dict[str, Any]]:
    """Drift between the committed SDL and what the endpoint actually serves.

    Two directions, and they are not the same problem:

    - **Undocumented**: the server serves a type or field the SDL does not
      declare. Clients can and will discover it through introspection, and
      then depend on something nobody agreed to support. This is what the
      issue means by "undocumented field usage".
    - **Missing**: the SDL declares something the server does not serve. Any
      client generated from the schema will ask for it and fail.
    """
    served = _introspected_fields(payload)
    declared = _declared_fields(schema)
    findings: list[dict[str, Any]] = []

    for type_name in sorted(set(served) - set(declared)):
        findings.append(
            {
                "rule_id": "GQL-DRIFT-UNDECLARED-TYPE",
                "severity": "WARN",
                "type": type_name,
                "message": f"endpoint serves type '{type_name}', which the schema does not declare",
            }
        )
    for type_name in sorted(set(declared) - set(served)):
        findings.append(
            {
                "rule_id": "GQL-DRIFT-MISSING-TYPE",
                "severity": "ERROR",
                "type": type_name,
                "message": f"schema declares type '{type_name}', which the endpoint does not serve",
            }
        )
    for type_name in sorted(set(served) & set(declared)):
        for field_name in sorted(served[type_name] - declared[type_name]):
            findings.append(
                {
                    "rule_id": "GQL-DRIFT-UNDECLARED-FIELD",
                    "severity": "WARN",
                    "type": type_name,
                    "field": field_name,
                    "message": (
                        f"endpoint serves '{type_name}.{field_name}', which the schema "
                        "does not declare"
                    ),
                }
            )
        for field_name in sorted(declared[type_name] - served[type_name]):
            findings.append(
                {
                    "rule_id": "GQL-DRIFT-MISSING-FIELD",
                    "severity": "ERROR",
                    "type": type_name,
                    "field": field_name,
                    "message": (
                        f"schema declares '{type_name}.{field_name}', which the endpoint "
                        "does not serve"
                    ),
                }
            )
    return findings
