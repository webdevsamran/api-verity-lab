"""Operation-level GraphQL: generation, envelopes, drift (#16).

The acceptance criterion on the issue is behavioural -- `apiverity test
schema.graphql --base-url ...` runs positive and negative cases, and drift
reports undocumented field usage -- so the tests that matter here drive a real
`graphql-core` schema and a real executor rather than asserting on query
strings.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

graphql = pytest.importorskip(
    "graphql", reason="the graphql extra is a dev dependency; install it to run these"
)

from apiverity.specs.graphql.operations import (  # noqa: E402
    INTROSPECTION_QUERY,
    build_cases,
    check_envelope,
    compare_introspection,
    load_persisted_operations,
)

SDL = """\
type Query {
  user(id: ID!, verbose: Boolean): User
  search(term: String!, kind: Kind): [User!]!
  health: String!
}
type Mutation {
  createUser(input: NewUser!): User!
}
input NewUser { name: String!, email: String }
enum Kind { PERSON, ROBOT }
type User {
  id: ID!
  name: String!
  age: Int
  friends: [User!]
  status: Kind
}
"""


@pytest.fixture(scope="module")
def schema():
    return graphql.build_schema(SDL)


def _execute(schema: Any, query: str) -> dict[str, Any]:
    """Run a query against a real executor, the way a server would."""
    user = {"id": "1", "name": "Ada", "age": 36, "friends": [], "status": "PERSON"}
    root = {
        "user": lambda _info, **kw: {**user, "id": kw.get("id", "1")},
        "search": lambda _info, **kw: [user],
        "health": lambda _info, **kw: "ok",
        "createUser": lambda _info, **kw: user,
    }
    result = graphql.graphql_sync(schema, query, root_value=root)
    body: dict[str, Any] = {}
    if result.data is not None:
        body["data"] = result.data
    if result.errors:
        body["errors"] = [{"message": e.message} for e in result.errors]
    return body


# ------------------------------------------------------------------ generation


def test_every_generated_query_parses(schema) -> None:
    """A case the server rejects as a syntax error tests nothing about it."""
    for case in build_cases(schema, include_mutations=True):
        graphql.parse(case.query)


def test_positive_cases_are_accepted_by_a_correct_server(schema) -> None:
    """The whole point: a generated positive case must actually be valid.

    Executed against graphql-core itself, so "valid" means what the reference
    implementation says, not what this generator hopes.
    """
    for case in build_cases(schema):
        if case.kind != "positive":
            continue
        body = _execute(schema, case.query)
        assert "errors" not in body, f"{case.name}: {body.get('errors')}"
        assert body.get("data") is not None, case.name


def test_negative_cases_are_rejected_by_a_correct_server(schema) -> None:
    """And the converse: a negative case the server accepts is not a test."""
    for case in build_cases(schema):
        if case.kind != "negative":
            continue
        body = _execute(schema, case.query)
        assert body.get("errors"), f"{case.name} was accepted: {body}"


def test_the_generated_cases_cover_the_documented_shapes(schema) -> None:
    names = {c.name for c in build_cases(schema)}
    assert "query:user" in names
    assert any("unknown-field" in n for n in names)
    assert "query:user:missing-id" in names, "a required argument was never omitted"
    assert "query:user:bad-id" in names, "no argument was given the wrong type"
    assert "query:search:bad-kind" in names, "enum arguments were not exercised"


def test_a_required_argument_case_omits_it_rather_than_renaming_it(schema) -> None:
    """Renaming would trip two violations at once -- an unknown argument as
    well as a missing one -- and a case name that no longer describes it."""
    case = next(c for c in build_cases(schema) if c.name == "query:user:missing-id")
    assert "id:" not in case.query
    assert "apiverityOmitted" not in case.query


def test_mutations_are_excluded_unless_asked_for(schema) -> None:
    """A generated mutation is a write against whatever --base-url names."""
    default = {c.name for c in build_cases(schema)}
    assert not [n for n in default if n.startswith("mutation:")]
    opted_in = {c.name for c in build_cases(schema, include_mutations=True)}
    assert [n for n in opted_in if n.startswith("mutation:")]


def test_selection_sets_terminate_on_a_cyclic_schema(schema) -> None:
    """`User.friends: [User]` is ordinary; a selection set cannot be cyclic."""
    case = next(c for c in build_cases(schema) if c.name == "query:user")
    assert case.query.count("friends") <= 3
    assert len(case.query) < 2000


def test_enum_arguments_are_rendered_unquoted(schema) -> None:
    """A quoted enum is a type error the server blames on the caller."""
    case = next(c for c in build_cases(schema) if c.name == "query:search:bad-kind")
    assert "kind: APIVERITY_NOT_A_MEMBER" in case.query
    assert 'kind: "' not in case.query


# ------------------------------------------------------------------- envelopes


def _case(kind: str = "positive", paths: list[str] | None = None):
    from apiverity.specs.graphql.operations import GraphQLCase

    return GraphQLCase(
        name="t", query="query { health }", kind=kind, expect_paths=paths or ["data.health"]
    )


def test_errors_on_a_200_are_a_failure_not_a_pass() -> None:
    """The reason GraphQL cannot go through the HTTP runner.

    A server answers a malformed query with 200 and an `errors` array; judging
    by status code alone marks every failure a pass.
    """
    problems = check_envelope(_case(), 200, {"data": None, "errors": [{"message": "boom"}]})
    assert problems
    assert any("returned errors" in p.message for p in problems)


def test_a_negative_case_that_is_accepted_is_a_failure() -> None:
    problems = check_envelope(_case("negative"), 200, {"data": {"health": "ok"}})
    assert any("was accepted" in p.message for p in problems)


def test_a_negative_case_that_is_rejected_passes() -> None:
    assert check_envelope(_case("negative"), 200, {"errors": [{"message": "nope"}]}) == []


def test_a_positive_case_missing_its_own_selection_is_reported() -> None:
    problems = check_envelope(_case(paths=["data.health"]), 200, {"data": {"other": 1}})
    assert any("missing 'data.health'" in p.message for p in problems)


def test_a_body_that_is_not_an_envelope_is_reported() -> None:
    assert check_envelope(_case(), 200, {"result": "ok"})
    assert check_envelope(_case(), 200, "not json at all")
    assert check_envelope(_case(), 200, None)


def test_a_5xx_is_reported_as_such() -> None:
    problems = check_envelope(_case(), 500, {"errors": [{"message": "x"}]})
    assert any("500" in p.message for p in problems)


def test_an_error_with_no_message_is_noted_but_not_fatal() -> None:
    """Every GraphQL error must carry a message, but a missing one should not
    turn an otherwise-correct rejection into a failure."""
    problems = check_envelope(_case("negative"), 200, {"errors": [{"path": ["x"]}]})
    assert problems
    assert not [p for p in problems if p.fatal]


# ------------------------------------------------------------------- persisted


def test_named_operations_become_cases() -> None:
    cases = load_persisted_operations(
        'query HealthCheck { health }\nquery Two { user(id: "1") { id } }', "ops.graphql"
    )
    assert [c.name for c in cases] == ["HealthCheck", "Two"]
    assert cases[0].expect_paths == ["data.health"]
    assert "ops.graphql" in cases[0].description


def test_anonymous_operations_are_skipped() -> None:
    """An anonymous operation cannot be named in a report or re-run from one."""
    assert load_persisted_operations("{ health }") == []


def test_fragments_are_not_mistaken_for_operations() -> None:
    cases = load_persisted_operations(
        'fragment F on User { id }\nquery Named { user(id: "1") { ...F } }'
    )
    assert [c.name for c in cases] == ["Named"]


def test_an_alias_becomes_the_expected_path() -> None:
    """The response key is the alias, not the field name."""
    cases = load_persisted_operations("query A { status: health }")
    assert cases[0].expect_paths == ["data.status"]


def test_a_malformed_document_raises_a_graphql_syntax_error() -> None:
    """Named, not blind: the CLI catches this to print which document failed,
    so it needs to be the parser's error and not something else."""
    from graphql import GraphQLSyntaxError

    with pytest.raises(GraphQLSyntaxError):
        load_persisted_operations("query { this is not graphql")


# --------------------------------------------------------------- introspection


def _introspection(schema) -> dict[str, Any]:
    result = graphql.graphql_sync(schema, INTROSPECTION_QUERY)
    assert not result.errors, result.errors
    return {"data": result.data}


def test_the_introspection_query_is_answerable(schema) -> None:
    """The full introspection query is enormous and many servers cap depth.

    Asking only for what the comparison uses is what makes it likely to be
    answered at all.
    """
    payload = _introspection(schema)
    assert payload["data"]["__schema"]["types"]


def test_a_matching_endpoint_reports_no_drift(schema) -> None:
    assert compare_introspection(schema, _introspection(schema)) == []


def test_an_undocumented_field_is_reported(schema) -> None:
    """The issue's acceptance criterion.

    A client can discover this through introspection and come to depend on
    something nobody agreed to support.
    """
    served = graphql.build_schema(
        SDL.replace("  health: String!", "  health: String!\n  internalDebug: String")
    )
    findings = compare_introspection(schema, _introspection(served))
    assert [f["rule_id"] for f in findings] == ["GQL-DRIFT-UNDECLARED-FIELD"]
    assert findings[0]["field"] == "internalDebug"
    assert findings[0]["severity"] == "WARN"


def test_a_field_the_endpoint_does_not_serve_is_an_error(schema) -> None:
    """The other direction. Any client generated from the schema will ask for
    it and fail, so it is more serious than an extra."""
    served = graphql.build_schema(SDL.replace("  age: Int\n", ""))
    findings = compare_introspection(schema, _introspection(served))
    missing = [f for f in findings if f["rule_id"] == "GQL-DRIFT-MISSING-FIELD"]
    assert missing and missing[0]["field"] == "age"
    assert missing[0]["severity"] == "ERROR"


def test_an_undeclared_type_is_reported(schema) -> None:
    served = graphql.build_schema(SDL + "\ntype Secret { token: String! }\n")
    findings = compare_introspection(schema, _introspection(served))
    assert any(
        f["rule_id"] == "GQL-DRIFT-UNDECLARED-TYPE" and f["type"] == "Secret" for f in findings
    )


def test_an_empty_introspection_payload_is_not_read_as_an_empty_server(schema) -> None:
    """`introspect` raises rather than returning nothing, precisely so this
    cannot happen -- but the comparison is defensive about it too, because
    reporting every declared type as missing would be a very loud lie."""
    findings = compare_introspection(schema, {"data": {"__schema": {"types": []}}})
    assert all(f["rule_id"] == "GQL-DRIFT-MISSING-TYPE" for f in findings)


def test_introspection_refusal_is_reported_as_a_refusal() -> None:
    """Many servers disable introspection in production."""
    import httpx

    from apiverity.specs.graphql import runner

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"errors": [{"message": "introspection is disabled"}]})

    transport = httpx.MockTransport(handler)
    real = httpx.Client

    class Patched(real):  # type: ignore[misc, valid-type]
        def __init__(self, **kwargs: object) -> None:
            kwargs["transport"] = transport
            super().__init__(**kwargs)  # type: ignore[arg-type]

    original = runner.httpx.Client
    runner.httpx.Client = Patched  # type: ignore[misc]
    try:
        with pytest.raises(ValueError, match="refused"):
            runner.introspect("http://t")
    finally:
        runner.httpx.Client = original  # type: ignore[misc]


# ------------------------------------------------------------------------ CLI


def test_the_test_command_routes_graphql_away_from_the_http_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Routing it through the HTTP runner would pass every failing case."""
    import argparse

    from apiverity.cli.commands import testing

    spec = tmp_path / "schema.graphql"
    spec.write_text(SDL, encoding="utf-8")
    called: list[str] = []
    monkeypatch.setattr(testing, "_test_graphql", lambda args: called.append(args.spec) or 0)
    args = argparse.Namespace(
        spec=str(spec),
        base_url="http://t",
        seed=0,
        timeout=1.0,
        minimize=False,
        json=False,
        generator=None,
        list_generators=False,
    )
    assert testing.cmd_test(args) == 0
    assert called == [str(spec)]


def test_a_missing_operations_document_is_a_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import argparse

    from apiverity.cli.commands.testing import cmd_test

    spec = tmp_path / "schema.graphql"
    spec.write_text(SDL, encoding="utf-8")
    args = argparse.Namespace(
        spec=str(spec),
        base_url="http://t",
        seed=0,
        timeout=1.0,
        minimize=False,
        json=False,
        generator=None,
        list_generators=False,
        operations=[str(tmp_path / "nope.graphql")],
        include_mutations=False,
    )
    assert cmd_test(args) == 2
    assert "no such operations document" in capsys.readouterr().err
