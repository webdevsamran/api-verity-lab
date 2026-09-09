"""The published `protocol` enum must list every protocol the code can emit.

`schemas/result-v1.schema.json` constrained `protocol` to
`openapi | graphql | grpc` while `apiverity.core.model.Protocol` had six
members and `AsyncApiSpecPlugin` had been shipping for months. So
`apiverity validate events.yaml --json` emitted `"protocol": "asyncapi"` --
an artifact that violated the project's own published schema, from a supported
format, on the happy path.

Nothing caught it because `scripts/validate_result_artifacts.py` only ran
`validate` against an OpenAPI fixture. The schema step was green because the
one command that writes this field was never pointed at anything but the
protocol the enum already allowed.

Two tests, because the failure has two halves. The first binds the enum to the
source of truth so a new `Protocol` member cannot be added without extending
the schema. The second is the inverse -- an enum value with no `Protocol`
behind it is a promise the code cannot keep -- and together they make the two
lists impossible to drift apart in either direction.
"""

from __future__ import annotations

import json
from pathlib import Path

from apiverity.core.model import Protocol

_ROOT = Path(__file__).resolve().parent.parent.parent
_SCHEMA = _ROOT / "schemas" / "result-v1.schema.json"


def _schema_protocols() -> set[str]:
    schema = json.loads(_SCHEMA.read_text(encoding="utf-8"))
    return set(schema["properties"]["protocol"]["enum"])


def test_every_protocol_the_model_defines_is_allowed_by_the_schema() -> None:
    missing = {p.value for p in Protocol} - _schema_protocols()
    assert not missing, (
        f"Protocol member(s) {sorted(missing)} are not in the result-v1 `protocol` enum. "
        "A command that loads a contract in that format will emit an artifact this "
        "schema rejects. Add them to schemas/result-v1.schema.json -- the enum is "
        "additive, so extending it breaks no existing artifact."
    )


def test_the_schema_promises_no_protocol_the_model_cannot_produce() -> None:
    invented = _schema_protocols() - {p.value for p in Protocol}
    assert not invented, (
        f"result-v1 allows protocol value(s) {sorted(invented)} that no Protocol member "
        "produces. A consumer branching on them is writing dead code."
    )
