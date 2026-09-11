"""The pack's own tests, which is what a published pack should have.

Every rule is checked in both directions. A rule only ever asserted to fire is
a rule that might fire on everything, and a pack of those is a pack somebody
disables.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from house_rules import PACK, error_shape, list_pagination, pack, path_case

from apiverity.core.model import (
    Operation,
    Parameter,
    Protocol,
    Response,
    Service,
)


def _service(*operations: Operation) -> Service:
    return Service(
        title="t", version="1.0.0", protocol=Protocol.OPENAPI, operations=list(operations)
    )


def _op(method: str, path: str, **kwargs) -> Operation:
    return Operation(operation_id=f"{method} {path}", method=method, path=path, **kwargs)


def test_the_entry_point_returns_the_pack() -> None:
    assert pack() is PACK
    assert PACK.rule_ids() == [
        "HOUSE-PATH-CASE",
        "HOUSE-LIST-PAGINATION",
        "HOUSE-ERROR-SHAPE",
    ]


def test_kebab_case_paths_pass_and_camel_case_ones_do_not() -> None:
    assert not path_case(_service(_op("GET", "/user-profiles/{userId}")))
    findings = path_case(_service(_op("GET", "/userProfiles")))
    assert [f.rule_id for f in findings] == ["HOUSE-PATH-CASE"]


def test_a_path_parameter_is_not_a_path_segment() -> None:
    """`{userId}` is a variable name. A rule that objected to its casing would
    be having a different argument than the one it is named for."""
    assert not path_case(_service(_op("GET", "/orders/{orderId}")))


def test_a_collection_get_needs_paging_and_an_item_get_does_not() -> None:
    assert list_pagination(_service(_op("GET", "/orders")))
    assert not list_pagination(_service(_op("GET", "/orders/{id}")))
    paged = _op("GET", "/orders", parameters=[Parameter(name="limit", location="query")])
    assert not list_pagination(_service(paged))


def test_a_write_is_not_a_collection_read() -> None:
    assert not list_pagination(_service(_op("POST", "/orders")))


def test_an_operation_with_no_4xx_is_reported() -> None:
    happy = _op("GET", "/orders", responses=[Response(status="200", description="ok")])
    assert error_shape(_service(happy))

    complete = _op(
        "GET",
        "/orders",
        responses=[
            Response(status="200", description="ok"),
            Response(status="404", description="no"),
        ],
    )
    assert not error_shape(_service(complete))


def test_responses_are_a_list_not_a_mapping() -> None:
    """The first version of `error_shape` iterated `responses` as a dict keyed
    by status code. It is a list of `Response`, so every operation came back
    reported -- a rule that fires on everything is a rule nobody keeps."""
    operation = _op("GET", "/orders", responses=[Response(status="404", description="no")])
    assert not error_shape(_service(operation))
