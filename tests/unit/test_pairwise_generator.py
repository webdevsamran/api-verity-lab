"""Boundary values, and every pair of parameters at least once.

`docs/capability-status.md` published "boundary values, pairwise -- EXISTING"
about `apiverity/fuzz/boundary.py`, which no command reached. Two things follow
from that, and both are here.

`apiverity test --generator pairwise` reaches it now. And `boundary_values`
returned values that **violate** the schema it was given -- which did not
matter while the only caller treated every value the same, and matters the
moment a generator has to say whether a case is positive or negative.
"""

from __future__ import annotations

import itertools
from typing import Any

import pytest

from apiverity.core.model import Operation, Parameter, ParameterLocation, SchemaNode
from apiverity.fuzz.boundary import (
    boundary_values,
    near_boundary_invalid_cases,
    pairwise_parameter_cases,
)
from apiverity.fuzz.generators import BUILTIN_GENERATORS, PairwiseGenerator


def _query(name: str, schema: SchemaNode) -> Parameter:
    return Parameter(name=name, location=ParameterLocation.QUERY, schema_node=schema)


def _op(*params: Parameter) -> Operation:
    return Operation(method="GET", path="/x", parameters=list(params))


# ---------------------------------------------- what a boundary value is now


@pytest.mark.parametrize(
    ("schema", "expected"),
    [
        (SchemaNode(type="integer", minimum=1, maximum=100), [1, 100]),
        (SchemaNode(type="integer", exclusive_minimum=5, exclusive_maximum=10), [6, 9]),
        (SchemaNode(type="string", min_length=2, max_length=4), ["aa", "aaaa"]),
        (SchemaNode(type="array", min_items=1, max_items=3), [[None], [None, None, None]]),
        (SchemaNode(type="boolean"), [True, False]),
    ],
)
def test_every_boundary_value_satisfies_its_schema(schema: SchemaNode, expected: Any) -> None:
    assert boundary_values(schema) == expected


def test_the_exclusive_bound_itself_is_not_a_permitted_value() -> None:
    """`exclusiveMinimum: 5` singles 5 out as forbidden, and it was returned as
    a boundary *value* -- so a positive case would have sent the one number the
    contract says must be rejected, and reported the rejection as a defect."""
    schema = SchemaNode(type="integer", exclusive_minimum=5)
    assert 5 not in boundary_values(schema)
    assert 5 in near_boundary_invalid_cases(schema)


def test_a_length_one_step_outside_the_range_is_not_a_permitted_value() -> None:
    """Both were in `boundary_values`, marked `# invalid near-boundary` in the
    source, and both were already in `near_boundary_invalid_cases`."""
    schema = SchemaNode(type="string", min_length=2, max_length=4)
    assert "a" not in boundary_values(schema)
    assert "aaaaa" not in boundary_values(schema)
    assert set(near_boundary_invalid_cases(schema)) == {"a", "aaaaa"}


def test_a_pattern_yields_nothing_rather_than_a_guess() -> None:
    """It returned `"A1-"` for every pattern. A string matching an arbitrary
    regex cannot be derived here, and a guess is this module asserting that its
    own guess is valid."""
    assert boundary_values(SchemaNode(type="string", pattern="^[0-9]{4}$")) == []


def test_multiple_of_steps_from_the_lower_bound_and_stays_in_range() -> None:
    schema = SchemaNode(type="integer", minimum=0, maximum=10, multiple_of=5)
    assert boundary_values(schema) == [0, 10, 5]
    assert boundary_values(SchemaNode(type="integer", minimum=0, maximum=3, multiple_of=5)) == [
        0,
        3,
    ]


def test_an_invalid_value_is_one_step_out_in_the_multiple_of_unit() -> None:
    schema = SchemaNode(type="integer", minimum=10, maximum=20, multiple_of=5)
    assert near_boundary_invalid_cases(schema) == [5, 25]


def test_an_array_longer_than_max_items_is_now_reported_as_invalid() -> None:
    assert [None, None] in near_boundary_invalid_cases(SchemaNode(type="array", max_items=1))


# --------------------------------------------------------- the pairwise claim


def _pairs(names: list[str], choices: dict[str, list[Any]]) -> set[tuple[Any, ...]]:
    return {
        (x, y, vx, vy)
        for x, y in itertools.combinations(names, 2)
        for vx in choices[x]
        for vy in choices[y]
    }


def test_every_pair_of_values_appears_in_some_case() -> None:
    """The docstring's claim, measured rather than asserted in prose."""
    params = [
        _query(n, SchemaNode(type="string", enum=[f"{n}{i}" for i in range(3)])) for n in "abcd"
    ]
    cases = pairwise_parameter_cases(_op(*params))
    names = [p.name for p in params]
    choices = {p.name: list(p.schema_node.enum or []) for p in params}

    covered = {
        (x, y, case[x], case[y])
        for case in cases
        for x, y in itertools.combinations(names, 2)
        if x in case and y in case
    }
    assert _pairs(names, choices) <= covered


def test_it_is_smaller_than_the_cartesian_product() -> None:
    """The whole reason to do this rather than the obvious thing. Not optimal
    -- an optimal covering array for this shape is about 36 -- and stated as a
    measurement rather than a claim about the algorithm."""
    params = [
        _query(n, SchemaNode(type="string", enum=[f"{n}{i}" for i in range(6)])) for n in "abcde"
    ]
    cases = pairwise_parameter_cases(_op(*params))
    assert len(cases) < 6**5 // 4


def test_it_is_deterministic_for_a_seed() -> None:
    params = [_query(n, SchemaNode(type="string", enum=["p", "q"])) for n in "ab"]
    assert pairwise_parameter_cases(_op(*params), seed=3) == pairwise_parameter_cases(
        _op(*params), seed=3
    )


def test_one_parameter_produces_its_values_and_nothing_combinatorial() -> None:
    cases = pairwise_parameter_cases(_op(_query("a", SchemaNode(type="string", enum=["x", "y"]))))
    assert cases == [{"a": "x"}, {"a": "y"}]


# ------------------------------------------------------------ the generator


def test_the_generator_is_registered_and_named() -> None:
    assert BUILTIN_GENERATORS["pairwise"].name == "pairwise"


def test_it_produces_positive_cases_only() -> None:
    """Every value a permitted one, so a combination is a request the contract
    says must be accepted. A 4xx here is the finding."""
    params = [
        _query("page", SchemaNode(type="integer", minimum=1, maximum=9)),
        _query("size", SchemaNode(type="integer", minimum=1, maximum=50)),
    ]
    cases = list(PairwiseGenerator().generate(_op(*params), seed=0))
    assert cases
    assert {c["kind"] for c in cases} == {"positive"}


def test_a_header_parameter_goes_in_the_headers_not_the_query() -> None:
    operation = Operation(
        method="GET",
        path="/x",
        parameters=[
            _query("page", SchemaNode(type="integer", minimum=1, maximum=3)),
            Parameter(
                name="X-Region",
                location=ParameterLocation.HEADER,
                schema_node=SchemaNode(type="string", enum=["eu", "us"]),
            ),
        ],
    )
    cases = list(PairwiseGenerator().generate(operation, seed=0))
    assert cases
    assert all("X-Region" in c["headers"] for c in cases)
    assert all("X-Region" not in c["query"] for c in cases)


def test_a_single_parameter_operation_produces_nothing() -> None:
    """Every other generator already covers one field better than this one."""
    assert list(PairwiseGenerator().generate(_op(_query("a", SchemaNode(type="boolean"))), 0)) == []


def test_a_wide_operation_is_capped_and_says_so() -> None:
    """A generator that quietly produced four hundred cases for one endpoint
    would be switched off, taking the useful ones with it -- and a run that
    covered two thirds of the pairs while reporting nothing about it reads as
    a run that covered them all."""
    params = [
        _query(n, SchemaNode(type="string", enum=[f"{n}{i}" for i in range(6)])) for n in "abcde"
    ]
    cases = list(PairwiseGenerator().generate(_op(*params), seed=0))
    assert len(cases) == PairwiseGenerator.MAX_CASES
    assert "capped at 60 of" in cases[-1]["description"]


def test_the_description_names_the_combination() -> None:
    """ "case 37" tells a reader nothing when it fails."""
    params = [_query(n, SchemaNode(type="string", enum=["p", "q"])) for n in "ab"]
    cases = list(PairwiseGenerator().generate(_op(*params), seed=0))
    assert all(c["description"].startswith("parameter combination a=") for c in cases)


def test_the_generator_is_listed_by_the_command() -> None:
    import contextlib
    import io

    from apiverity.cli.main import main

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = main(["--no-config", "test", "--list-generators"])
    assert code == 0
    assert "pairwise" in buffer.getvalue()


def test_listing_generators_needs_no_contract() -> None:
    """The flag is documented as "list ... and exit" and argparse required a
    contract to reach it."""
    import contextlib
    import io

    from apiverity.cli.main import main

    with contextlib.redirect_stdout(io.StringIO()):
        assert main(["--no-config", "test", "--list-generators"]) == 0


def test_a_run_without_a_contract_says_which_argument_is_missing() -> None:
    import contextlib
    import io

    from apiverity.cli.main import main

    err = io.StringIO()
    with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
        code = main(["--no-config", "test", "--base-url", "http://127.0.0.1:1"])
    assert code != 0
    assert "a contract is required" in err.getvalue()
