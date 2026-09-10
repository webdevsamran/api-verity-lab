"""JSON Schema 2020-12 keywords that were parsed away and dropped.

Seven keywords -- `prefixItems`, `contains`/`minContains`/`maxContains`,
`patternProperties`, `propertyNames`, `dependentRequired`, `dependentSchemas`
and `if`/`then`/`else` -- each state a rule the document makes, and each was
discarded at parse time. That produced the two worst outcomes a contract tool
has, together: the differ reported a tightened contract as unchanged, and
`validate_value` accepted data the document forbids.

So the tests below run the whole path -- parse, diff, classify, validate --
rather than asserting that a field got populated. A keyword that loads and
then changes nothing downstream is worse than one that never loaded, because
it looks covered.

Four defects found while writing these are pinned at the bottom. Three of them
made rules in the published catalogue unreachable.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from apiverity.core.model import (
    Operation,
    Protocol,
    RequestBody,
    Response,
    SchemaNode,
    Service,
)
from apiverity.core.validation import validate_value
from apiverity.diff.engine import diff_services
from apiverity.rules.breaking import evaluate_breaking
from apiverity.specs.loader import detect_and_load

_ROOT = Path(__file__).resolve().parents[2]
_FIXTURES = _ROOT / "fixtures" / "apis" / "jsonschema2020"


def _load(path: Path) -> Service:
    service, _findings, _ = detect_and_load(str(path))
    return service


def _request_schema(service: Service) -> SchemaNode:
    body = service.operations[0].request_body
    assert body is not None
    return next(iter(body.content.values()))


def _response_schema(service: Service) -> SchemaNode:
    response = next(r for r in service.operations[0].responses if r.status == "201")
    return next(iter(response.content.values()))


def _fixture_rules() -> dict[str, str]:
    """rule_id -> message, for the shipped v1 -> v2 fixture pair."""
    before = _load(_FIXTURES / "v1.yaml")
    after = _load(_FIXTURES / "v2.yaml")
    findings = evaluate_breaking(diff_services(before, after))
    return {f.rule_id: f.message for f in findings}


# ------------------------------------------------------------------- parsing


def test_every_newly_modelled_keyword_survives_the_parser() -> None:
    """The keywords reach the model, not just the document.

    Asserted together because the failure mode they share is silent: a keyword
    dropped at parse time leaves a schema that validates and diffs cleanly
    while asserting less than the document does.
    """
    service = _load(_FIXTURES / "v1.yaml")
    request = _request_schema(service)
    response = _response_schema(service)

    assert request.dependent_required == {"card": ["cvv"]}
    assert set(request.pattern_properties) == {"^x-"}
    assert request.if_schema is not None
    assert request.then_schema is not None
    assert request.if_schema.properties["mode"].const == "road"

    route = response.properties["route"]
    assert route.prefix_items is not None
    assert [item.type for item in route.prefix_items] == ["string", "string"]
    assert response.properties["legs"].contains is not None
    assert response.properties["legs"].min_contains == 1
    assert response.properties["labels"].property_names is not None


def test_the_parser_no_longer_calls_these_keywords_unmodelled() -> None:
    """The MCP loader's honesty list must shrink as the model grows.

    It reports which keywords are dropped so a user is not left to discover it.
    Leaving a modelled keyword on that list would be the same defect in the
    other direction: a warning about a limitation that no longer exists.
    """
    from apiverity.specs.mcp.manifest import _UNMODELLED_KEYWORDS

    for keyword in (
        "prefixItems",
        "contains",
        "patternProperties",
        "propertyNames",
        "dependentRequired",
        "dependentSchemas",
        "if",
        "then",
        "else",
    ):
        assert keyword not in _UNMODELLED_KEYWORDS

    # And what remains is named, not merely absent.
    assert set(_UNMODELLED_KEYWORDS) == {
        "unevaluatedProperties",
        "unevaluatedItems",
        "$dynamicRef",
        "$dynamicAnchor",
    }


# ---------------------------------------------------------------- diff rules


def test_the_fixture_pair_produces_one_finding_per_keyword_changed() -> None:
    """Six edits, six findings, each naming what moved.

    This is the test that would have failed before the keywords were modelled:
    every one of these edits tightens the contract, and the differ reported the
    pair as differing only in version.
    """
    rules = _fixture_rules()
    assert "BRK-DEPENDENT-REQUIRED-ADDED" in rules
    assert "BRK-TUPLE-SHAPE-CHANGED" in rules
    assert "BRK-CONTAINS-CHANGED" in rules
    assert "BRK-RESP-CONSTRAINT-TIGHTENED" in rules  # propertyNames pattern
    assert "BRK-CONSTRAINT-TIGHTENED" in rules  # patternProperties maxLength


def test_a_new_dependent_requirement_is_an_error_on_a_request() -> None:
    rules = _fixture_rules()
    message = rules["BRK-DEPENDENT-REQUIRED-ADDED"]
    assert "card" in message
    assert "billingPostcode" in message


def test_a_tuple_gaining_a_position_is_an_error() -> None:
    rules = _fixture_rules()
    assert "2 positional item(s) to 3" in rules["BRK-TUPLE-SHAPE-CHANGED"]


def test_a_dependent_requirement_dropped_from_a_response_is_not_silent() -> None:
    """Direction inverts here as it does everywhere else in the rules.

    Dropping a dependency from a *request* accepts more. Dropping it from a
    *response* withdraws a guarantee the consumer was given, so the two must
    not share a rule id.
    """
    old = SchemaNode(type="object", dependent_required={"card": ["cvv"]})
    new = SchemaNode(type="object")
    request = _rules_for_body(old, new, direction="request")
    response = _rules_for_body(old, new, direction="response")
    assert request == {"BRK-DEPENDENT-REQUIRED-REMOVED"}
    assert response == {"BRK-DEPENDENT-REQUIRED-ADDED"}


def _rules_for_body(old: SchemaNode, new: SchemaNode, *, direction: str) -> set[str]:
    """Diff one schema in one direction and return the rule ids."""

    def service(schema: SchemaNode) -> Service:
        operation = Operation(operation_id="op", method="POST", path="/thing")
        if direction == "request":
            operation.request_body = RequestBody(
                required=True, content={"application/json": schema}
            )
        else:
            operation.responses = [Response(status="200", content={"application/json": schema})]
        return Service(
            title="fixture",
            version="1.0.0",
            protocol=Protocol.OPENAPI,
            operations=[operation],
        )

    findings = evaluate_breaking(diff_services(service(old), service(new)))
    return {f.rule_id for f in findings}


# ---------------------------------------------------------------- validation


def test_prefix_items_are_validated_positionally() -> None:
    schema = SchemaNode(
        type="array",
        prefix_items=[SchemaNode(type="string"), SchemaNode(type="integer")],
    )
    assert validate_value(schema, ["LHR", 3]) == []
    assert validate_value(schema, ["LHR", "three"]) != []


def test_contains_bounds_are_enforced() -> None:
    schema = SchemaNode(
        type="array",
        contains=SchemaNode(type="integer"),
        min_contains=2,
    )
    assert validate_value(schema, [1, 2, "x"]) == []
    assert validate_value(schema, [1, "x"]) != []


def test_dependent_required_is_enforced() -> None:
    schema = SchemaNode(
        type="object",
        properties={"card": SchemaNode(type="string"), "cvv": SchemaNode(type="string")},
        dependent_required={"card": ["cvv"]},
    )
    assert validate_value(schema, {"card": "4111", "cvv": "123"}) == []
    assert validate_value(schema, {"card": "4111"}) != []
    assert validate_value(schema, {"cvv": "123"}) == []  # trigger absent


def test_dependent_schemas_apply_only_when_the_trigger_is_present() -> None:
    schema = SchemaNode(
        type="object",
        properties={"card": SchemaNode(type="string")},
        dependent_schemas={
            "card": SchemaNode(type="object", required=["billingPostcode"]),
        },
    )
    assert validate_value(schema, {}) == []
    assert validate_value(schema, {"card": "4111"}) != []
    assert validate_value(schema, {"card": "4111", "billingPostcode": "SW1"}) == []


def test_property_names_constrain_keys_not_values() -> None:
    schema = SchemaNode(
        type="object",
        property_names=SchemaNode(type="string", pattern="^[a-z]+$"),
    )
    assert validate_value(schema, {"region": "eu"}) == []
    assert validate_value(schema, {"Region": "eu"}) != []


def test_pattern_properties_constrain_matching_fields() -> None:
    schema = SchemaNode(
        type="object",
        pattern_properties={"^x-": SchemaNode(type="string")},
    )
    assert validate_value(schema, {"x-tenant": "acme"}) == []
    assert validate_value(schema, {"x-tenant": 7}) != []


def test_a_pattern_matched_property_counts_as_declared() -> None:
    """`forbid_undeclared_fields` must not reject what a pattern declares.

    Before `patternProperties` was modelled, a document declaring `^x-` still
    rejected `x-tenant` under strict validation, because the only declaration
    the model carried was `properties`.
    """
    schema = SchemaNode(
        type="object",
        properties={"id": SchemaNode(type="string")},
        pattern_properties={"^x-": SchemaNode(type="string")},
    )
    errors = validate_value(
        schema,
        {"id": "s1", "x-tenant": "acme"},
        forbid_undeclared_fields=True,
    )
    assert errors == []
    assert (
        validate_value(
            schema,
            {"id": "s1", "surprise": "acme"},
            forbid_undeclared_fields=True,
        )
        != []
    )


def test_if_then_else_selects_a_branch() -> None:
    schema = SchemaNode(
        type="object",
        properties={"mode": SchemaNode(type="string"), "weightKg": SchemaNode(type="number")},
        if_schema=SchemaNode(
            type="object",
            required=["mode"],
            properties={"mode": SchemaNode(type="string", const="road")},
        ),
        then_schema=SchemaNode(type="object", required=["weightKg"]),
        else_schema=SchemaNode(type="object", required=["mode"]),
    )
    assert validate_value(schema, {"mode": "road", "weightKg": 12}) == []
    assert validate_value(schema, {"mode": "road"}) != []
    assert validate_value(schema, {"mode": "sea"}) == []


# -------------------------------------------------- defects found in passing


def test_a_constraint_appearing_where_there_was_none_is_a_finding() -> None:
    """`None -> 64` used to produce a change and no finding.

    `_constraint_change_is_tightening` compared two numbers and returned
    "not comparable" whenever either side was absent -- so adding `maxLength`
    to a request field that had no limit, which rejects input that was valid
    the day before, was reported as a change nobody was told about.
    """
    old = SchemaNode(type="object", properties={"note": SchemaNode(type="string")})
    new = SchemaNode(
        type="object",
        properties={"note": SchemaNode(type="string", max_length=64)},
    )
    assert _rules_for_body(old, new, direction="request") == {"BRK-CONSTRAINT-TIGHTENED"}


def test_a_constraint_disappearing_is_a_finding() -> None:
    old = SchemaNode(
        type="object",
        properties={"note": SchemaNode(type="string", max_length=64)},
    )
    new = SchemaNode(type="object", properties={"note": SchemaNode(type="string")})
    assert _rules_for_body(old, new, direction="request") == {"BRK-CONSTRAINT-LOOSENED"}


def test_brk_constraint_loosened_is_reachable() -> None:
    """It was in the catalogue and no input could produce it.

    The classifier only ever returned "tightened" or "not comparable", so this
    rule id was published, documented and dead -- the same defect as
    `SEC-UNAUTH-WRITE`. A genuine loosening must now reach it.
    """
    old = SchemaNode(type="object", properties={"n": SchemaNode(type="integer", minimum=10)})
    new = SchemaNode(type="object", properties={"n": SchemaNode(type="integer", minimum=1)})
    assert _rules_for_body(old, new, direction="request") == {"BRK-CONSTRAINT-LOOSENED"}


def test_requiring_uniqueness_is_a_tightening() -> None:
    """`unique_items` is a bool listed among numeric bounds.

    It was compared for inequality and then handed to a function that only
    understood numbers, so turning it on -- which rejects arrays that were
    accepted -- produced nothing.
    """
    old = SchemaNode(type="object", properties={"tags": SchemaNode(type="array")})
    new = SchemaNode(
        type="object",
        properties={"tags": SchemaNode(type="array", unique_items=True)},
    )
    assert _rules_for_body(old, new, direction="request") == {"BRK-CONSTRAINT-TIGHTENED"}


def test_a_const_change_is_visible_to_the_differ() -> None:
    """`const` was parsed, validated, and compared nowhere.

    A `const` change invalidates every value carrying the old one, and it was
    invisible in every protocol -- OpenAPI, AsyncAPI, GraphQL, gRPC, Swagger
    and MCP alike -- because the differ's constraint list never named it.
    """
    old = SchemaNode(type="object", properties={"kind": SchemaNode(type="string", const="road")})
    new = SchemaNode(type="object", properties={"kind": SchemaNode(type="string", const="sea")})
    assert _rules_for_body(old, new, direction="request") == {"BRK-CONSTRAINT-TIGHTENED"}


def test_a_const_appearing_narrows_and_a_const_leaving_widens() -> None:
    unconstrained = SchemaNode(type="object", properties={"k": SchemaNode(type="string")})
    pinned = SchemaNode(
        type="object",
        properties={"k": SchemaNode(type="string", const="road")},
    )
    assert _rules_for_body(unconstrained, pinned, direction="request") == {
        "BRK-CONSTRAINT-TIGHTENED"
    }
    assert _rules_for_body(pinned, unconstrained, direction="request") == {
        "BRK-CONSTRAINT-LOOSENED"
    }


def test_the_const_inside_a_conditional_branch_is_compared_too() -> None:
    """The fixture's `if: {mode: {const: road -> sea}}` must not be silent.

    Moving the condition changes which requests the `then` branch applies to,
    which is a different contract even though nothing else in the document
    moved.
    """
    rules = _fixture_rules()
    assert any("constraint 'const' changed" in message for message in rules.values())


# ------------------------------------------------------------ round-tripping


def test_a_2020_12_document_still_validates_its_own_examples(tmp_path: Path) -> None:
    """Loading must not invent constraints the document does not state.

    The risk with a parser that gained twelve fields in one pass is the
    opposite of dropping them: a default that reads as a declaration. An empty
    `patternProperties` must not become a rule.
    """
    doc = yaml.safe_load((_FIXTURES / "v1.yaml").read_text(encoding="utf-8"))
    path = tmp_path / "spec.yaml"
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    service = _load(path)

    plain = SchemaNode(type="object", properties={"id": SchemaNode(type="string")})
    assert plain.pattern_properties == {}
    assert plain.dependent_required == {}
    assert plain.prefix_items is None
    assert validate_value(plain, {"id": "s1"}) == []

    request = _request_schema(service)
    assert validate_value(request, {"reference": "R1"}) == []
