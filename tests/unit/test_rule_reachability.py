"""Every rule in the published catalogue must be producible by some input.

A rule id that no code path emits is worse than a missing rule. It appears in
`docs/rule-catalog.md`, in `apiverity rules`, in `apiverity explain`, and in the
alternatives table -- so a team writes a `--severity-override` for it, a
reviewer waits for it to fire, and it never does. The engine reports a clean
contract and the catalogue says the check exists.

This has happened three times in this repository already: `SEC-UNAUTH-WRITE`
and `SEC-AUTH-MISSING` were unreachable because the security check returned
early; `BRK-CONSTRAINT-LOOSENED` was unreachable because the classifier never
returned "loosened"; and `BRK-REQ-FIELD-REMOVED`,
`BRK-REQ-FIELD-ADDED-REQUIRED` and `BRK-REQ-FIELD-ADDED-OPTIONAL` were
unreachable because every request body property was reported as a *parameter*.

Each was found by running the code rather than reading it. This test is the
cheap version of that: it is a static check, so it cannot prove a rule fires,
only that some code path names it -- but it catches the exact failure all three
shared, which is a rule that is documented and referenced nowhere else.
"""

from __future__ import annotations

from pathlib import Path

from apiverity.core.model import (
    Operation,
    Parameter,
    ParameterLocation,
    Protocol,
    RequestBody,
    SchemaNode,
    Service,
)
from apiverity.diff.engine import diff_services
from apiverity.rules.breaking import CATALOG, evaluate_breaking

_PACKAGE = Path(__file__).resolve().parents[2] / "apiverity"

#: A rule mentioned *only* in these files is documented, not produced. The
#: catalogue declares it, the alternatives table says what to do about it, and
#: the summary table phrases it -- none of which makes anything emit it.
_DOCUMENTING_ONLY = {"alternatives.py", "summary.py"}


def _catalog_literal() -> str:
    """The `CATALOG = {...}` block, which declares rules rather than emits them."""
    source = (_PACKAGE / "rules" / "breaking.py").read_text(encoding="utf-8")
    start = source.index("CATALOG: dict[str, RuleSpec] = {")
    end = source.index("\ndef ", start)
    return source[start:end]


def _emitting_sources() -> dict[Path, str]:
    catalog = _catalog_literal()
    breaking = _PACKAGE / "rules" / "breaking.py"
    sources: dict[Path, str] = {}
    for path in _PACKAGE.rglob("*.py"):
        if path.name in _DOCUMENTING_ONLY:
            continue
        text = path.read_text(encoding="utf-8")
        sources[path] = text.replace(catalog, "") if path == breaking else text
    return sources


def test_no_rule_is_declared_and_then_emitted_by_nothing() -> None:
    sources = _emitting_sources()
    orphaned = [
        rule
        for rule in CATALOG
        if not any(f'"{rule}"' in text or f"'{rule}'" in text for text in sources.values())
    ]
    assert orphaned == [], (
        "these rules are in the published catalogue and no code path emits them: "
        f"{orphaned}. A rule nobody can produce still gets configured, waited for, "
        "and trusted."
    )


# --------------------------------- the three that were unreachable, run live


def _service(*, body: SchemaNode | None = None, params: list[Parameter] | None = None) -> Service:
    operation = Operation(operation_id="op", method="POST", path="/thing")
    if body is not None:
        operation.request_body = RequestBody(required=True, content={"application/json": body})
    if params:
        operation.parameters = params
    return Service(
        title="fixture",
        version="1.0.0",
        protocol=Protocol.OPENAPI,
        operations=[operation],
    )


def _rules(old: Service, new: Service) -> set[str]:
    return {f.rule_id for f in evaluate_breaking(diff_services(old, new))}


def test_a_removed_request_body_field_is_a_field_not_a_parameter() -> None:
    """`BRK-PARAM-REMOVED` sends a reviewer to look at the query string."""
    before = _service(
        body=SchemaNode(
            type="object",
            required=["a", "b"],
            properties={"a": SchemaNode(type="string"), "b": SchemaNode(type="string")},
        )
    )
    after = _service(
        body=SchemaNode(type="object", required=["a"], properties={"a": SchemaNode(type="string")})
    )
    fired = _rules(before, after)
    assert "BRK-REQ-FIELD-REMOVED" in fired
    assert "BRK-PARAM-REMOVED" not in fired


def test_a_new_required_request_body_field_is_a_field() -> None:
    before = _service(
        body=SchemaNode(type="object", required=["a"], properties={"a": SchemaNode(type="string")})
    )
    after = _service(
        body=SchemaNode(
            type="object",
            required=["a", "b"],
            properties={"a": SchemaNode(type="string"), "b": SchemaNode(type="string")},
        )
    )
    fired = _rules(before, after)
    assert "BRK-REQ-FIELD-ADDED-REQUIRED" in fired
    assert "BRK-PARAM-ADDED-REQUIRED" not in fired


def test_a_new_optional_request_body_field_is_a_field() -> None:
    before = _service(body=SchemaNode(type="object", properties={"a": SchemaNode(type="string")}))
    after = _service(
        body=SchemaNode(
            type="object",
            properties={"a": SchemaNode(type="string"), "b": SchemaNode(type="string")},
        )
    )
    assert "BRK-REQ-FIELD-ADDED-OPTIONAL" in _rules(before, after)


def test_a_real_parameter_is_still_reported_as_a_parameter() -> None:
    """The fix must not swap the confusion round.

    A removed query parameter is a parameter, and reporting it as a body field
    would send the same reviewer to the same wrong place in the other
    direction.
    """
    param = Parameter(
        name="limit",
        location=ParameterLocation.QUERY,
        required=False,
        schema=SchemaNode(type="integer"),
    )
    fired = _rules(_service(params=[param]), _service(params=[]))
    assert "BRK-PARAM-REMOVED" in fired
    assert "BRK-REQ-FIELD-REMOVED" not in fired
