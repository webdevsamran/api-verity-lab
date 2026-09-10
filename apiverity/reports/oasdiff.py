"""Findings in oasdiff's shape, so switching does not mean rewriting CI.

Migration cost is the real competitor. A team already gating on oasdiff has
`jq` filters, ignore-lists and dashboards keyed on its output; asking them to
rewrite all of that to try something else is asking for more than a trial is
worth. This writes the same shape.

## What was checked, and when

Verified 2026-09-10 against `oasdiff/oasdiff` at `main` — release **v1.31.0**,
published 2026-09-05, Apache-2.0.

`formatters/changes.go` defines the object `--format json` emits, with these
tags:

    id, text, comment, disclaimers, level, operation, operationId, path,
    section, attributes, baseSource, revisionSource, fingerprint

all `omitempty` except `level`. `checker/source.go` defines `baseSource` and
`revisionSource` as `{file, line, column, endLine, endColumn}`, also all
`omitempty`. `checker/rules/level.go` declares `type Level int` with
`ERR = 3, WARN = 2, INFO = 1, NONE = 0, INVALID = -1` and **no** `MarshalJSON`,
so the field is a *number* in JSON, not the string its `String()` method
returns. That last detail is the one a from-memory implementation gets wrong.

## What this deliberately does not emit

**`fingerprint`.** oasdiff computes it over its own change identity. A value
computed differently would look like a fingerprint, compare unequal to the real
one, and break exactly the ignore-lists this export exists to preserve —
silently. Omitted, which the field's `omitempty` permits.

**`attributes`, `section`, `disclaimers`.** No equivalent here. An empty string
is not the same as an absent value in a format where every one of these is
`omitempty`.

**An oasdiff `id` for a rule that has no exact counterpart.** The mapping below
is exact matches only. Where our rule is broader than any of theirs — our
`BRK-ENUM-NARROWED-REQUEST` covers both a parameter and a body property, and
oasdiff has a separate id for each — picking one would assert something this
tool never determined. Those come out as `x-apiverity-<rule id>`, which cannot
collide with an oasdiff id and can be grepped for.

**Anything but OpenAPI, in oasdiff's vocabulary.** oasdiff reads OpenAPI. A
removed gRPC RPC really is "an endpoint was removed", but emitting
`api-removed-without-deprecation` for one would make a consumer's tooling
report an OpenAPI endpoint removal that never happened. Every finding from a
non-OpenAPI contract is namespaced, whatever its rule.
"""

from __future__ import annotations

import json
from typing import Any

#: oasdiff's numeric levels, from `checker/rules/level.go`. Not the strings its
#: `String()` returns -- `Level` is a plain `int` with no `MarshalJSON`, so the
#: JSON carries the number.
LEVELS = {"ERROR": 3, "WARN": 2, "INFO": 1}

#: The protocol whose vocabulary oasdiff speaks.
NATIVE_PROTOCOL = "openapi"

#: Prefix for a finding with no exact oasdiff counterpart. Deliberately not a
#: plausible-looking oasdiff id: a consumer filtering on their vocabulary
#: should see this as foreign rather than as a check they have not heard of.
FOREIGN_PREFIX = "x-apiverity-"

#: Our rule -> the oasdiff check that means the same thing. Exact matches only;
#: see the module docstring for what is left out and why.
#:
#: Ids taken from `checker/localizations_src/en/messages.yaml` at
#: oasdiff v1.31.0.
MAPPING: dict[str, str] = {
    "BRK-OP-REMOVED": "api-removed-without-deprecation",
    "BRK-RPC-REMOVED": "api-removed-without-deprecation",
    "BRK-OP-ADDED": "endpoint-added",
    "BRK-RPC-ADDED": "endpoint-added",
    "BRK-DEPRECATION-ADDED": "endpoint-deprecated",
    "BRK-PARAM-REMOVED": "request-parameter-removed",
    "BRK-PARAM-ADDED-REQUIRED": "new-required-request-parameter",
    "BRK-PARAM-ADDED-OPTIONAL": "new-optional-request-parameter",
    "BRK-PARAM-REQUIRED": "request-parameter-became-required",
    "BRK-PARAM-OPTIONALIZED": "request-parameter-became-optional",
    "BRK-PARAM-TYPE-CHANGED": "request-parameter-type-changed",
    "BRK-REQ-FIELD-ADDED-REQUIRED": "new-required-request-property",
    "BRK-REQ-FIELD-ADDED-OPTIONAL": "new-optional-request-property",
    "BRK-REQ-FIELD-BECAME-REQUIRED": "request-property-became-required",
    "BRK-REQ-BODY-ADDED-REQUIRED": "request-body-added-required",
    "BRK-REQ-BODY-ADDED-OPTIONAL": "request-body-added-optional",
    "BRK-REQ-BODY-REQUIRED": "request-body-became-required",
    "BRK-RESP-FIELD-REMOVED": "response-required-property-removed",
    "BRK-RESP-FIELD-OPTIONALIZED": "response-property-became-optional",
    "BRK-RESP-TYPE-CHANGED": "response-property-type-changed",
    "BRK-HEADER-ADDED": "response-header-added",
    "BRK-MEDIA-TYPE-CHANGED": "response-media-type-name-changed",
}

#: Two of our rules split on the status code, which oasdiff splits into
#: separate check ids. Resolved from the finding rather than guessed.
STATUS_MAPPING = {
    "BRK-RESP-STATUS-REMOVED": (
        "response-success-status-removed",
        "response-non-success-status-removed",
    ),
    "BRK-RESP-STATUS-ADDED": ("response-success-status-added", "response-non-success-status-added"),
}

#: Rules with no exact counterpart, and the reason, so the gap is a decision
#: somebody can argue with rather than an omission. Only the ones where an
#: oasdiff check *nearly* fits are listed -- a protobuf field number has no
#: near miss.
NO_EXACT_MATCH: dict[str, str] = {
    "BRK-ENUM-NARROWED-REQUEST": (
        "oasdiff separates request-parameter-enum-value-removed from "
        "request-property-enum-value-removed; this rule covers both and does not record "
        "which"
    ),
    "BRK-ENUM-NARROWED-RESPONSE": (
        "oasdiff's nearest is response-mediatype-enum-value-removed, which is about the "
        "media type's enum rather than a property's"
    ),
    "BRK-HEADER-REMOVED": (
        "oasdiff separates required-response-header-removed from "
        "optional-response-header-removed; response header requiredness is not modelled here"
    ),
    "BRK-RESP-FIELD-ADDED": (
        "oasdiff's response-required-property-added asserts the new field is required, "
        "which this rule does not determine"
    ),
    "BRK-RESP-FIELD-GUARANTEED": (
        "oasdiff has response-property-became-optional and no counterpart for the "
        "opposite direction"
    ),
    "BRK-CONSTRAINT-TIGHTENED": (
        "oasdiff has a separate id per constraint and direction "
        "(request-parameter-max-decreased, -max-length-decreased, ...); this rule names "
        "the constraint in its message rather than in its id"
    ),
    "BRK-CONSTRAINT-LOOSENED": "the same, in the other direction",
    "BRK-SECURITY-CHANGED": (
        "oasdiff splits api-security-added, -removed, -updated and the scope variants; "
        "this rule does not record which"
    ),
}


def _source(location: Any) -> dict[str, Any] | None:
    """A `checker.Source`, or nothing.

    Every field is `omitempty` there, and a zero line is genuinely unknown
    rather than line zero -- so an unknown position produces an object with a
    file and no coordinates, and no position at all produces no object.
    """
    if not isinstance(location, dict):
        return None
    file = str(location.get("file") or "")
    if not file:
        return None
    source: dict[str, Any] = {"file": file}
    line = int(location.get("line") or 0)
    column = int(location.get("column") or 0)
    if line:
        source["line"] = line
    if column:
        source["column"] = column
    return source


def _split_operation(operation_key: Any) -> tuple[str, str]:
    """`"GET /users"` -> `("GET", "/users")`.

    An operation key that is not method-and-path -- a gRPC `Service.Method`, an
    MCP `tool search` -- yields no method and no path. oasdiff's fields are
    `omitempty`, so absent is expressible and a fabricated `"GET"` is not
    necessary.
    """
    if not operation_key or not isinstance(operation_key, str):
        return "", ""
    parts = operation_key.split(" ", 1)
    if len(parts) == 2 and parts[0].isupper() and parts[1].startswith("/"):
        return parts[0], parts[1]
    return "", ""


def oasdiff_id(finding: dict[str, Any], *, native: bool) -> str:
    """The id to emit, and whether it is theirs or ours.

    `native` is false for any protocol oasdiff does not read. A removed gRPC
    RPC really is an endpoint removal, and saying so in oasdiff's vocabulary
    would make a consumer's tooling report an OpenAPI removal that never
    happened.
    """
    rule_id = str(finding.get("rule_id") or "")
    if not native:
        return FOREIGN_PREFIX + rule_id.lower()
    if rule_id in STATUS_MAPPING:
        success, other = STATUS_MAPPING[rule_id]
        # The status the finding is about, taken from its own message rather
        # than assumed: "response status '404' was removed".
        return success if "'2" in str(finding.get("message") or "") else other
    mapped = MAPPING.get(rule_id)
    return mapped if mapped else FOREIGN_PREFIX + rule_id.lower()


def to_change(finding: dict[str, Any], *, native: bool) -> dict[str, Any]:
    """One finding as one oasdiff `formatters.Change`.

    Takes a plain dict, like every renderer in `apiverity.reports.renderers`:
    the input is an already-serialised artifact, and reconstructing model
    objects from it to serialise them again would be two conversions where the
    second can disagree with the first.
    """
    operation, path = _split_operation(finding.get("operation_key"))
    change: dict[str, Any] = {
        "id": oasdiff_id(finding, native=native),
        "level": LEVELS.get(str(finding.get("severity") or "").upper(), 0),
    }
    message = str(finding.get("message") or "")
    if message:
        change["text"] = message
    hint = str(finding.get("hint") or "")
    if hint:
        change["comment"] = hint
    if operation:
        change["operation"] = operation
    if path:
        change["path"] = path
    base = _source(finding.get("location"))
    if base:
        change["baseSource"] = base
    revision = _source(finding.get("new_location"))
    if revision:
        change["revisionSource"] = revision
    return change


def export(data: dict[str, Any]) -> list[dict[str, Any]]:
    """A result artifact as an oasdiff changelog array.

    A bare JSON array, because that is what `oasdiff breaking -f json` writes:
    wrapping it in an envelope would mean every existing `jq` expression needs
    a `.changes` in front of it, which is the migration cost this exists to
    remove.

    Ordered the way oasdiff orders: most severe first, then path, then
    operation, then id (`checker/changes.go`, `CompareChanges`).
    """
    findings = data.get("findings")
    if not isinstance(findings, list):
        findings = []
    # `validate` writes `protocol`; the diff commands write `protocol_version`.
    protocol = str(data.get("protocol") or data.get("protocol_version") or "")
    native = protocol == NATIVE_PROTOCOL
    changes = [
        to_change(finding, native=native) for finding in findings if isinstance(finding, dict)
    ]
    return sorted(
        changes,
        key=lambda c: (
            -int(c.get("level", 0)),
            str(c.get("path", "")),
            str(c.get("operation", "")),
            str(c.get("id", "")),
        ),
    )


def render(data: dict[str, Any]) -> str:
    """The renderer `apiverity report --format oasdiff` dispatches to."""
    return json.dumps(export(data), indent=2)


def coverage() -> dict[str, Any]:
    """What maps, what does not, and why -- for `--explain`.

    A migration aid whose coverage nobody can see is one nobody can trust: the
    question a team switching actually has is "which of my filters will stop
    matching", and this answers it without them running the tool twice.
    """
    return {
        "oasdiff_version_checked": "v1.31.0",
        "checked_on": "2026-09-10",
        "mapped": dict(sorted(MAPPING.items())),
        "mapped_by_status": {
            rule: {"2xx": success, "other": other}
            for rule, (success, other) in sorted(STATUS_MAPPING.items())
        },
        "no_exact_match": dict(sorted(NO_EXACT_MATCH.items())),
        "foreign_prefix": FOREIGN_PREFIX,
        "omitted_fields": {
            "fingerprint": (
                "oasdiff hashes its own change identity; a value computed differently "
                "would compare unequal to theirs and break the ignore-lists this export "
                "exists to preserve"
            ),
            "attributes, section, disclaimers": "no equivalent here",
        },
    }


__all__ = [
    "FOREIGN_PREFIX",
    "LEVELS",
    "MAPPING",
    "NATIVE_PROTOCOL",
    "NO_EXACT_MATCH",
    "STATUS_MAPPING",
    "coverage",
    "export",
    "oasdiff_id",
    "render",
    "to_change",
]
