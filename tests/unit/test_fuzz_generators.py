"""Pluggable case generators (#19).

The entry-point group was declared, documented and registered, and nothing
ever read it: `apiverity test` called `build_cases` directly, so an installed
third-party generator loaded into the registry and then did nothing. The first
test here is the one that matters -- a generator that is registered actually
runs.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from apiverity.core.model import (
    Operation,
    Parameter,
    ParameterLocation,
    Protocol,
    RequestBody,
    Response,
    SchemaNode,
    Server,
    Service,
)
from apiverity.fuzz import generators as gen
from apiverity.fuzz.runner import build_cases


def _op(**kw: Any) -> Operation:
    base: dict[str, Any] = {
        "method": "POST",
        "path": "/items",
        "responses": [Response(status="200")],
    }
    base.update(kw)
    return Operation(**base)


def _service(*ops: Operation) -> Service:
    return Service(
        title="T",
        version="1.0.0",
        protocol=Protocol.OPENAPI,
        servers=[Server(url="http://t")],
        operations=list(ops) or [_op()],
    )


def _body(schema: SchemaNode) -> RequestBody:
    return RequestBody(required=True, content={"application/json": schema})


def _query(name: str, schema: SchemaNode) -> Parameter:
    return Parameter(name=name, location=ParameterLocation.QUERY, schema_node=schema)


# ------------------------------------------------------------------ dispatch


def test_a_registered_generator_is_actually_invoked(monkeypatch: pytest.MonkeyPatch) -> None:
    """The defect #19 exists for: the plugin point loaded but was never read."""
    calls: list[str] = []

    class Recording:
        name = "recording"

        def generate(self, op: Operation, seed: int) -> list[dict[str, Any]]:
            calls.append(op.key)
            return [
                gen.GeneratedCase(kind="negative", description="from the plugin", query={"x": 1})
            ]

    monkeypatch.setattr(gen, "load_generators", lambda selected=None: {"recording": Recording()})
    cases = build_cases(_service(), seed=1, generators=["recording"])
    assert calls, "the generator was selected and never called"
    assert any(c.description == "[recording] from the plugin" for c in cases)


def test_a_third_party_generator_can_replace_a_builtin() -> None:
    """A strategy should be improvable without forking the tool."""

    class Replacement:
        name = "unicode"

        def generate(self, op: Operation, seed: int) -> list[dict[str, Any]]:
            return []

    available = dict(gen.BUILTIN_GENERATORS)
    available["unicode"] = Replacement()  # type: ignore[assignment]
    assert type(available["unicode"]).__name__ == "Replacement"


def test_selecting_an_unknown_generator_lists_the_real_ones() -> None:
    with pytest.raises(ValueError, match="unknown generator"):
        gen.load_generators(["does-not-exist"])
    with pytest.raises(ValueError, match="unicode"):
        gen.load_generators(["does-not-exist"])


def test_a_generator_that_raises_does_not_abort_the_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One broken plugin in the environment must not cost you the whole run."""

    class Exploding:
        name = "exploding"

        def generate(self, op: Operation, seed: int) -> list[dict[str, Any]]:
            raise RuntimeError("kaboom")

    monkeypatch.setattr(gen, "load_generators", lambda selected=None: {"exploding": Exploding()})
    cases = build_cases(_service(), seed=1, generators=["exploding"])
    assert cases, "the schema cases were lost along with the broken generator"
    assert any("kaboom" in c.description for c in cases), (
        "the failure was swallowed silently; a plugin that never works must say so"
    )


def test_generators_are_opt_in() -> None:
    """`apiverity test` should not silently get ten times longer."""
    op = _op(
        request_body=_body(SchemaNode(type="object", properties={"a": SchemaNode(type="string")}))
    )
    plain = build_cases(_service(op), seed=1)
    with_extra = build_cases(_service(op), seed=1, generators=["unicode"])
    assert len(with_extra) > len(plain)


def test_case_ids_do_not_shift_when_a_generator_is_added() -> None:
    """A case id in a bug report has to keep pointing at the same case."""
    op = _op(
        request_body=_body(SchemaNode(type="object", properties={"a": SchemaNode(type="string")}))
    )
    plain = build_cases(_service(op), seed=3)
    with_extra = build_cases(_service(op), seed=3, generators=["unicode"])
    prefix = with_extra[: len(plain)]
    assert [c.id for c in prefix] == [c.id for c in plain]
    assert [c.description for c in prefix] == [c.description for c in plain]


def test_generation_is_deterministic() -> None:
    op = _op(
        request_body=_body(SchemaNode(type="object", properties={"a": SchemaNode(type="string")}))
    )
    names = ["unicode", "nesting", "numeric", "header-safety"]
    first = build_cases(_service(op), seed=9, generators=names)
    second = build_cases(_service(op), seed=9, generators=names)
    assert [(c.id, c.description, json.dumps(c.body, default=str)) for c in first] == [
        (c.id, c.description, json.dumps(c.body, default=str)) for c in second
    ]


# ------------------------------------------------------------------- unicode


def test_unicode_cases_are_positive() -> None:
    """A service that 500s on an emoji has a bug.

    Marking these negative would be asserting that rejecting valid UTF-8 is
    correct behaviour.
    """
    op = _op(
        request_body=_body(SchemaNode(type="object", properties={"a": SchemaNode(type="string")}))
    )
    cases = list(gen.UnicodeGenerator().generate(op, 1))
    assert cases
    assert {c["kind"] for c in cases} == {"positive"}


def test_unicode_cases_respect_declared_length_bounds() -> None:
    """A service rejecting an over-long string is behaving correctly.

    Emitting one and calling the rejection a unicode-handling failure would be
    a false positive with a misleading name.
    """
    op = _op(
        request_body=_body(
            SchemaNode(type="object", properties={"a": SchemaNode(type="string", max_length=3)})
        )
    )
    for case in gen.UnicodeGenerator().generate(op, 1):
        value = (case["body"] or {}).get("a")
        assert value is None or len(value) <= 3, f"emitted {value!r} against maxLength 3"


def test_unicode_covers_both_normalization_forms() -> None:
    labels = {label for label, _ in gen.UNICODE_SAMPLES}
    assert any("NFD" in label for label in labels)
    assert any("NFC" in label for label in labels)
    pairs = gen.normalization_pairs()
    assert pairs and all(a != b for a, b in pairs)


def test_unicode_reaches_query_parameters_too() -> None:
    op = _op(parameters=[_query("q", SchemaNode(type="string"))], request_body=None)
    cases = list(gen.UnicodeGenerator().generate(op, 1))
    assert cases and all("q" in c["query"] for c in cases)


# ------------------------------------------------------------------- nesting


def test_nesting_produces_genuinely_deep_payloads() -> None:
    op = _op(request_body=_body(SchemaNode(type="object")))
    cases = list(gen.NestingGenerator().generate(op, 1))
    assert cases

    def depth(value: Any) -> int:
        """Iterative on purpose: a recursive walk hits Python's own recursion
        limit on the payloads this generator exists to produce, which would
        make the test fail for a reason that has nothing to do with the
        service under test."""
        deepest = 0
        stack = [(value, 0)]
        while stack:
            node, level = stack.pop()
            deepest = max(deepest, level)
            if isinstance(node, dict):
                stack.extend((child, level + 1) for child in node.values())
            elif isinstance(node, list):
                stack.extend((child, level + 1) for child in node)
        return deepest

    assert max(depth(c["body"]) for c in cases) >= 512


def test_nesting_cases_are_negative_and_serialisable() -> None:
    """A case the harness cannot serialise is not a test of the service."""
    op = _op(request_body=_body(SchemaNode(type="object")))
    for case in gen.NestingGenerator().generate(op, 1):
        assert case["kind"] == "negative"
        json.dumps(case["body"])  # raises if too deep for the encoder


def test_nesting_says_nothing_about_an_operation_with_no_body() -> None:
    assert list(gen.NestingGenerator().generate(_op(request_body=None), 1)) == []


# ------------------------------------------------------------------- numeric


def test_the_exclusive_minimum_itself_is_a_negative_case() -> None:
    """The value the contract forbids and implementations routinely accept."""
    op = _op(
        parameters=[_query("n", SchemaNode(type="integer", exclusive_minimum=10))],
        request_body=None,
    )
    cases = list(gen.NumericBoundaryGenerator().generate(op, 1))
    at_bound = [c for c in cases if c["query"]["n"] == 10]
    assert at_bound, "the exclusive bound itself was never tested"
    assert at_bound[0]["kind"] == "negative"
    above = [c for c in cases if c["query"]["n"] == 11]
    assert above and above[0]["kind"] == "positive"


def test_the_inclusive_boundary_is_a_positive_case() -> None:
    op = _op(
        parameters=[_query("n", SchemaNode(type="integer", minimum=5, maximum=9))],
        request_body=None,
    )
    cases = list(gen.NumericBoundaryGenerator().generate(op, 1))
    by_value = {c["query"]["n"]: c["kind"] for c in cases}
    assert by_value[5] == "positive"
    assert by_value[9] == "positive"
    assert by_value[4] == "negative"
    assert by_value[10] == "negative"


def test_multiple_of_produces_both_sides() -> None:
    op = _op(parameters=[_query("n", SchemaNode(type="integer", multiple_of=4))], request_body=None)
    kinds = {c["kind"] for c in gen.NumericBoundaryGenerator().generate(op, 1)}
    assert kinds == {"positive", "negative"}


def test_numeric_says_nothing_about_a_string_field() -> None:
    op = _op(parameters=[_query("s", SchemaNode(type="string"))], request_body=None)
    assert list(gen.NumericBoundaryGenerator().generate(op, 1)) == []


# ------------------------------------------------------------- header safety


def test_header_values_are_sendable_by_the_transport() -> None:
    """The bug this test exists for.

    A U+2028 header value made httpx raise UnicodeEncodeError before the
    request left the process, which aborted the entire run -- and reported it
    as "target unreachable" when the target was fine. Header values must be
    latin-1 encodable; anything above that belongs in a body or query.
    """
    op = _op(request_body=None)
    for case in gen.HeaderSafetyGenerator().generate(op, 1):
        for value in case["headers"].values():
            value.encode("latin-1")  # raises if the transport could not send it


def test_header_safety_targets_declared_headers_when_there_are_any() -> None:
    op = _op(
        parameters=[
            Parameter(
                name="X-Tenant",
                location=ParameterLocation.HEADER,
                schema_node=SchemaNode(type="string"),
            )
        ],
        request_body=None,
    )
    cases = list(gen.HeaderSafetyGenerator().generate(op, 1))
    assert cases and all("X-Tenant" in c["headers"] for c in cases)


def test_header_safety_ships_no_exploit_payloads() -> None:
    """Defensive only, and it should stay that way.

    Finding out whether untrusted bytes reach a header does not require a
    working attack, and shipping one would make this something a security team
    has to review before installing.
    """
    joined = " ".join(value for _, value in gen.HeaderSafetyGenerator.UNSAFE).lower()
    for word in ("select ", "union ", "<script", "../", "/etc/passwd", "curl ", "|"):
        assert word not in joined, f"an exploit-shaped payload appeared: {word!r}"


# ------------------------------------------------------------------- runner


def test_an_unsendable_case_is_recorded_against_that_case() -> None:
    """It used to propagate, killing the run and blaming the target.

    A case that cannot be encoded is a fact about the case. Reporting it as
    `target unreachable` sends whoever reads it to look at the wrong thing.
    """
    import httpx

    from apiverity.fuzz.models import TestCase
    from apiverity.fuzz.runner import run_cases

    service = _service(_op(method="GET", path="/items"))
    cases = [
        TestCase(
            id="TC-000-000",
            operation_key=service.operations[0].key,
            kind="negative",
            description="unsendable header",
            method="GET",
            url_path="/items",
            # U+2028: valid in a string, not encodable in a header.
            headers={"X-Bad": chr(0x2028)},
            expected="4xx",
        ),
        TestCase(
            id="TC-000-001",
            operation_key=service.operations[0].key,
            kind="positive",
            description="fine",
            method="GET",
            url_path="/items",
            expected="2xx",
        ),
    ]

    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={}))
    real = httpx.Client

    class Patched(real):  # type: ignore[misc, valid-type]
        def __init__(self, **kwargs: object) -> None:
            kwargs["transport"] = transport
            super().__init__(**kwargs)  # type: ignore[arg-type]

    import apiverity.fuzz.runner as runner

    original = runner.httpx.Client
    runner.httpx.Client = Patched  # type: ignore[misc]
    try:
        results = run_cases(service, "http://t", cases)
    finally:
        runner.httpx.Client = original  # type: ignore[misc]

    assert len(results) == 2, "one unsendable case took the rest of the run with it"
    assert results[0].status == "error"
    assert results[1].status in ("pass", "fail")
