"""Draft workflow manifests from what a spec states outright (#20).

The tempting version of this feature guesses. It sees `POST /users` and
`DELETE /users/{id}`, notices the shapes line up, and offers you a lifecycle
workflow. That is also how a tool ends up handing someone a manifest that
deletes rows in an environment they did not expect, because the guess was
about naming conventions and the consequence was not.

So this reads exactly one thing: the `links` objects in the spec. A link is
the author saying "after this response you can call that operation, and here
is where its parameters come from". It is a statement, not an inference, and
it is the only relationship in OpenAPI that is.

Two consequences follow, and both are deliberate:

- **Every step is emitted commented out.** The output is a draft to read, not
  a manifest to run. Uncommenting is the human's acknowledgement that they
  looked at what it will do.
- **Destructive steps are commented out twice**, under a banner naming the
  method and what it will act on. A single `sed` that uncomments the file will
  not uncomment those; you have to reach for them individually.

`capability-status.md` described this as "PARTIAL (safe deterministic
subset)". There was no inference of any kind -- no `links` in the model, no
parser support, nothing to call. The claim is now true.
"""

from __future__ import annotations

import re

from apiverity.core.model import Link, Operation, Service

__all__ = ["DESTRUCTIVE_METHODS", "InferredWorkflow", "infer_workflows", "render_manifest"]

#: Methods whose steps never come out ready to run. HEAD and GET are absent
#: because they cannot change anything; POST is present because a link chain
#: ending in one can create rows in whatever it is pointed at.
DESTRUCTIVE_METHODS = frozenset({"DELETE", "PUT", "PATCH", "POST"})

#: Runtime expressions defined by the specification. Anything else is left
#: verbatim in the draft with a note, rather than translated by guesswork.
_RESPONSE_BODY = re.compile(r"^\$response\.body#(?P<pointer>/.*)$")
_RESPONSE_HEADER = re.compile(r"^\$response\.header\.(?P<name>.+)$")
_REQUEST_PATH = re.compile(r"^\$request\.path\.(?P<name>.+)$")
_REQUEST_QUERY = re.compile(r"^\$request\.query\.(?P<name>.+)$")


class InferredWorkflow:
    """A draft chain: a source operation and the links it declares."""

    def __init__(self, source: Operation, steps: list[tuple[Link, Operation | None]]) -> None:
        self.source = source
        self.steps = steps

    @property
    def name(self) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", f"{self.source.key}".lower()).strip("-")
        return f"inferred-{slug}"

    @property
    def unresolved(self) -> list[Link]:
        return [link for link, op in self.steps if op is None]

    @property
    def destructive(self) -> list[Operation]:
        return [
            op
            for _, op in self.steps
            if op is not None and (op.method or "").upper() in DESTRUCTIVE_METHODS
        ]


# ------------------------------------------------------------------ resolving


def _by_operation_id(service: Service) -> dict[str, Operation]:
    return {op.operation_id: op for op in service.operations if op.operation_id}


def _by_path_and_method(service: Service) -> dict[tuple[str, str], Operation]:
    return {
        (op.path or "", (op.method or "").upper()): op
        for op in service.operations
        if op.path and op.method
    }


def _resolve(link: Link, service: Service) -> Operation | None:
    """Find the operation a link points at.

    `operationRef` is a JSON pointer into the document. Only the local form is
    resolved -- an external `operationRef` names an operation in a file this
    run never read, and a draft step for it would be a step nobody can check.
    """
    if link.operation_id:
        return _by_operation_id(service).get(link.operation_id)
    if not link.operation_ref:
        return None
    ref = link.operation_ref
    if not ref.startswith("#/"):
        return None
    parts = ref[2:].split("/")
    if len(parts) < 3 or parts[0] != "paths":
        return None
    path = parts[1].replace("~1", "/").replace("~0", "~")
    method = parts[2].upper()
    return _by_path_and_method(service).get((path, method))


def _extraction_for(expression: str) -> tuple[str | None, str]:
    """Translate a runtime expression into (jsonpath, explanation).

    Returns `None` for the path when the expression is one the workflow engine
    cannot express. Emitting a plausible-looking jsonpath for a header
    reference would produce a draft that runs and quietly extracts nothing.
    """
    body = _RESPONSE_BODY.match(expression)
    if body:
        pointer = body.group("pointer")
        segments = [seg.replace("~1", "/").replace("~0", "~") for seg in pointer.split("/") if seg]
        return "$." + ".".join(segments) if segments else "$", ""
    header = _RESPONSE_HEADER.match(expression)
    if header:
        return None, f"reads response header '{header.group('name')}' -- extract it by hand"
    for pattern, kind in ((_REQUEST_PATH, "path"), (_REQUEST_QUERY, "query")):
        match = pattern.match(expression)
        if match:
            return None, (
                f"reuses the {kind} parameter '{match.group('name')}' from the "
                f"request that produced this response -- supply it as an input"
            )
    return None, f"unrecognised runtime expression {expression!r} -- resolve by hand"


# ------------------------------------------------------------------ inference


def infer_workflows(service: Service) -> list[InferredWorkflow]:
    """One draft per operation that declares links, in a stable order."""
    drafts: list[InferredWorkflow] = []
    for op in service.operations:
        steps: list[tuple[Link, Operation | None]] = []
        for response in op.responses:
            for link in response.links:
                steps.append((link, _resolve(link, service)))
        if steps:
            drafts.append(InferredWorkflow(op, steps))
    return drafts


# ------------------------------------------------------------------ rendering


def _comment(lines: list[str], text: str = "", *, prefix: str = "# ") -> None:
    lines.append(f"{prefix}{text}".rstrip())


def _example_status(op: Operation) -> int:
    for response in op.responses:
        if response.status.isdigit() and response.status.startswith("2"):
            return int(response.status)
    return 200


def render_manifest(service: Service, drafts: list[InferredWorkflow]) -> str:
    """Render drafts as a commented-out YAML manifest.

    Deliberately produced as text rather than dumped from a model: the value
    of the output is in the commentary -- which step is destructive, which
    variable could not be resolved, why a link was skipped -- and a YAML
    serialiser would drop all of it.
    """
    lines: list[str] = []
    _comment(lines, f"Draft workflow manifest inferred from {service.title} {service.version}.")
    _comment(lines)
    _comment(lines, "Inferred ONLY from the `links` objects the specification declares.")
    _comment(lines, "No step was guessed from a path shape or a naming convention.")
    _comment(lines)
    _comment(lines, "Every step below is commented out. Read it, then uncomment the")
    _comment(lines, "steps you want. Destructive steps are commented twice on purpose:")
    _comment(lines, "uncommenting the file wholesale will not enable them.")
    lines.append("")

    if not drafts:
        _comment(lines, "No `links` objects were found in this specification, so there is")
        _comment(lines, "nothing to infer. That is not a defect in the spec -- links are")
        _comment(lines, "optional -- but it does mean a workflow has to be written by hand.")
        lines.append("")
        _comment(lines, "See docs/workflow-authoring.md, or start from a built-in template:")
        _comment(lines, "  apiverity workflow --list-templates")
        return "\n".join(lines) + "\n"

    for draft in drafts:
        source = draft.source
        lines.append(f"# --- {source.key} " + "-" * max(0, 60 - len(source.key)))
        _comment(lines, f"name: {draft.name}")
        if source.summary:
            _comment(lines, f"description: {source.summary}")
        _comment(lines, "allowed_hosts: []   # <- required before this can run")
        _comment(lines, "steps:")
        _comment(lines, f"  - name: {source.operation_id or 'source'}")
        _comment(lines, "    request:")
        _comment(lines, f"      method: {source.method}")
        _comment(lines, f'      path: "{source.path}"')
        _comment(lines, f"    assert: {{status: {_example_status(source)}}}")

        for link, target in draft.steps:
            lines.append("#")
            if target is None:
                ref = link.operation_id or link.operation_ref or "?"
                _comment(lines, f"  # link '{link.name}' -> {ref}")
                _comment(
                    lines,
                    "  # SKIPPED: this link points at an operation that is not in this document.",
                )
                continue

            method = (target.method or "GET").upper()
            deadly = method in DESTRUCTIVE_METHODS
            prefix = "# # " if deadly else "# "
            if deadly:
                _comment(lines, "  " + "!" * 58)
                _comment(lines, f"  !! {method} {target.path}")
                _comment(
                    lines,
                    f"  !! This step will {'delete' if method == 'DELETE' else 'modify'} "
                    "data. It is commented",
                )
                _comment(lines, "  !! twice; uncomment it deliberately, and only after you")
                _comment(lines, "  !! know what `allowed_hosts` points at.")
                _comment(lines, "  " + "!" * 58)

            _comment(lines, f"  - name: {link.name}", prefix=prefix)
            _comment(lines, "    request:", prefix=prefix)
            _comment(lines, f"      method: {method}", prefix=prefix)

            path = target.path or ""
            notes: list[str] = []
            extract: dict[str, str] = {}
            for parameter, expression in sorted(link.parameters.items()):
                jsonpath, note = _extraction_for(expression)
                if jsonpath:
                    extract[parameter] = jsonpath
                else:
                    notes.append(f"{parameter}: {note}")
            _comment(lines, f'      path: "{path}"', prefix=prefix)
            _comment(lines, f"    assert: {{status: {_example_status(target)}}}", prefix=prefix)
            if extract:
                rendered = ", ".join(f'{k}: "{v}"' for k, v in sorted(extract.items()))
                _comment(lines, "    # extracted from the step above:", prefix=prefix)
                _comment(lines, f"    extract: {{{rendered}}}", prefix=prefix)
            for note in notes:
                _comment(lines, f"    # UNRESOLVED {note}", prefix=prefix)
        lines.append("")

    resolved = sum(1 for d in drafts for _, op in d.steps if op is not None)
    skipped = sum(len(d.unresolved) for d in drafts)
    destructive = sum(len(d.destructive) for d in drafts)
    _comment(lines, "-" * 62)
    _comment(
        lines,
        f"{len(drafts)} draft(s), {resolved} linked step(s) resolved, "
        f"{skipped} skipped, {destructive} destructive.",
    )
    return "\n".join(lines) + "\n"
