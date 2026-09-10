"""Arazzo 1.1.0 in and out of this project's workflow manifests.

`apiverity workflow` runs a manifest this project invented. Arazzo is the
OpenAPI Initiative's workflow specification for the same job -- version 1.1.0,
released 2026-05-18, checked at
<https://github.com/OAI/Arazzo-Specification/releases> on 2026-09-10 -- and a
proprietary format is a reason not to adopt a tool regardless of how good the
engine behind it is.

So this reads Arazzo descriptions and writes them. It does **not** claim to be
an Arazzo runtime, and the difference is most of this module.

## The two formats do not describe the same machine

The manifest is a straight line: steps in document order, each one request,
stop at the first failure, then best-effort cleanup. Arazzo describes a graph:
`onSuccess`/`onFailure` actions can `goto` another step or another workflow,
`retry` with a limit and a delay, steps can `dependsOn` other steps, a step can
*be* a whole other workflow, and 1.1.0 added AsyncAPI steps that publish to or
subscribe from a channel.

None of that has an equivalent here. It could be dropped silently and the
imported workflow would still run -- which is exactly the failure this project
treats as worse than an error, because a `retry` that vanished and a `goto`
that vanished both leave a workflow that *appears* to have been imported
whole. Every construct with no equivalent is therefore reported as an
`Untranslated` entry naming the workflow, the step, the construct and why.

## What maps, exactly

| Arazzo | Manifest | Note |
|---|---|---|
| `operationPath` | `request.method` + `request.path` | The JSON Pointer names the path and method literally, so this resolves with no source document |
| `operationId` | -- | Needs the source description to know which method and path it is; reported when absent |
| `parameters` (`path`) | `{var}` in `request.path` | The placeholder is renamed to the variable the value expression names |
| `parameters` (`query`, `header`) | `request.query`, `request.headers` | |
| `requestBody.payload` | `request.body` | Runtime expressions inside become `{var}` |
| `outputs` (`$response.body#/a/b`) | `extract` (`$.a.b`) | JSON Pointer and this engine's JSONPath subset are the same shape |
| `successCriteria` (`$statusCode == 200`) | `assert_status` | an OR chain becomes the list |
| `successCriteria` (`$response.body#/a == 'x'`) | `assert_jsonpath` | |
| `timeout` (ms) | `timeout_seconds` | |
| `inputs` (JSON Schema) | `inputs` (names) | Types are dropped: the manifest has nowhere to put them |

## The allowlist an imported description does not have

A manifest carries `allowed_hosts`, and `WorkflowEngine` refuses to send
traffic anywhere else. Arazzo has no such field and nothing in a description
implies one -- a Source Description's `url` is where the *specification
document* lives, which is frequently not where the API is.

So an import leaves `allowed_hosts` empty, and empty means the engine's check
does not fire. That is not a hole introduced here: every request goes to the
`base_url` the operator passes on the command line, and an imported workflow
has no `base_url` of its own, so running one requires `--base-url` and the
operator has named the target themselves. `ArazzoImport.note` says so, and
`docs/arazzo.md` says it again next to the command.

## What checks the export

Structure is checked against the OAI's own published JSON Schema, vendored at
`schemas/vendor/arazzo-1.1-2026-04-15.schema.json` and run over a real exported
document -- and over the bundled fixture, and over a control case that must
fail -- by `tests/unit/test_arazzo.py`.

The schema does not check the *grammar inside* a criterion's `condition`, and
neither does anything else here, because no Arazzo runtime is vendored in this
repository. What is checked is that this module reads back what it writes. A
condition this project emits is therefore known to be structurally valid and
known to round-trip; it is **not** known to have been executed by another
implementation, and this paragraph is the whole of that claim.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from apiverity.core.model import Service
from apiverity.stateful.models import Workflow, WorkflowRequest, WorkflowStep

#: The version this writes and the highest it reads. 1.1.0 was released
#: 2026-05-18; 1.0.x documents differ in ways this module does not use, so they
#: are read too and the version is carried into `ArazzoImport.version`.
ARAZZO_VERSION = "1.1.0"

#: The published schema iteration the vendored copy came from. Named here so
#: the constant, the file and the CI step cannot drift apart silently.
SCHEMA_ITERATION = "https://spec.openapis.org/arazzo/1.1/schema/2026-04-15"

#: `workflowId` and `stepId` SHOULD match this (Arazzo 1.1.0, Workflow Object).
_ID_RE = re.compile(r"^[A-Za-z0-9_\-]+$")
_ID_BAD = re.compile(r"[^A-Za-z0-9_\-]+")

#: `{$sourceDescriptions.name.url}#/paths/~1pets~1{petId}/get`
_OPERATION_PATH_RE = re.compile(
    r"^\{\$sourceDescriptions\.(?P<source>[^.}]+)\.url\}#(?P<pointer>/.*)$"
)

#: `$statusCode == 200`, the shape `assert_status` becomes and comes back from.
_STATUS_RE = re.compile(r"^\$statusCode\s*==\s*(\d{3})$")

#: `$response.body#/a/b == 'value'`, the shape `assert_jsonpath` becomes.
_BODY_EQ_RE = re.compile(r"^\$response\.body#(?P<pointer>/\S*)\s*==\s*(?P<literal>.+)$")

#: `$response.body#/a/b`, the shape `extract` becomes.
_BODY_REF_RE = re.compile(r"^\$response\.body#(?P<pointer>/\S*)$")

#: `$inputs.name` / `$steps.stepId.outputs.name` -- the two expression forms a
#: manifest variable can have come from.
_INPUT_RE = re.compile(r"^\$inputs\.(?P<name>[A-Za-z0-9_.\-]+)$")
_STEP_OUTPUT_RE = re.compile(
    r"^\$steps\.(?P<step>[A-Za-z0-9_\-]+)\.outputs\.(?P<name>[A-Za-z0-9_.\-]+)$"
)

#: `{$expression}` embedded in a string, which is how Arazzo puts a runtime
#: value inside a payload or a URL.
_EMBEDDED_RE = re.compile(r"\{(\$[^{}]+)\}")

#: Parameter locations this engine can send. `querystring` and `cookie` are
#: valid Arazzo and have no `WorkflowRequest` field.
_SENDABLE_LOCATIONS = ("path", "query", "header")


@dataclass(frozen=True)
class Untranslated:
    """One construct that did not survive, and why.

    Reported rather than dropped. A `retry` that disappeared silently leaves a
    workflow that looks imported whole and behaves differently from the one
    that was written.
    """

    workflow: str
    step: str | None
    construct: str
    reason: str

    def __str__(self) -> str:
        where = f"{self.workflow}.{self.step}" if self.step else self.workflow
        return f"{where}: {self.construct} -- {self.reason}"


@dataclass
class ArazzoImport:
    """The workflows, and everything the conversion could not carry."""

    workflows: list[Workflow] = field(default_factory=list)
    #: The `arazzo` field as written. 1.0.x documents are read; the field says
    #: which one this was rather than implying it was 1.1.0.
    version: str = ""
    #: `info.title`, for the caller that wants to say what it read.
    title: str = ""
    #: Source Description names, in document order.
    sources: list[str] = field(default_factory=list)
    #: Constructs with no equivalent here. See `Untranslated`.
    untranslated: list[Untranslated] = field(default_factory=list)
    #: Steps that were dropped entirely, by `workflowId.stepId`. A workflow
    #: missing a step is a different workflow, so this is counted separately
    #: from constructs that were merely narrowed.
    dropped_steps: list[str] = field(default_factory=list)
    #: `stepId`/`workflowId` values that had to change, old -> new.
    renamed: dict[str, str] = field(default_factory=dict)

    @property
    def note(self) -> str:
        """One line for a caller that has to say what it just loaded."""
        return (
            f"Read {len(self.workflows)} workflow(s) from an Arazzo {self.version} "
            f"description ({self.title!r}). {len(self.untranslated)} construct(s) have "
            f"no equivalent in this engine and {len(self.dropped_steps)} step(s) were "
            "dropped. An Arazzo description carries no host allowlist, so the imported "
            "workflow has none: every request goes to the --base-url given at run time."
        )


@dataclass
class ArazzoExport:
    """The description, and everything the manifest said that it does not."""

    document: dict[str, Any] = field(default_factory=dict)
    untranslated: list[Untranslated] = field(default_factory=list)
    renamed: dict[str, str] = field(default_factory=dict)

    def to_yaml(self) -> str:
        return str(yaml.safe_dump(self.document, sort_keys=False, allow_unicode=True))


# --------------------------------------------------------------- expressions


def _pointer_to_jsonpath(pointer: str) -> str | None:
    """`/a/b` -> `$.a.b`, `/a/0` -> `$.a[0]`; None when this engine cannot.

    The engine's JSONPath subset is `$.a.b` with at most one trailing index, so
    a pointer that needs more than that has no manifest form.
    """
    parts = [p.replace("~1", "/").replace("~0", "~") for p in pointer.split("/")[1:]]
    if not parts or any(not p for p in parts):
        return None
    index: str | None = None
    if parts[-1].isdigit():
        index = parts.pop()
    if not parts or any(p.isdigit() or not re.fullmatch(r"[A-Za-z_][\w]*", p) for p in parts):
        return None
    return "$." + ".".join(parts) + (f"[{index}]" if index is not None else "")


def _jsonpath_to_pointer(expression: str) -> str | None:
    """`$.a.b` -> `/a/b`, `$.a[0]` -> `/a/0`; None when it is not the subset."""
    m = re.fullmatch(r"\$\.([A-Za-z_][\w.]*)(?:\[(\d+)\])?", expression.strip())
    if not m:
        return None
    parts = m.group(1).split(".")
    if m.group(2) is not None:
        parts.append(m.group(2))
    return "/" + "/".join(p.replace("~", "~0").replace("/", "~1") for p in parts)


def _variable_for(expression: str) -> str | None:
    """The manifest variable an Arazzo value expression stands for."""
    m = _INPUT_RE.fullmatch(expression) or _STEP_OUTPUT_RE.fullmatch(expression)
    return m.group("name") if m else None


def _literal(value: Any) -> str:
    """A value as a criterion literal: quoted for strings, JSON otherwise."""
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace("'", "\\'")
        return f"'{escaped}'"
    return json.dumps(value)


def _unliteral(text: str) -> tuple[bool, Any]:
    """The inverse of `_literal`. False when the text is neither form."""
    text = text.strip()
    if len(text) >= 2 and text[0] == "'" and text[-1] == "'":
        return True, text[1:-1].replace("\\'", "'").replace("\\\\", "\\")
    try:
        return True, json.loads(text)
    except ValueError:
        return False, None


def _sanitize_id(name: str, renamed: dict[str, str]) -> str:
    """An id matching Arazzo's `[A-Za-z0-9_\\-]+`, recording any change."""
    if _ID_RE.fullmatch(name):
        return name
    new = _ID_BAD.sub("-", name).strip("-") or "step"
    renamed[name] = new
    return new


# -------------------------------------------------------------------- import


def is_arazzo(raw: object) -> bool:
    """Whether a loaded document is an Arazzo description.

    The root `arazzo` field is required and unique to the format, so this is a
    fact about the document rather than a guess from the file name.
    """
    return isinstance(raw, dict) and isinstance(raw.get("arazzo"), str)


def read_arazzo(path: str) -> ArazzoImport:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not is_arazzo(raw):
        raise ValueError(f"{path} has no root 'arazzo' field; it is not an Arazzo description")
    return from_arazzo(raw)


def from_arazzo(document: dict[str, Any]) -> ArazzoImport:
    """Read an Arazzo description into manifest workflows."""
    out = ArazzoImport(
        version=str(document.get("arazzo", "")),
        title=str((document.get("info") or {}).get("title", "")),
        sources=[
            str(s.get("name", ""))
            for s in document.get("sourceDescriptions") or []
            if isinstance(s, dict)
        ],
    )
    for raw in document.get("workflows") or []:
        if isinstance(raw, dict):
            out.workflows.append(_read_workflow(raw, out))
    return out


def _read_workflow(raw: dict[str, Any], out: ArazzoImport) -> Workflow:
    name = str(raw.get("workflowId", "workflow"))
    inputs_schema = raw.get("inputs")
    inputs: list[str] = []
    if isinstance(inputs_schema, dict):
        properties = inputs_schema.get("properties")
        if isinstance(properties, dict):
            inputs = [str(k) for k in properties]
        if inputs_schema.get("$ref") is not None:
            out.untranslated.append(
                Untranslated(
                    name,
                    None,
                    "inputs.$ref",
                    "reusable input schemas live in components and are not resolved here",
                )
            )
    for construct, reason in (
        ("dependsOn", "this engine runs one workflow at a time, in document order"),
        ("successActions", "workflow-level success actions have no equivalent"),
        ("failureActions", "workflow-level failure actions have no equivalent"),
        ("outputs", "a manifest has no workflow-level output block"),
        ("parameters", "workflow-level parameters are not applied to every step here"),
    ):
        if raw.get(construct):
            out.untranslated.append(Untranslated(name, None, construct, reason))

    steps: list[WorkflowStep] = []
    for raw_step in raw.get("steps") or []:
        if not isinstance(raw_step, dict):
            continue
        step = _read_step(raw_step, name, out)
        if step is not None:
            steps.append(step)
    return Workflow(
        name=name,
        description=raw.get("summary") or raw.get("description"),
        inputs=inputs,
        # Deliberately empty: see the module docstring. Arazzo declares no host
        # allowlist and inventing one from a source URL would allowlist the
        # host that serves the specification, not the host that serves the API.
        allowed_hosts=[],
        steps=steps,
    )


def _read_step(raw: dict[str, Any], workflow: str, out: ArazzoImport) -> WorkflowStep | None:
    step_id = str(raw.get("stepId", f"step-{len(out.dropped_steps)}"))
    if raw.get("workflowId"):
        out.dropped_steps.append(f"{workflow}.{step_id}")
        out.untranslated.append(
            Untranslated(
                workflow,
                step_id,
                "workflowId",
                "a step that calls another workflow; this engine does not nest workflows",
            )
        )
        return None
    if raw.get("channelPath") or raw.get("action"):
        out.dropped_steps.append(f"{workflow}.{step_id}")
        out.untranslated.append(
            Untranslated(
                workflow,
                step_id,
                "channelPath",
                "an AsyncAPI publish/subscribe step; this engine sends HTTP requests",
            )
        )
        return None

    method, path = _resolve_operation(raw, workflow, step_id, out)
    if method is None or path is None:
        out.dropped_steps.append(f"{workflow}.{step_id}")
        return None

    request = WorkflowRequest(method=method, path=path)
    _read_parameters(raw, request, workflow, step_id, out)
    _read_body(raw, request, workflow, step_id, out)

    for construct, reason in (
        ("onSuccess", "`goto` and `end` have no equivalent in a straight-line run"),
        ("onFailure", "`retry`, `goto` and `end` have no equivalent in a straight-line run"),
        ("dependsOn", "steps run in document order and nothing waits"),
        ("correlationId", "there is nothing here that correlates asynchronous messages"),
    ):
        if raw.get(construct):
            out.untranslated.append(Untranslated(workflow, step_id, construct, reason))

    timeout = raw.get("timeout")
    return WorkflowStep(
        name=step_id,
        request=request,
        extract=_read_outputs(raw, workflow, step_id, out),
        assert_status=_read_status_criteria(raw),
        assert_jsonpath=_read_body_criteria(raw, workflow, step_id, out),
        # Arazzo `timeout` is milliseconds; `timeout_seconds` is not.
        timeout_seconds=float(timeout) / 1000.0 if isinstance(timeout, int | float) else 30.0,
    )


def _resolve_operation(
    raw: dict[str, Any], workflow: str, step_id: str, out: ArazzoImport
) -> tuple[str | None, str | None]:
    """Method and path, from `operationPath`. `operationId` cannot give them."""
    operation_path = raw.get("operationPath")
    if isinstance(operation_path, str):
        m = _OPERATION_PATH_RE.fullmatch(operation_path)
        if not m:
            out.untranslated.append(
                Untranslated(
                    workflow,
                    step_id,
                    "operationPath",
                    f"{operation_path!r} is not "
                    "`{$sourceDescriptions.<name>.url}#<json-pointer>`, so the method and "
                    "path cannot be read from it",
                )
            )
            return None, None
        parts = [p.replace("~1", "/").replace("~0", "~") for p in m.group("pointer").split("/")[1:]]
        if len(parts) != 3 or parts[0] != "paths":
            out.untranslated.append(
                Untranslated(
                    workflow,
                    step_id,
                    "operationPath",
                    f"the pointer {m.group('pointer')!r} does not name `/paths/<path>/<method>`",
                )
            )
            return None, None
        return parts[2].upper(), parts[1]

    operation_id = raw.get("operationId")
    if isinstance(operation_id, str):
        out.untranslated.append(
            Untranslated(
                workflow,
                step_id,
                "operationId",
                f"{operation_id!r} names an operation in a source description; the method "
                "and path are in that document, which is not read here",
            )
        )
        return None, None
    out.untranslated.append(
        Untranslated(workflow, step_id, "step", "names no operationId, operationPath or workflowId")
    )
    return None, None


def _read_parameters(
    raw: dict[str, Any],
    request: WorkflowRequest,
    workflow: str,
    step_id: str,
    out: ArazzoImport,
) -> None:
    for parameter in raw.get("parameters") or []:
        if not isinstance(parameter, dict):
            continue
        if "reference" in parameter:
            out.untranslated.append(
                Untranslated(
                    workflow,
                    step_id,
                    "parameters.reference",
                    "a reusable parameter from components, which is not resolved here",
                )
            )
            continue
        name = str(parameter.get("name", ""))
        location = str(parameter.get("in", "")) or "query"
        value = parameter.get("value")
        if location not in _SENDABLE_LOCATIONS:
            out.untranslated.append(
                Untranslated(
                    workflow,
                    step_id,
                    f"parameters.in={location}",
                    "a WorkflowRequest has a path, a query and headers, and nothing else",
                )
            )
            continue
        if isinstance(value, dict):
            out.untranslated.append(
                Untranslated(
                    workflow,
                    step_id,
                    f"parameters.{name}.value",
                    "a Selector Object; only literal values and runtime expressions are read",
                )
            )
            continue
        rendered = _render(value)
        if location == "path":
            # The manifest substitutes `{var}` from the variable table, so the
            # placeholder is renamed to whatever the value expression names.
            # `/pets/{petId}` with `value: $steps.create.outputs.pet_id` becomes
            # `/pets/{pet_id}` -- the same request, addressed the way this
            # engine addresses it.
            request.path = request.path.replace("{" + name + "}", rendered)
        elif location == "query":
            request.query[name] = rendered
        else:
            request.headers[name] = str(rendered)


def _render(value: Any) -> Any:
    """An Arazzo parameter or payload value as the manifest writes it."""
    if isinstance(value, str):
        m = _INPUT_RE.fullmatch(value) or _STEP_OUTPUT_RE.fullmatch(value)
        if m:
            return "{" + m.group("name") + "}"
        return _EMBEDDED_RE.sub(
            lambda hit: "{" + (_variable_for(hit.group(1)) or hit.group(1)) + "}", value
        )
    if isinstance(value, dict):
        return {k: _render(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_render(v) for v in value]
    return value


def _read_body(
    raw: dict[str, Any],
    request: WorkflowRequest,
    workflow: str,
    step_id: str,
    out: ArazzoImport,
) -> None:
    body = raw.get("requestBody")
    if not isinstance(body, dict):
        return
    content_type = body.get("contentType")
    if isinstance(content_type, str) and "json" not in content_type:
        out.untranslated.append(
            Untranslated(
                workflow,
                step_id,
                f"requestBody.contentType={content_type}",
                "this engine sends the body as JSON",
            )
        )
        return
    if body.get("replacements"):
        out.untranslated.append(
            Untranslated(
                workflow,
                step_id,
                "requestBody.replacements",
                "targeted payload edits are applied at send time by an Arazzo runtime",
            )
        )
    request.body = _render(body.get("payload"))


def _read_outputs(
    raw: dict[str, Any], workflow: str, step_id: str, out: ArazzoImport
) -> dict[str, str]:
    extract: dict[str, str] = {}
    outputs = raw.get("outputs")
    if not isinstance(outputs, dict):
        return extract
    for name, expression in outputs.items():
        if not isinstance(expression, str):
            out.untranslated.append(
                Untranslated(
                    workflow,
                    step_id,
                    f"outputs.{name}",
                    "a Selector Object; only `$response.body#<pointer>` is read",
                )
            )
            continue
        m = _BODY_REF_RE.fullmatch(expression.strip())
        jsonpath = _pointer_to_jsonpath(m.group("pointer")) if m else None
        if jsonpath is None:
            out.untranslated.append(
                Untranslated(
                    workflow,
                    step_id,
                    f"outputs.{name}",
                    f"{expression!r} is outside this engine's `$.a.b` extraction subset",
                )
            )
            continue
        extract[str(name)] = jsonpath
    return extract


def _read_status_criteria(raw: dict[str, Any]) -> list[int] | None:
    """The statuses an OR chain of `$statusCode == N` names.

    Nothing is reported from here: a criterion that is not a status check is
    read by `_read_body_criteria`, which reports the ones it cannot carry. Two
    passes over the same list would otherwise report each miss twice.
    """
    statuses: list[int] = []
    for criterion in raw.get("successCriteria") or []:
        if not isinstance(criterion, dict) or criterion.get("type") not in (None, "simple"):
            continue
        condition = str(criterion.get("condition", ""))
        parts = [p.strip() for p in condition.split("||")]
        matches = [_STATUS_RE.fullmatch(p) for p in parts]
        if all(matches) and matches:
            statuses.extend(int(m.group(1)) for m in matches if m)
    return sorted(set(statuses)) or None


def _read_body_criteria(
    raw: dict[str, Any], workflow: str, step_id: str, out: ArazzoImport
) -> dict[str, Any]:
    asserts: dict[str, Any] = {}
    for criterion in raw.get("successCriteria") or []:
        if not isinstance(criterion, dict):
            continue
        condition = str(criterion.get("condition", ""))
        kind = criterion.get("type")
        if kind not in (None, "simple"):
            out.untranslated.append(
                Untranslated(
                    workflow,
                    step_id,
                    f"successCriteria.type={kind if isinstance(kind, str) else 'object'}",
                    "this engine compares a status and equality on one extracted value",
                )
            )
            continue
        parts = [p.strip() for p in condition.split("||")]
        if all(_STATUS_RE.fullmatch(p) for p in parts):
            continue  # already read as assert_status
        m = _BODY_EQ_RE.fullmatch(condition.strip())
        jsonpath = _pointer_to_jsonpath(m.group("pointer")) if m else None
        parsed, value = _unliteral(m.group("literal")) if m else (False, None)
        if jsonpath is None or not parsed:
            out.untranslated.append(
                Untranslated(
                    workflow,
                    step_id,
                    "successCriteria",
                    f"{condition!r} is outside `$statusCode == N` and "
                    "`$response.body#<pointer> == <literal>`",
                )
            )
            continue
        if isinstance(value, str) and _EMBEDDED_RE.search(value):
            # The engine substitutes variables into paths, bodies, headers and
            # query values. It does not substitute into an expected value, so
            # importing this would compare the response against the literal
            # text `{$inputs.name}` and fail every time it ran.
            out.untranslated.append(
                Untranslated(
                    workflow,
                    step_id,
                    "successCriteria",
                    f"{condition!r} expects a runtime value; this engine compares against "
                    "a literal and does not substitute variables into an expectation",
                )
            )
            continue
        asserts[jsonpath] = value
    return asserts


# -------------------------------------------------------------------- export


def to_arazzo(
    workflow: Workflow,
    *,
    source_name: str,
    source_url: str,
    source_type: str = "openapi",
    title: str | None = None,
    version: str = "1.0.0",
    service: Service | None = None,
) -> ArazzoExport:
    """Write a manifest as an Arazzo description.

    `service`, when given, is the contract the manifest is run against. It is
    what turns a manifest path into a *declared* path: `/users/{user_id}` is a
    template over this engine's variables, and the source document's path is
    `/users/{userId}` or `/users/{id}` -- whatever the author of the contract
    called it. Without the contract the manifest's own template is written into
    the pointer, which resolves only where the two names happen to agree, and
    that is reported.
    """
    export = ArazzoExport()
    workflow_id = _sanitize_id(workflow.name, export.renamed)
    steps: list[dict[str, Any]] = []
    # Which step produced which variable, so a `{var}` becomes the expression
    # that names its origin rather than a bare string.
    origin: dict[str, str] = {}
    for step in workflow.steps:
        steps.append(_write_step(step, workflow, workflow_id, origin, export, service, source_name))
        for name in step.extract:
            origin[name] = _sanitize_id(step.name, export.renamed)
    if workflow.cleanup:
        export.untranslated.append(
            Untranslated(
                workflow.name,
                None,
                "cleanup",
                "cleanup steps run after a failure and are not conditional in Arazzo; "
                "writing them as ordinary steps would make them run on the success path too",
            )
        )
    if workflow.allowed_hosts or workflow.base_url:
        export.untranslated.append(
            Untranslated(
                workflow.name,
                None,
                "allowed_hosts",
                "Arazzo has no host allowlist and no base URL; a runtime resolves the "
                "server from the source description",
            )
        )
    document: dict[str, Any] = {
        "arazzo": ARAZZO_VERSION,
        "info": {
            "title": title or workflow.name,
            "version": version,
        },
        "sourceDescriptions": [
            {"name": source_name, "url": source_url, "type": source_type},
        ],
        "workflows": [
            {
                "workflowId": workflow_id,
                **({"summary": workflow.description} if workflow.description else {}),
                **({"inputs": _write_inputs(workflow)} if workflow.inputs else {}),
                "steps": steps,
            }
        ],
    }
    export.document = document
    return export


def _write_inputs(workflow: Workflow) -> dict[str, Any]:
    """The manifest's input names as a JSON Schema 2020-12 object.

    Every input becomes a required string, because that is all a manifest
    records: `inputs` is a list of names with no types. Declaring them as
    strings is a narrowing an Arazzo runtime will enforce, so it is stated in
    the export's description rather than left for a reader to discover.
    """
    return {
        "type": "object",
        "properties": {name: {"type": "string"} for name in workflow.inputs},
        "required": list(workflow.inputs),
    }


def _expression(value: str, origin: dict[str, str]) -> str:
    """`{var}` as the Arazzo expression that names where `var` came from."""

    def _one(name: str) -> str:
        if name in origin:
            return f"$steps.{origin[name]}.outputs.{name}"
        return f"$inputs.{name}"

    def _replace(hit: re.Match[str]) -> str:
        return "{" + _one(hit.group(1)) + "}"

    rendered = re.sub(r"\{([A-Za-z_][\w.\-]*)\}", _replace, value)
    # A value that is exactly one placeholder is the expression itself, not a
    # string with one embedded: `{$inputs.x}` is a string, `$inputs.x` is the
    # value, and a parameter that must stay a number needs the second form.
    m = re.fullmatch(r"\{(\$[^{}]+)\}", rendered)
    return m.group(1) if m else rendered


def _deep_expression(value: Any, origin: dict[str, str]) -> Any:
    if isinstance(value, str):
        return _expression(value, origin)
    if isinstance(value, dict):
        return {k: _deep_expression(v, origin) for k, v in value.items()}
    if isinstance(value, list):
        return [_deep_expression(v, origin) for v in value]
    return value


def _declared_path(
    step: WorkflowStep, service: Service | None
) -> tuple[str, dict[str, str]] | None:
    """The contract's own path for this step, and placeholder -> declared name.

    Matched on method and on shape: the segments must line up and a `{...}` in
    one must face a `{...}` in the other. Two different operations cannot share
    a shape *and* a method, so a match is the operation.
    """
    if service is None:
        return None
    ours = step.request.path.split("/")
    for operation in service.operations:
        if (operation.method or "").upper() != step.request.method or not operation.path:
            continue
        theirs = operation.path.split("/")
        if len(theirs) != len(ours):
            continue
        mapping: dict[str, str] = {}
        for mine, other in zip(ours, theirs, strict=True):
            mine_var = mine.startswith("{") and mine.endswith("}")
            other_var = other.startswith("{") and other.endswith("}")
            if mine_var and other_var:
                mapping[mine[1:-1]] = other[1:-1]
            elif mine != other:
                break
        else:
            return operation.path, mapping
    return None


def _write_step(
    step: WorkflowStep,
    workflow: Workflow,
    workflow_id: str,
    origin: dict[str, str],
    export: ArazzoExport,
    service: Service | None,
    source_name: str,
) -> dict[str, Any]:
    step_id = _sanitize_id(step.name, export.renamed)
    declared = _declared_path(step, service)
    path = declared[0] if declared else step.request.path
    names = declared[1] if declared else {}
    if declared is None and "{" in step.request.path:
        export.untranslated.append(
            Untranslated(
                workflow.name,
                step.name,
                "request.path",
                f"{step.request.path!r} is a template over this engine's variables. No "
                "contract was supplied, so it is written into the pointer as-is; it "
                "resolves only where the variable name equals the declared parameter name",
            )
        )
    pointer = "/paths/" + path.replace("~", "~0").replace("/", "~1")
    out: dict[str, Any] = {
        "stepId": step_id,
        "operationPath": (
            "{$sourceDescriptions." + source_name + ".url}#" + pointer + "/" + _method(step)
        ),
    }

    parameters: list[dict[str, Any]] = []
    for segment in re.findall(r"\{([^{}]+)\}", step.request.path):
        parameters.append(
            {
                "name": names.get(segment, segment),
                "in": "path",
                "value": _expression("{" + segment + "}", origin),
            }
        )
    for key, value in step.request.query.items():
        parameters.append({"name": key, "in": "query", "value": _deep_expression(value, origin)})
    for key, value in step.request.headers.items():
        parameters.append({"name": key, "in": "header", "value": _deep_expression(value, origin)})
    for parameter in parameters:
        if isinstance(parameter["value"], dict):
            # A Parameter Object's `value` admits string, boolean, array,
            # number and null -- not an object.
            export.untranslated.append(
                Untranslated(
                    workflow.name,
                    step.name,
                    f"parameter {parameter['name']}",
                    "its value is an object, which an Arazzo Parameter Object cannot hold",
                )
            )
    parameters = [p for p in parameters if not isinstance(p["value"], dict)]
    if parameters:
        out["parameters"] = parameters

    if step.request.body is not None:
        out["requestBody"] = {
            "contentType": "application/json",
            "payload": _deep_expression(step.request.body, origin),
        }

    criteria: list[dict[str, Any]] = []
    if step.assert_status:
        criteria.append(
            {"condition": " || ".join(f"$statusCode == {s}" for s in step.assert_status)}
        )
    for expression, expected in step.assert_jsonpath.items():
        pointer_form = _jsonpath_to_pointer(expression)
        if pointer_form is None:
            export.untranslated.append(
                Untranslated(
                    workflow.name,
                    step.name,
                    f"assert_jsonpath {expression}",
                    "outside the `$.a.b` subset, so it has no JSON Pointer form",
                )
            )
            continue
        criteria.append({"condition": f"$response.body#{pointer_form} == {_literal(expected)}"})
    if criteria:
        out["successCriteria"] = criteria

    outputs: dict[str, str] = {}
    for name, expression in step.extract.items():
        pointer_form = _jsonpath_to_pointer(expression)
        if pointer_form is None:
            export.untranslated.append(
                Untranslated(
                    workflow.name,
                    step.name,
                    f"extract {name}",
                    f"{expression!r} is outside the `$.a.b` subset, so it has no JSON Pointer form",
                )
            )
            continue
        outputs[name] = f"$response.body#{pointer_form}"
    if outputs:
        out["outputs"] = outputs

    if step.timeout_seconds:
        out["timeout"] = int(step.timeout_seconds * 1000)
    return out


def _method(step: WorkflowStep) -> str:
    return step.request.method.lower()
