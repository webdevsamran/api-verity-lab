"""What a contract *declares* that is a problem on its own.

The checks that existed cover omissions -- no authentication, no rate-limit
metadata, a wildcard CORS header. These cover decisions someone wrote down: a
credential in a query string, an unbounded array on a request, an OAuth
requirement that names no scope. Every one is fixable by editing the line the
finding points at, which is the difference between a security check and a
lecture.

Half of these tests exist to prove a check *stays quiet*. A rule that fires on
ordinary contracts is a rule that gets switched off, and it takes the four
useful ones with it when it goes.
"""

from __future__ import annotations

from typing import Any

from apiverity.core.model import (
    Operation,
    Parameter,
    ParameterLocation,
    Protocol,
    RequestBody,
    Response,
    SchemaNode,
    SecurityRequirement,
    SecurityScheme,
    Service,
)
from apiverity.security import run_security_checks
from apiverity.security.hardening import run_hardening_checks


def _service(
    operations: list[Operation] | None = None,
    schemes: dict[str, SecurityScheme] | None = None,
    global_security: list[SecurityRequirement] | None = None,
) -> Service:
    return Service(
        title="fixture",
        version="1.0.0",
        protocol=Protocol.OPENAPI,
        operations=operations or [],
        security_schemes=schemes or {},
        global_security=global_security or [],
    )


def _rules(service: Service) -> dict[str, str]:
    return {f.rule_id: f.message for f in run_hardening_checks(service)}


def _post(body: SchemaNode) -> Operation:
    return Operation(
        operation_id="create",
        method="POST",
        path="/things",
        request_body=RequestBody(required=True, content={"application/json": body}),
    )


def _list(returns: SchemaNode, params: list[Parameter] | None = None) -> Operation:
    return Operation(
        operation_id="list",
        method="GET",
        path="/things",
        parameters=params or [],
        responses=[Response(status="200", content={"application/json": returns})],
    )


def _param(name: str) -> Parameter:
    return Parameter(
        name=name,
        location=ParameterLocation.QUERY,
        required=False,
        schema=SchemaNode(type="integer"),
    )


# ---------------------------------------------------------- unbounded arrays


def test_a_request_array_with_no_ceiling_is_reported() -> None:
    body = SchemaNode(
        type="object",
        properties={"ids": SchemaNode(type="array", items=SchemaNode(type="string"))},
    )
    fired = _rules(_service([_post(body)]))
    assert "SEC-ARRAY-UNBOUNDED" in fired
    assert "ids" in fired["SEC-ARRAY-UNBOUNDED"]


def test_a_bounded_array_is_not_reported() -> None:
    body = SchemaNode(
        type="object",
        properties={
            "ids": SchemaNode(type="array", items=SchemaNode(type="string"), max_items=100)
        },
    )
    assert "SEC-ARRAY-UNBOUNDED" not in _rules(_service([_post(body)]))


def test_a_nested_unbounded_array_is_found() -> None:
    """A ceiling on the outer list does nothing for the lists inside it."""
    body = SchemaNode(
        type="object",
        properties={
            "orders": SchemaNode(
                type="array",
                max_items=10,
                items=SchemaNode(
                    type="object",
                    properties={"lines": SchemaNode(type="array", items=SchemaNode())},
                ),
            )
        },
    )
    fired = _rules(_service([_post(body)]))
    assert "lines" in fired["SEC-ARRAY-UNBOUNDED"]


def test_a_response_array_is_not_a_request_problem() -> None:
    """The check is about work a *caller* can ask the server to do."""
    listing = _list(
        SchemaNode(type="array", items=SchemaNode(type="string")),
        params=[_param("limit")],
    )
    assert "SEC-ARRAY-UNBOUNDED" not in _rules(_service([listing]))


def test_a_recursive_schema_does_not_hang_the_walk() -> None:
    node = SchemaNode(type="object")
    node.properties = {"child": node}
    assert isinstance(_rules(_service([_post(node)])), dict)


def test_the_finding_caps_how_many_fields_it_lists() -> None:
    """Forty field names in one message is a message nobody finishes."""
    body = SchemaNode(
        type="object",
        properties={
            f"list{i}": SchemaNode(type="array", items=SchemaNode(type="string")) for i in range(40)
        },
    )
    message = _rules(_service([_post(body)]))["SEC-ARRAY-UNBOUNDED"]
    assert "and 35 more" in message


# ------------------------------------------------------------- pagination


def test_a_list_endpoint_with_no_pagination_is_reported() -> None:
    listing = _list(SchemaNode(type="array", items=SchemaNode(type="string")))
    assert "SEC-COLLECTION-UNPAGINATED" in _rules(_service([listing]))


def test_any_of_the_usual_pagination_parameters_satisfies_it() -> None:
    array = SchemaNode(type="array", items=SchemaNode(type="string"))
    for name in ("limit", "cursor", "page_size", "perPage", "page_token", "top"):
        listing = _list(array, params=[_param(name)])
        assert "SEC-COLLECTION-UNPAGINATED" not in _rules(_service([listing])), name


def test_a_parameter_that_merely_contains_a_pagination_word_does_not_count() -> None:
    """`limited` is not `limit`.

    A substring match would quietly excuse an operation that has no pagination
    at all, which is worse than not checking: it reports clean.
    """
    listing = _list(
        SchemaNode(type="array", items=SchemaNode(type="string")),
        params=[_param("limited")],
    )
    assert "SEC-COLLECTION-UNPAGINATED" in _rules(_service([listing]))


def test_an_endpoint_that_returns_one_object_is_not_a_collection() -> None:
    single = Operation(
        operation_id="get",
        method="GET",
        path="/things/{id}",
        responses=[Response(status="200", content={"application/json": SchemaNode(type="object")})],
    )
    assert "SEC-COLLECTION-UNPAGINATED" not in _rules(_service([single]))


def test_a_mutation_is_not_checked_for_pagination() -> None:
    creating = Operation(
        operation_id="create",
        method="POST",
        path="/things",
        responses=[
            Response(
                status="200",
                content={"application/json": SchemaNode(type="array", items=SchemaNode())},
            )
        ],
    )
    assert "SEC-COLLECTION-UNPAGINATED" not in _rules(_service([creating]))


# ------------------------------------------------------ credential placement


def test_an_api_key_in_the_query_string_is_an_error() -> None:
    """A URL is written to access logs, proxy logs, history and `Referer`."""
    schemes = {"key": SecurityScheme(name="key", type="apiKey", location=ParameterLocation.QUERY)}
    fired = run_hardening_checks(_service(schemes=schemes))
    match = next(f for f in fired if f.rule_id == "SEC-APIKEY-IN-QUERY")
    assert match.severity.value == "ERROR"


def test_an_api_key_in_a_header_is_not_reported() -> None:
    schemes = {"key": SecurityScheme(name="key", type="apiKey", location=ParameterLocation.HEADER)}
    assert "SEC-APIKEY-IN-QUERY" not in _rules(_service(schemes=schemes))


def test_http_basic_is_reported() -> None:
    schemes = {"basic": SecurityScheme(name="basic", type="http", scheme="Basic")}
    assert "SEC-BASIC-AUTH" in _rules(_service(schemes=schemes))


def test_bearer_is_not_reported() -> None:
    schemes = {"bearer": SecurityScheme(name="bearer", type="http", scheme="bearer")}
    assert "SEC-BASIC-AUTH" not in _rules(_service(schemes=schemes))


# ----------------------------------------------------------------- scopes


def _oauth(scopes: dict[str, str]) -> dict[str, SecurityScheme]:
    return {"oauth": SecurityScheme(name="oauth", type="oauth2", scopes=scopes)}


def _guarded(*scopes: str) -> Operation:
    return Operation(
        operation_id="op",
        method="GET",
        path="/things/{id}",
        security=[SecurityRequirement(scheme_name="oauth", scopes=list(scopes))],
    )


def test_an_operation_requiring_oauth_with_no_scope_is_reported() -> None:
    service = _service([_guarded()], schemes=_oauth({"read:things": "read"}))
    assert "SEC-SCOPE-UNSCOPED" in _rules(service)


def test_a_scheme_that_declares_no_scopes_has_nothing_to_narrow() -> None:
    """Reporting it would be reporting the absence of a feature the document
    never used."""
    service = _service([_guarded()], schemes=_oauth({}))
    assert "SEC-SCOPE-UNSCOPED" not in _rules(service)


def test_a_narrow_scope_is_not_reported() -> None:
    service = _service([_guarded("read:things")], schemes=_oauth({"read:things": "read"}))
    assert _rules(service) == {}


def test_a_scope_that_grants_everything_is_reported() -> None:
    service = _service([_guarded("admin")], schemes=_oauth({"admin": "everything"}))
    fired = _rules(service)
    assert "SEC-SCOPE-BROAD" in fired
    assert "admin" in fired["SEC-SCOPE-BROAD"]


def test_a_global_requirement_reaches_every_operation() -> None:
    """An operation with no `security` of its own inherits the contract's."""
    service = _service(
        [Operation(operation_id="op", method="GET", path="/x")],
        schemes=_oauth({"read": "r"}),
        global_security=[SecurityRequirement(scheme_name="oauth", scopes=["*"])],
    )
    assert "SEC-SCOPE-BROAD" in _rules(service)


# ------------------------------------------------------------ integration


def test_the_checks_run_as_part_of_validate() -> None:
    """A module nothing calls is a module that does nothing.

    `oauth_scopes.py` sat in this package, complete and imported by no code at
    all, for the whole life of the project.
    """
    schemes = {"key": SecurityScheme(name="key", type="apiKey", location=ParameterLocation.QUERY)}
    fired = {f.rule_id for f in run_security_checks(_service(schemes=schemes))}
    assert "SEC-APIKEY-IN-QUERY" in fired


def test_scope_coverage_is_reachable_from_the_package() -> None:
    from apiverity.security import analyze_scope_coverage

    service = _service([_guarded("read:things")], schemes=_oauth({"read:things": "r", "w": "w"}))
    coverage: Any = analyze_scope_coverage(service)
    assert coverage.unused_declared == {"w"}
    assert set(coverage.used_scopes) == {"read:things"}


def test_an_ordinary_contract_draws_nothing_from_this_module() -> None:
    """The whole point. A check that fires on everything is a check nobody keeps."""
    body = SchemaNode(
        type="object",
        properties={"name": SchemaNode(type="string")},
    )
    listing = _list(
        SchemaNode(type="array", items=SchemaNode(type="string")),
        params=[_param("limit")],
    )
    schemes = {"bearer": SecurityScheme(name="bearer", type="http", scheme="bearer")}
    assert _rules(_service([_post(body), listing], schemes=schemes)) == {}
