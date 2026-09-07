"""Workflow inference from declared links (#20).

The safety properties are the feature. A tool that hands someone a runnable
manifest containing a DELETE it inferred from a path shape is worse than one
that infers nothing, so most of these tests are about what the output does
*not* do.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from apiverity.specs.loader import detect_and_load
from apiverity.stateful.infer import (
    DESTRUCTIVE_METHODS,
    infer_workflows,
    render_manifest,
)

_SPEC = """\
openapi: "3.0.3"
info: {{ title: Linked API, version: "1.0.0" }}
paths:
  /users:
    post:
      operationId: createUser
      summary: Create a user
      responses:
        "201":
          description: created
          content:
            application/json:
              schema: {{ type: object, properties: {{ id: {{ type: string }} }} }}
          links:
{links}
  /users/{{id}}:
    get:
      operationId: getUser
      responses:
        "200": {{ description: ok }}
    delete:
      operationId: deleteUser
      responses:
        "204": {{ description: gone }}
"""

_GET_LINK = """\
            GetUser:
              operationId: getUser
              parameters: { id: "$response.body#/id" }
"""
_DELETE_LINK = """\
            DeleteUser:
              operationId: deleteUser
              parameters: { id: "$response.body#/id" }
"""
_DANGLING_LINK = """\
            Audit:
              operationId: notInThisDocument
              parameters: { id: "$response.body#/id" }
"""
_HEADER_LINK = """\
            NextPage:
              operationId: getUser
              parameters: { cursor: "$response.header.X-Next" }
"""
_REF_LINK = """\
            ByRef:
              operationRef: "#/paths/~1users~1{id}/get"
              parameters: { id: "$response.body#/id" }
"""
_EXTERNAL_REF_LINK = """\
            Elsewhere:
              operationRef: "https://other.example.com/spec.yaml#/paths/~1x/get"
"""


def _load(tmp_path: Path, *links: str, name: str = "spec.yaml"):
    spec = tmp_path / name
    spec.write_text(_SPEC.format(links="".join(links) or "            {}\n"), encoding="utf-8")
    service, _, _ = detect_and_load(str(spec))
    return service


def _manifest(tmp_path: Path, *links: str) -> str:
    service = _load(tmp_path, *links)
    return render_manifest(service, infer_workflows(service))


# --------------------------------------------------------------------- links


def test_links_reach_the_model(tmp_path: Path) -> None:
    """They were not parsed at all before this."""
    service = _load(tmp_path, _GET_LINK)
    post = next(op for op in service.operations if op.method == "POST")
    links = [link for response in post.responses for link in response.links]
    assert [link.name for link in links] == ["GetUser"]
    assert links[0].operation_id == "getUser"
    assert links[0].parameters == {"id": "$response.body#/id"}


def test_a_link_by_operation_ref_resolves(tmp_path: Path) -> None:
    service = _load(tmp_path, _REF_LINK)
    draft = infer_workflows(service)[0]
    assert draft.unresolved == []
    assert draft.steps[0][1] is not None


def test_an_external_operation_ref_is_not_resolved(tmp_path: Path) -> None:
    """It names an operation in a file this run never read.

    A draft step for it would be a step nobody can check against anything.
    """
    service = _load(tmp_path, _EXTERNAL_REF_LINK)
    assert infer_workflows(service)[0].unresolved


def test_a_spec_with_no_links_infers_nothing(tmp_path: Path) -> None:
    """And says so, rather than falling back to guessing.

    The spec here has POST /users and DELETE /users/{id} -- exactly the shape
    a path-matching heuristic would turn into a lifecycle workflow.
    """
    service = _load(tmp_path)
    assert infer_workflows(service) == []
    manifest = render_manifest(service, [])
    assert "nothing to infer" in manifest
    assert "DELETE" not in manifest, "a DELETE was suggested with no link declaring it"


# --------------------------------------------------------------------- safety


def test_every_step_is_commented_out(tmp_path: Path) -> None:
    """The output is a draft to read, not a manifest to run."""
    manifest = _manifest(tmp_path, _GET_LINK, _DELETE_LINK)
    for line in manifest.splitlines():
        assert not line or line.startswith("#"), f"an uncommented line escaped: {line!r}"


def test_destructive_steps_are_commented_twice(tmp_path: Path) -> None:
    """So uncommenting the file wholesale does not enable them.

    This is the property the whole feature rests on: one careless `sed` must
    not turn a draft into a DELETE against whatever `allowed_hosts` names.
    """
    manifest = _manifest(tmp_path, _GET_LINK, _DELETE_LINK)
    delete_lines = [ln for ln in manifest.splitlines() if "DeleteUser" in ln or "DELETE" in ln]
    assert delete_lines
    step_lines = [ln for ln in delete_lines if "name: DeleteUser" in ln or "method: DELETE" in ln]
    assert step_lines
    for line in step_lines:
        assert line.startswith("# #"), f"a destructive line was only commented once: {line!r}"

    # And a single uncomment pass leaves them commented.
    once = "\n".join(ln[2:] if ln.startswith("# ") else ln for ln in manifest.splitlines())
    for line in once.splitlines():
        if "method: DELETE" in line:
            assert line.lstrip().startswith("#"), "one uncomment pass armed a DELETE"


def test_a_destructive_step_is_announced_before_it_appears(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, _DELETE_LINK)
    assert "will delete data" in manifest
    banner = manifest.index("will delete data")
    step = manifest.index("name: DeleteUser")
    assert banner < step, "the warning must precede the step it warns about"


def test_post_counts_as_destructive() -> None:
    """A link chain ending in a POST creates rows in whatever it points at."""
    assert "POST" in DESTRUCTIVE_METHODS
    assert "DELETE" in DESTRUCTIVE_METHODS
    assert "GET" not in DESTRUCTIVE_METHODS
    assert "HEAD" not in DESTRUCTIVE_METHODS


def test_a_read_only_step_is_commented_only_once(tmp_path: Path) -> None:
    """The distinction has to be visible, or the double comment means nothing."""
    manifest = _manifest(tmp_path, _GET_LINK)
    get_lines = [ln for ln in manifest.splitlines() if "method: GET" in ln]
    assert get_lines
    assert all(not ln.startswith("# #") for ln in get_lines)


# ----------------------------------------------------------------- extraction


def test_a_response_body_pointer_becomes_a_jsonpath(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, _GET_LINK)
    assert 'extract: {id: "$.id"}' in manifest


def test_an_expression_the_engine_cannot_express_is_flagged_not_faked(
    tmp_path: Path,
) -> None:
    """A plausible-looking jsonpath for a header would run and extract nothing.

    Silently wrong is the worst outcome here: the workflow passes, the
    variable is empty, and the next step tests something other than what its
    author meant.
    """
    manifest = _manifest(tmp_path, _HEADER_LINK)
    assert "UNRESOLVED cursor" in manifest
    assert "X-Next" in manifest
    assert '"$.X-Next"' not in manifest
    assert "extract: {cursor" not in manifest


def test_a_dangling_link_is_skipped_with_a_reason(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, _DANGLING_LINK)
    assert "SKIPPED" in manifest
    assert "notInThisDocument" in manifest
    assert "name: Audit" not in manifest, "a step was emitted for an unresolvable link"


def test_the_summary_counts_what_happened(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, _GET_LINK, _DELETE_LINK, _DANGLING_LINK)
    assert "2 linked step(s) resolved" in manifest
    assert "1 skipped" in manifest
    assert "1 destructive" in manifest


def test_rendering_is_stable(tmp_path: Path) -> None:
    first = _manifest(tmp_path, _GET_LINK, _DELETE_LINK)
    second = _manifest(tmp_path, _GET_LINK, _DELETE_LINK)
    assert first == second


# ------------------------------------------------------------------------ CLI


def _args(**kw: object) -> argparse.Namespace:
    base: dict[str, object] = {
        "manifest": "",
        "base_url": None,
        "infer": False,
        "template": None,
        "list_templates": False,
        "output": None,
        "json": False,
    }
    base.update(kw)
    return argparse.Namespace(**base)


def test_infer_writes_to_a_file_when_asked(tmp_path: Path) -> None:
    from apiverity.cli.commands.testing import cmd_workflow

    spec = tmp_path / "spec.yaml"
    spec.write_text(_SPEC.format(links=_GET_LINK), encoding="utf-8")
    out = tmp_path / "draft.yaml"
    assert cmd_workflow(_args(manifest=str(spec), infer=True, output=str(out))) == 0
    assert "GetUser" in out.read_text(encoding="utf-8")


def test_infer_refuses_to_overwrite(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A draft that silently replaced a hand-written manifest would be the
    worst possible outcome of a command whose whole premise is caution."""
    from apiverity.cli.commands.testing import cmd_workflow

    spec = tmp_path / "spec.yaml"
    spec.write_text(_SPEC.format(links=_GET_LINK), encoding="utf-8")
    existing = tmp_path / "mine.yaml"
    existing.write_text("name: hand-written\n", encoding="utf-8")

    assert cmd_workflow(_args(manifest=str(spec), infer=True, output=str(existing))) == 2
    assert "refusing to overwrite" in capsys.readouterr().err
    assert existing.read_text(encoding="utf-8") == "name: hand-written\n"


# ------------------------------------------------------------------ templates


def test_the_built_in_templates_are_reachable(capsys: pytest.CaptureFixture[str]) -> None:
    """Four templates existed, were tested, and had no CLI route to them.

    The advice given when a spec declares no links pointed at them, so it had
    to become true.
    """
    from apiverity.cli.commands.testing import cmd_workflow

    assert cmd_workflow(_args(list_templates=True)) == 0
    listed = capsys.readouterr().out
    for name in ("crud-lifecycle", "pagination-walk", "auth-refresh", "resource-lifecycle"):
        assert name in listed


def test_a_template_renders_as_usable_yaml(capsys: pytest.CaptureFixture[str]) -> None:
    import yaml

    from apiverity.cli.commands.testing import cmd_workflow

    assert cmd_workflow(_args(template="crud-lifecycle", base_url="http://127.0.0.1:9")) == 0
    text = capsys.readouterr().out
    loaded = yaml.safe_load(text)
    assert loaded["name"] == "crud-lifecycle"
    assert loaded["steps"]
    assert "Review allowed_hosts" in text


def test_an_unknown_template_lists_the_real_ones(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from apiverity.cli.commands.testing import cmd_workflow

    assert cmd_workflow(_args(template="nope")) == 2
    err = capsys.readouterr().err
    assert "unknown template 'nope'" in err
    assert "crud-lifecycle" in err


def test_the_no_links_advice_points_at_things_that_exist(tmp_path: Path) -> None:
    """The first draft of this message cited `docs/workflows.md` and
    `--template crud`. Neither existed. That is the exact defect this whole
    pass is about, so it gets a test."""
    from apiverity.stateful.templates import TEMPLATES

    service = _load(tmp_path)
    manifest = render_manifest(service, [])
    root = Path(__file__).resolve().parents[2]

    import re

    for doc in re.findall(r"docs/[\w-]+\.md", manifest):
        assert (root / doc).is_file(), f"the draft cites {doc}, which does not exist"
    for flag in re.findall(r"apiverity workflow (--[\w-]+)", manifest):
        assert flag in ("--list-templates", "--template", "--infer"), flag
    assert TEMPLATES, "the advice offers templates; there had better be some"
