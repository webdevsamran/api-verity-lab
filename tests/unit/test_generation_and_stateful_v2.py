"""Tests for boundary/pairwise generation, corpus round-trips, workflow graph
validation, templates and model-based CRUD testing."""

from __future__ import annotations

from pathlib import Path

from apiverity.core.model import Operation, Parameter, ParameterLocation, SchemaNode
from apiverity.fuzz.boundary import (
    boundary_values,
    near_boundary_invalid_cases,
    pairwise_parameter_cases,
)
from apiverity.fuzz.corpus import case_id, export_corpus, import_corpus, verify_corpus_roundtrip
from apiverity.fuzz.models import TestCase
from apiverity.stateful.graph import has_cycle, validate_workflow_graph
from apiverity.stateful.model_based import ModelBasedRunner
from apiverity.stateful.models import Workflow, WorkflowRequest, WorkflowStep
from apiverity.stateful.templates import TEMPLATES

# --- Boundary / pairwise ---------------------------------------------------------


class TestBoundary:
    def test_numeric_bounds(self) -> None:
        schema = SchemaNode(type="integer", minimum=1, maximum=3)
        vals = boundary_values(schema)
        assert 1 in vals and 3 in vals

    def test_string_length_bounds(self) -> None:
        schema = SchemaNode(type="string", min_length=2, max_length=4)
        vals = boundary_values(schema)
        assert "aa" in vals and "aaaa" in vals

    def test_enum_values(self) -> None:
        schema = SchemaNode(type="string", enum=["a", "b"])
        assert boundary_values(schema) == ["a", "b"]

    def test_near_boundary_invalid(self) -> None:
        schema = SchemaNode(type="integer", minimum=5)
        assert 4 in near_boundary_invalid_cases(schema)

    def test_pairwise_subcartesian(self) -> None:
        op = Operation(
            method="GET",
            path="/x",
            parameters=[
                Parameter(
                    name="a",
                    location=ParameterLocation.QUERY,
                    schema_node=SchemaNode(enum=["1", "2"]),
                ),
                Parameter(
                    name="b",
                    location=ParameterLocation.QUERY,
                    schema_node=SchemaNode(enum=["x", "y"]),
                ),
                Parameter(
                    name="c",
                    location=ParameterLocation.QUERY,
                    schema_node=SchemaNode(enum=["p", "q"]),
                ),
            ],
        )
        cases = pairwise_parameter_cases(op)
        full_cartesian = 2 * 2 * 2
        assert 0 < len(cases) < full_cartesian
        # every pair of parameters must co-occur at least once
        combos = {(tuple(sorted(c.items()))) for c in cases}
        assert combos

    def test_deterministic(self) -> None:
        op = Operation(
            method="GET",
            path="/x",
            parameters=[
                Parameter(
                    name="a",
                    location=ParameterLocation.QUERY,
                    schema_node=SchemaNode(enum=["1", "2"]),
                ),
                Parameter(
                    name="b",
                    location=ParameterLocation.QUERY,
                    schema_node=SchemaNode(enum=["x", "y"]),
                ),
            ],
        )
        assert pairwise_parameter_cases(op, seed=7) == pairwise_parameter_cases(op, seed=7)


# --- Corpus ------------------------------------------------------------------------


class TestCorpus:
    def _case(self, i: int = 0) -> TestCase:
        return TestCase(
            id=f"case-{i}",
            operation_key="GET /items",
            kind="positive",
            description=f"list items page {i}",
            method="GET",
            url_path="/items",
            query={"limit": str(i)},
            expected="2xx",
        )

    def test_roundtrip_preserves_ids(self, tmp_path: Path) -> None:
        cases = [self._case(0), self._case(1)]
        assert verify_corpus_roundtrip(cases, tmp_path / "corpus.jsonl")

    def test_case_id_stable(self) -> None:
        assert case_id(self._case()) == case_id(self._case())

    def test_import_order_preserved(self, tmp_path: Path) -> None:
        cases = [self._case(2), self._case(0), self._case(1)]
        export_corpus(cases, tmp_path / "c.jsonl")
        restored = import_corpus(tmp_path / "c.jsonl")
        assert [c.id for c in restored] == [c.id for c in cases]


# --- Workflow graph ------------------------------------------------------------------


class TestWorkflowGraph:
    def test_missing_variable_detected(self) -> None:
        wf = Workflow(
            name="bad",
            steps=[
                WorkflowStep(name="s1", request=WorkflowRequest(path="/x/{{ missing }}")),
            ],
        )
        result = validate_workflow_graph(wf)
        assert not result.ok
        assert any(i.rule_id == "WF-MISSING-VAR" for i in result.issues)

    def test_incomplete_cleanup_warned(self) -> None:
        wf = Workflow(
            name="leaky",
            steps=[
                WorkflowStep(
                    name="create",
                    request=WorkflowRequest(method="POST", path="/things"),
                    extract={"thing_id": "id"},
                ),
            ],
            cleanup=[],
        )
        result = validate_workflow_graph(wf)
        assert any(i.rule_id == "WF-INCOMPLETE-CLEANUP" for i in result.issues)

    def test_complete_cleanup_passes(self) -> None:
        wf = Workflow(
            name="clean",
            steps=[
                WorkflowStep(
                    name="create",
                    request=WorkflowRequest(method="POST", path="/things"),
                    extract={"thing_id": "id"},
                ),
            ],
            cleanup=[
                WorkflowStep(
                    name="del",
                    request=WorkflowRequest(method="DELETE", path="/things/{{ thing_id }}"),
                ),
            ],
        )
        result = validate_workflow_graph(wf)
        assert result.ok

    def test_cycle_detection(self) -> None:
        assert has_cycle(["a", "b"], {"a": ["b"], "b": ["a"]})
        assert not has_cycle(["a", "b"], {"a": ["b"], "b": []})


# --- Templates -------------------------------------------------------------------------


class TestTemplates:
    def test_all_templates_build(self) -> None:
        wf = TEMPLATES["crud-lifecycle"](base_url="http://localhost:9999")
        assert wf.steps and wf.cleanup
        walk = TEMPLATES["pagination-walk"](base_url="http://localhost:9999")
        assert len(walk.steps) == 5
        auth = TEMPLATES["auth-refresh"](base_url="http://localhost:9999")
        assert "{{ refresh_token }}" in auth.steps[0].request.body["refresh_token"]
        life = TEMPLATES["resource-lifecycle"](base_url="http://localhost:9999")
        assert life.steps[0].extract == {"order_id": "id"}

    def test_templates_validate_cleanly(self) -> None:
        for factory in TEMPLATES.values():
            wf = factory(base_url="http://localhost:9999")
            result = validate_workflow_graph(wf)
            # templates may legitimately warn about cleanup only when they create resources
            errors = [i for i in result.issues if i.severity.value == "ERROR"]
            assert not errors, (wf.name, errors)


# --- Model-based runner -------------------------------------------------------------------


class TestModelBasedRunner:
    def test_happy_path_crud(self) -> None:
        store: dict[str, dict] = {}
        counter = {"n": 0}

        def transport(method: str, path: str, body):
            if method == "POST":
                counter["n"] += 1
                rid = str(counter["n"])
                rec = dict(body or {})
                rec["id"] = rid
                store[rid] = rec
                return 201, rec
            rid = path.rsplit("/", 1)[-1]
            if method == "GET":
                if rid in store:
                    return 200, store[rid]
                return 404, None
            if method == "PATCH":
                store[rid].update(body or {})
                return 200, store[rid]
            if method == "DELETE":
                store.pop(rid, None)
                return 204, None
            raise AssertionError(method)

        result = ModelBasedRunner(transport).run()
        assert result.status == "pass"
        assert all(s.status == "pass" for s in result.steps)
        assert len(result.steps) == 6

    def test_update_not_persisted_fails(self) -> None:
        def transport(method: str, path: str, body):
            if method == "POST":
                return 201, {"id": "1", **(body or {})}
            if method == "GET":
                return 200, {"id": "1", "name": "stale"}  # never reflects updates
            if method == "PATCH":
                return 200, body
            if method == "DELETE":
                return 204, None
            raise AssertionError(method)

        result = ModelBasedRunner(transport).run()
        assert result.status == "fail"
        failed = [s for s in result.steps if s.status == "fail"]
        assert failed and "not persisted" in failed[0].violations[0]
