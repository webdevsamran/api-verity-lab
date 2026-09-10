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
    """`{name}`, not `{{ name }}`.

    Every test in this class used to be written in the double-brace syntax the
    validator looked for and the engine has never implemented -- so they passed
    against a validator that found nothing at all in a real manifest.
    """

    def test_missing_variable_detected(self) -> None:
        wf = Workflow(
            name="bad",
            steps=[
                WorkflowStep(name="s1", request=WorkflowRequest(path="/x/{missing}")),
            ],
        )
        result = validate_workflow_graph(wf)
        assert not result.ok
        assert any(i.rule_id == "WF-MISSING-VAR" for i in result.issues)

    def test_the_double_brace_form_is_not_a_variable(self) -> None:
        """The regression that made every other test in this class vacuous. If
        the validator ever reads `{{ missing }}` again, this fails."""
        wf = Workflow(
            name="literal",
            steps=[
                WorkflowStep(name="s1", request=WorkflowRequest(path="/x/{{ missing }}")),
            ],
        )
        assert validate_workflow_graph(wf).ok

    def test_a_supplied_input_is_available(self) -> None:
        wf = Workflow(
            name="parameterised",
            inputs=["tenant"],
            steps=[WorkflowStep(name="s1", request=WorkflowRequest(path="/t/{tenant}"))],
        )
        assert validate_workflow_graph(wf).ok

    def test_incomplete_cleanup_warned(self) -> None:
        wf = Workflow(
            name="leaky",
            steps=[
                WorkflowStep(
                    name="create",
                    request=WorkflowRequest(method="POST", path="/things"),
                    extract={"thing_id": "$.id"},
                ),
                # The variable has to *address* something for it to be a
                # resource somebody could clean up -- see the next test.
                WorkflowStep(name="read", request=WorkflowRequest(path="/things/{thing_id}")),
            ],
            cleanup=[],
        )
        result = validate_workflow_graph(wf)
        assert any(i.rule_id == "WF-INCOMPLETE-CLEANUP" for i in result.issues)

    def test_a_value_that_addresses_nothing_is_not_an_uncleaned_resource(self) -> None:
        """`POST /auth/token` extracting an `access_token` is not a resource
        with a DELETE endpoint, and the rule warned about one until a created
        resource was defined as a variable something puts in a *path*."""
        wf = Workflow(
            name="auth",
            steps=[
                WorkflowStep(
                    name="refresh",
                    request=WorkflowRequest(method="POST", path="/auth/token"),
                    extract={"access_token": "$.access_token"},
                ),
                WorkflowStep(
                    name="call",
                    request=WorkflowRequest(
                        path="/me", headers={"Authorization": "Bearer {access_token}"}
                    ),
                ),
            ],
        )
        assert validate_workflow_graph(wf).issues == []

    def test_complete_cleanup_passes(self) -> None:
        wf = Workflow(
            name="clean",
            steps=[
                WorkflowStep(
                    name="create",
                    request=WorkflowRequest(method="POST", path="/things"),
                    extract={"thing_id": "$.id"},
                ),
                WorkflowStep(name="read", request=WorkflowRequest(path="/things/{thing_id}")),
            ],
            cleanup=[
                WorkflowStep(
                    name="del",
                    request=WorkflowRequest(method="DELETE", path="/things/{thing_id}"),
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
        assert auth.steps[0].request.body["refresh_token"] == "{refresh_token}"
        life = TEMPLATES["resource-lifecycle"](base_url="http://localhost:9999")
        assert life.steps[0].extract == {"order_id": "$.id"}

    def test_templates_validate_cleanly(self) -> None:
        """No issues at all, not just no errors.

        The comment here said templates "may legitimately warn about cleanup",
        which was true of a validator that could not see a `{name}`: it warned
        about every created resource including the ones cleanup deleted.
        """
        for factory in TEMPLATES.values():
            wf = factory(base_url="http://localhost:9999")
            result = validate_workflow_graph(wf)
            assert result.issues == [], (wf.name, [i.message for i in result.issues])


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


class TestDeclaredInputs:
    """`Workflow.inputs` was a field nothing filled.

    It is documented on the model as "variables supplied by the caller", it is
    read by the graph validator when deciding whether a step's variables are
    available, and until an Arazzo description needed one: no manifest key
    parsed into it, no engine argument accepted one, and no command passed one.

    A workflow declaring `user_name` therefore ran with the variable absent,
    and `_substitute` leaves an unknown `{user_name}` exactly as written -- so
    the request went out with a literal brace in it and the run reported
    whatever the server made of that.
    """

    def test_a_manifest_declaring_inputs_parses_them(self, tmp_path: Path) -> None:
        from apiverity.stateful.engine import load_workflow_manifest

        manifest = tmp_path / "wf.yaml"
        manifest.write_text(
            "name: needs-input\n"
            "inputs: [tenant]\n"
            "steps:\n"
            "  - name: get\n"
            '    request: {method: GET, path: "/t/{tenant}"}\n',
            encoding="utf-8",
        )
        assert load_workflow_manifest(str(manifest)).inputs == ["tenant"]

    def test_a_missing_input_stops_the_run_rather_than_being_sent_literally(self) -> None:
        from apiverity.stateful.engine import WorkflowEngine

        workflow = Workflow(
            name="needs-input",
            inputs=["tenant"],
            steps=[WorkflowStep(name="get", request=WorkflowRequest(path="/t/{tenant}"))],
        )
        try:
            WorkflowEngine(workflow, "http://127.0.0.1:1")
            raised = ""
        except ValueError as exc:
            raised = str(exc)
        assert "['tenant']" in raised and "--input" in raised

    def test_a_supplied_input_seeds_the_variable_table(self) -> None:
        from apiverity.stateful.engine import WorkflowEngine

        workflow = Workflow(
            name="needs-input",
            inputs=["tenant"],
            steps=[WorkflowStep(name="get", request=WorkflowRequest(path="/t/{tenant}"))],
        )
        engine = WorkflowEngine(workflow, "http://127.0.0.1:1", {"tenant": "acme"})
        assert engine.inputs == {"tenant": "acme"}

    def test_an_undeclared_input_is_still_available(self) -> None:
        """Declaring is how a workflow says an input is *required*. Supplying
        one it did not declare is the caller's business, not an error -- and a
        template that used it would otherwise have no way to be filled."""
        from apiverity.stateful.engine import WorkflowEngine

        workflow = Workflow(name="w", steps=[])
        engine = WorkflowEngine(workflow, "http://127.0.0.1:1", {"extra": "1"})
        assert engine.run().variables == {"extra": "1"}
