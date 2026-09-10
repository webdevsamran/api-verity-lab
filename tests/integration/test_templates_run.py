"""The built-in templates, run. That is the whole idea.

`apiverity workflow --template crud-lifecycle` prints a manifest for somebody
to run. Nothing ever ran one.

They were tested against themselves -- `assert "{{ refresh_token }}" in
auth.steps[0].request.body[...]` -- and the assertion held while every template
was unrunnable in three independent ways at once:

- `{{ id }}` for a variable, where `WorkflowEngine` substitutes `{id}`;
- `extract={"widget_id": "id"}`, where the engine's JSONPath subset is `$.a.b`
  and a bare field name matches nothing;
- `assert_jsonpath={"state": "submitted"}`, the same mistake in the other
  direction.

Run as printed, `crud-lifecycle` failed on its first request with *"could not
extract 'widget_id' from id"* and never reached the `{{ }}` in its second.

A test that renders a template and inspects it can only agree with whatever the
template says. This one sends the requests, against
`fixtures/apis/templates/openapi.yaml` -- a contract carrying every path the
four of them name, so each runs unedited.
"""

from __future__ import annotations

import pytest

from apiverity.core.model import Service
from apiverity.mock import MockServer
from apiverity.specs.loader import detect_and_load
from apiverity.stateful.engine import WorkflowEngine
from apiverity.stateful.graph import validate_workflow_graph
from apiverity.stateful.models import Workflow, WorkflowResult
from apiverity.stateful.templates import TEMPLATES

_CONTRACT = "fixtures/apis/templates/openapi.yaml"
_INPUTS = {"refresh_token": "refresh-abcdefgh"}


@pytest.fixture(scope="module")
def service() -> Service:
    loaded, findings, _plugin = detect_and_load(_CONTRACT)
    assert [f.rule_id for f in findings] == [], "the fixture itself must load clean"
    return loaded


def _template(name: str) -> Workflow:
    workflow = TEMPLATES[name](base_url="unused")
    # The templates ship an allowlist naming the base URL they were given. The
    # mock binds an ephemeral port, so the allowlist is dropped here and the
    # target is the one this test hands the engine -- which is the same
    # decision `--base-url` represents on the command line.
    workflow.allowed_hosts = []
    return workflow


def _run(service: Service, name: str) -> WorkflowResult:
    workflow = _template(name)
    supplied = {k: v for k, v in _INPUTS.items() if k in workflow.inputs}
    with MockServer(service, port=0) as mock:
        return WorkflowEngine(workflow, mock.base_url, supplied).run()


@pytest.mark.parametrize("name", ["auth-refresh", "crud-lifecycle", "pagination-walk"])
def test_the_template_runs_green_against_the_contract_it_assumes(
    service: Service, name: str
) -> None:
    result = _run(service, name)
    assert result.status == "pass", [(s.step, s.violations) for s in result.steps]


def test_the_extraction_the_template_declares_actually_extracts(service: Service) -> None:
    """`extract={"widget_id": "id"}` produced *"could not extract 'widget_id'
    from id"* on the first request of the first template."""
    result = _run(service, "crud-lifecycle")
    assert result.steps[0].extracted.get("widget_id")
    assert result.variables["widget_id"]


def test_the_path_placeholder_is_filled_rather_than_sent(service: Service) -> None:
    """A `{{ widget_id }}` nothing substitutes goes out as a literal path
    segment. The read would answer 404, not 200."""
    result = _run(service, "crud-lifecycle")
    read = next(s for s in result.steps if s.step == "read")
    assert read.actual_status == 200


def test_the_token_reaches_the_second_request(service: Service) -> None:
    """`Bearer {{ access_token }}` was sent as that exact text."""
    workflow = _template("auth-refresh")
    assert workflow.steps[1].request.headers["Authorization"] == "Bearer {access_token}"
    result = _run(service, "auth-refresh")
    assert result.variables["access_token"]
    assert result.steps[1].actual_status == 200


def test_an_assertion_now_fails_on_the_value_rather_than_the_path(
    service: Service,
) -> None:
    """The clearest single piece of evidence.

    `resource-lifecycle` checks that a submitted order reads back as submitted.
    The mock does not implement the state transition, so the check does not
    pass -- and *how* it fails is the point. It used to say "assertion path
    'state' not found", which is the engine reporting that the assertion looked
    somewhere that does not exist. It now says the field held `draft` when
    `submitted` was expected, which is the assertion doing its job against a
    mock that never claimed to transition anything.
    """
    result = _run(service, "resource-lifecycle")
    violations = [v for step in result.steps for v in step.violations]
    assert violations == ["assertion failed at '$.state': expected 'submitted', got 'draft'"]


@pytest.mark.parametrize("name", sorted(TEMPLATES))
def test_every_template_passes_its_own_graph_validation(name: str) -> None:
    """The validator and the templates disagreed with the engine in the same
    direction, so they agreed with each other and nothing showed. Now that both
    read `{name}`, a template that fails this would fail at run time."""
    validation = validate_workflow_graph(TEMPLATES[name](base_url="unused"))
    assert validation.issues == [], [i.message for i in validation.issues]


@pytest.mark.parametrize("name", sorted(TEMPLATES))
def test_no_template_still_writes_the_old_syntax(name: str) -> None:
    """The specific regression, in all three forms."""
    workflow = TEMPLATES[name](base_url="unused")
    for step in [*workflow.steps, *workflow.cleanup]:
        blob = f"{step.request.path} {step.request.headers} {step.request.body}"
        assert "{{" not in blob, f"{name}.{step.name} still writes a double brace"
        assert all(p.startswith("$.") for p in step.extract.values())
        assert all(p.startswith("$.") for p in step.assert_jsonpath)


# ------------------------------------------------- the pre-flight before a run


def _cli(argv: list[str]) -> tuple[int, str]:
    import contextlib
    import io

    from apiverity.cli.main import main

    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    return code, err.getvalue()


def _manifest(tmp_path, body: str):
    path = tmp_path / "wf.yaml"
    path.write_text(body, encoding="utf-8")
    return str(path)


def test_a_manifest_with_an_unfillable_variable_never_reaches_the_network(
    tmp_path,
) -> None:
    """`stateful/graph.py` has existed since the engine did and no command
    called it. A request going out with a literal `{missing}` in its path is
    the thing it was written to prevent, and it prevented nothing."""
    path = _manifest(
        tmp_path,
        'name: broken\nsteps:\n  - name: get\n    request: {method: GET, path: "/x/{missing}"}\n',
    )
    code, err = _cli(["--no-config", "workflow", path, "--base-url", "http://127.0.0.1:1"])
    assert code != 0
    assert "undefined variables: ['missing']" in err
    assert "refusing to run" in err


def test_the_check_can_be_skipped_deliberately(tmp_path) -> None:
    """It refuses a manifest, so there has to be a way past it -- and the way
    past is a flag somebody typed, not a default."""
    path = _manifest(
        tmp_path,
        'name: broken\nsteps:\n  - name: get\n    request: {method: GET, path: "/x/{missing}"}\n',
    )
    code, err = _cli(
        ["--no-config", "workflow", path, "--base-url", "http://127.0.0.1:1", "--no-preflight"]
    )
    assert "refusing to run" not in err
    assert code != 0  # nothing is listening on port 1; the point is that it tried


def test_a_variable_supplied_on_the_command_line_satisfies_the_check(tmp_path) -> None:
    path = _manifest(
        tmp_path,
        'name: parameterised\nsteps:\n  - name: get\n    request: {method: GET, path: "/t/{tenant}"}\n',
    )
    _code, err = _cli(
        [
            "--no-config",
            "workflow",
            path,
            "--base-url",
            "http://127.0.0.1:1",
            "--input",
            "tenant=acme",
        ]
    )
    assert "refusing to run" not in err


def test_a_warning_prints_and_the_run_continues(service: Service, tmp_path) -> None:
    """An uncleaned resource is worth knowing about and is not a reason to
    refuse: the run is what tells you whether it mattered."""
    path = _manifest(
        tmp_path,
        "name: leaky\n"
        "steps:\n"
        "  - name: create\n"
        "    request: {method: POST, path: /widgets, body: {name: x}}\n"
        "    assert: {status: 201}\n"
        '    extract: {widget_id: "$.id"}\n'
        "  - name: read\n"
        '    request: {method: GET, path: "/widgets/{widget_id}"}\n',
    )
    with MockServer(service, port=0) as mock:
        code, err = _cli(["--no-config", "workflow", path, "--base-url", mock.base_url])
    assert "never deleted in cleanup" in err
    assert "refusing to run" not in err
    assert code == 0
