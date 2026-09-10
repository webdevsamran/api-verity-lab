"""Naming the format, for the documents content sniffing gets wrong.

Detection here is substring matching: `openapi:` makes a document OpenAPI,
`type Query` makes it GraphQL, a `service` declaration makes it gRPC. That is a
reasonable default and it has no escape hatch, so a document that merely
*mentions* the wrong word is unloadable by any means -- and it does not fail as
"could not detect", it fails as a parse error about a format nobody asked for,
which is a bad error message on top of a wrong answer.

The cases below are not hypothetical shapes: a GraphQL schema whose comment
discusses the OpenAPI gateway in front of it, and an MCP manifest whose tool
description mentions a service, are both ordinary documents.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from apiverity.core.model import Protocol
from apiverity.specs.loader import (
    SPEC_FORMATS,
    UnknownSpecFormatError,
    _builtin_plugins,
    _by_format,
    detect_and_load,
)


def _write(tmp_path: Path, name: str, content: str) -> str:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return str(path)


# ---------------------------------------------------------- the registry


def test_every_builtin_format_is_addressable_by_name() -> None:
    """A name in the CLI's `choices` that resolves to no plugin is a flag that
    fails at the point of use, having advertised itself as valid."""
    plugins = _builtin_plugins()
    unresolved = [name for name in SPEC_FORMATS if _by_format(plugins, name) is None]
    assert unresolved == []


def test_the_two_formats_that_share_a_protocol_are_separately_addressable() -> None:
    """OpenAPI and Swagger 2.0 are both `Protocol.OPENAPI`.

    Keying the override on protocol would make one of them unnameable, and it
    is exactly the pair a caller needs to disambiguate.
    """
    plugins = _builtin_plugins()
    openapi = _by_format(plugins, "openapi")
    swagger = _by_format(plugins, "swagger2")
    assert openapi is not None and swagger is not None
    assert openapi is not swagger
    assert openapi.protocol() == swagger.protocol() == Protocol.OPENAPI


def test_an_unknown_format_says_what_is_known() -> None:
    with pytest.raises(UnknownSpecFormatError) as caught:
        detect_and_load("whatever.yaml", spec_format="yaml")
    assert "openapi" in str(caught.value)


# ------------------------------------------------- the misdetection it fixes


_MINIMAL_OPENAPI = """openapi: 3.1.0
info:
  title: T
  version: '1'
"""


_SDL_MENTIONING_OPENAPI = """
# This schema is served behind the openapi: gateway described in ops/README.
type Query {
  user(id: ID!): User
}

type User {
  id: ID!
  email: String!
}
"""


def test_a_graphql_schema_that_mentions_openapi_is_misdetected(tmp_path: Path) -> None:
    """The failure the flag exists for, demonstrated before it is fixed.

    Asserted rather than described, because a flag justified by a problem
    nobody reproduced is a flag that may be solving nothing.
    """
    source = _write(tmp_path, "schema.graphql", _SDL_MENTIONING_OPENAPI)
    with pytest.raises(Exception) as caught:
        detect_and_load(source)
    assert not isinstance(caught.value, UnknownSpecFormatError)


def test_naming_the_format_loads_it(tmp_path: Path) -> None:
    source = _write(tmp_path, "schema.graphql", _SDL_MENTIONING_OPENAPI)
    service, _findings, plugin = detect_and_load(source, spec_format="graphql")
    assert plugin.protocol() == Protocol.GRAPHQL
    assert service.operations, "the schema loaded as GraphQL, with its operations"


def test_the_override_does_not_fall_through_to_another_plugin(tmp_path: Path) -> None:
    """Skipping detection, not reordering it.

    An override that only moved a plugin to the front would still fall through
    when that plugin declined -- which is the misdetection the caller is
    overriding, reached a second time and now silently. Naming a format that
    cannot read the document has to fail *as that format*, so the error names
    something the caller can act on.
    """
    source = _write(tmp_path, "spec.yaml", _MINIMAL_OPENAPI)
    _service, findings, plugin = detect_and_load(source, spec_format="grpc")
    assert plugin.protocol() == Protocol.GRPC
    assert "PROTO-PARSE-EMPTY" in {f.rule_id for f in findings}, (
        "the failure has to come from the parser that was named"
    )


def test_an_override_that_contradicts_detection_says_so(tmp_path: Path) -> None:
    """Honoured, and reported.

    The caller may know something the sniffer does not, so the override wins.
    The other explanation is a typo in the flag, and a silent load as the wrong
    format is the harder of the two to notice.
    """
    source = _write(tmp_path, "spec.yaml", _MINIMAL_OPENAPI)
    _service, findings, _plugin = detect_and_load(source, spec_format="grpc")
    override = [f for f in findings if f.rule_id == "SPEC-FORMAT-OVERRIDDEN"]
    assert len(override) == 1
    assert override[0].severity.value == "WARN"


def test_an_override_that_agrees_with_detection_is_silent(tmp_path: Path) -> None:
    """A warning on every correct use is a warning people learn to ignore."""
    source = _write(
        tmp_path,
        "spec.json",
        json.dumps({"openapi": "3.1.0", "info": {"title": "T", "version": "1.0.0"}, "paths": {}}),
    )
    _service, findings, _plugin = detect_and_load(source, spec_format="openapi")
    assert "SPEC-FORMAT-OVERRIDDEN" not in {f.rule_id for f in findings}


def test_detection_still_runs_when_no_format_is_named(tmp_path: Path) -> None:
    source = _write(
        tmp_path,
        "spec.json",
        json.dumps({"openapi": "3.1.0", "info": {"title": "T", "version": "1.0.0"}, "paths": {}}),
    )
    _service, _findings, plugin = detect_and_load(source)
    assert plugin.protocol() == Protocol.OPENAPI
