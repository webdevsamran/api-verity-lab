"""AsyncAPI 2.x/3.x adapter and direction normalization (#18).

The adapter handled 2.x only, stored the document's own word for direction,
and keyed event operations by message name alone. Each of those three is
tested here against a concrete consequence rather than against the shape of
the code.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from apiverity.core.model import OperationKind
from apiverity.diff.engine import diff_services
from apiverity.rules.breaking import evaluate_breaking
from apiverity.specs.asyncapi import DIRECTION, AsyncApiSpecPlugin
from apiverity.specs.loader import detect_and_load

_V2 = """\
asyncapi: "2.6.0"
info: { title: Events, version: "1.0.0" }
channels:
  user/created:
    subscribe:
      operationId: onUserCreated
      message:
        name: UserCreated
        payload:
          type: object
          required: [id, email]
          properties:
            id: { type: string }
            email: { type: string }
  user/delete-request:
    publish:
      operationId: deleteUser
      message:
        name: DeleteUser
        payload:
          type: object
          required: [id]
          properties:
            id: { type: string }
"""

_V3 = """\
asyncapi: "3.0.0"
info: { title: Events, version: "1.0.0" }
channels:
  userCreated:
    address: user/created
    messages:
      UserCreated:
        name: UserCreated
        payload:
          type: object
          required: [id, email]
          properties:
            id: { type: string }
            email: { type: string }
  userDeleteRequest:
    address: user/delete-request
    messages:
      DeleteUser:
        name: DeleteUser
        payload:
          type: object
          required: [id]
          properties:
            id: { type: string }
operations:
  onUserCreated:
    action: send
    channel: { $ref: '#/channels/userCreated' }
  deleteUser:
    action: receive
    channel: { $ref: '#/channels/userDeleteRequest' }
"""


def _load(tmp_path: Path, text: str, name: str):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    service, _, _ = detect_and_load(str(path))
    return service


@pytest.fixture
def v2(tmp_path: Path):
    return _load(tmp_path, _V2, "v2.yaml")


@pytest.fixture
def v3(tmp_path: Path):
    return _load(tmp_path, _V3, "v3.yaml")


# -------------------------------------------------------------------- parsing


def test_asyncapi_3_is_detected_and_parsed(v3) -> None:
    assert len(v3.operations) == 2
    assert {op.kind for op in v3.operations} == {OperationKind.EVENT}
    assert {op.channel for op in v3.operations} == {"user/created", "user/delete-request"}


def test_a_v3_channel_address_wins_over_its_key(v3) -> None:
    """A channel's key is a name for humans; `address` is the wire value.

    Keying on the object name would make a channel rename look like a channel
    move even when the address never changed.
    """
    assert all("/" in (op.channel or "") for op in v3.operations)
    assert not any(op.channel in ("userCreated", "userDeleteRequest") for op in v3.operations)


def test_an_unreleased_major_is_refused_rather_than_guessed(tmp_path: Path) -> None:
    """Parsing a 4.x document as though it resembled 3.x would produce a
    contract that looks parsed and is wrong -- worse than saying so."""
    plugin = AsyncApiSpecPlugin()
    assert plugin.detect("x", b'{"asyncapi": "3.0.0"}')
    assert plugin.detect("x", b'{"asyncapi": "2.6.0"}')
    assert not plugin.detect("x", b'{"asyncapi": "4.0.0"}')
    assert not plugin.detect("x", b'{"openapi": "3.0.3"}')


def test_the_plugin_declares_its_contract_version() -> None:
    assert AsyncApiSpecPlugin.PLUGIN_API_VERSION == "1"


def test_the_plugin_is_registered_as_an_entry_point() -> None:
    """It was reachable only through the hardcoded builtin list, so an
    installation that resolved plugins through entry points did not have it."""
    from apiverity.plugins.registry import load_group

    assert "asyncapi" in {name for name, _ in load_group("apiverity.specs")}


def test_a_v3_operation_with_no_action_is_reported_not_dropped(tmp_path: Path) -> None:
    from apiverity.specs.asyncapi import load_asyncapi

    path = tmp_path / "bad.yaml"
    path.write_text(
        "asyncapi: '3.0.0'\n"
        "info: { title: T, version: '1.0.0' }\n"
        "channels: { c: { address: a, messages: { M: { payload: { type: object } } } } }\n"
        "operations:\n"
        "  weird:\n"
        "    action: broadcast\n"
        "    channel: { $ref: '#/channels/c' }\n",
        encoding="utf-8",
    )
    service, findings = load_asyncapi(str(path))
    assert service.operations == []
    assert any(f.rule_id == "ASYNCAPI-OPERATION-BAD-ACTION" for f in findings)


def test_a_v3_operation_pointing_nowhere_is_reported(tmp_path: Path) -> None:
    from apiverity.specs.asyncapi import load_asyncapi

    path = tmp_path / "bad.yaml"
    path.write_text(
        "asyncapi: '3.0.0'\n"
        "info: { title: T, version: '1.0.0' }\n"
        "channels: {}\n"
        "operations:\n"
        "  orphan:\n"
        "    action: send\n"
        "    channel: { $ref: '#/channels/missing' }\n",
        encoding="utf-8",
    )
    service, findings = load_asyncapi(str(path))
    assert service.operations == []
    assert any(f.rule_id == "ASYNCAPI-OPERATION-NO-CHANNEL" for f in findings)


# ------------------------------------------------------------------ direction


def test_the_two_versions_name_the_same_direction_differently() -> None:
    """AsyncAPI 2's words read from the client's side and are inverted.

    `subscribe` describes what the application *produces*; `publish` describes
    what it *consumes*.
    """
    assert DIRECTION["subscribe"] == "send"
    assert DIRECTION["publish"] == "receive"
    assert DIRECTION["send"] == "send"
    assert DIRECTION["receive"] == "receive"


def test_the_document_word_is_kept_alongside_the_normalized_one(v2) -> None:
    by_action = {op.source_action: op.direction for op in v2.operations}
    assert by_action == {"subscribe": "send", "publish": "receive"}


def test_a_v2_document_equals_its_own_v3_migration(v2, v3) -> None:
    """The test the normalization exists for.

    Without it every operation reads as removed and re-added, so a migration
    that changed nothing produces a wall of breaking changes.
    """
    changes = diff_services(v2, v3)
    assert changes == [], [c.description for c in changes]


# ----------------------------------------------------------------- event keys


def test_the_channel_is_part_of_an_event_key(v2) -> None:
    """Keying on message name alone let two channels collide."""
    keys = {op.key for op in v2.operations}
    assert "send user/created#UserCreated" in keys
    assert "receive user/delete-request#DeleteUser" in keys


def test_two_channels_carrying_the_same_message_do_not_collide(tmp_path: Path) -> None:
    text = """\
asyncapi: "2.6.0"
info: { title: T, version: "1.0.0" }
channels:
  a/events:
    subscribe:
      message: { name: Thing, payload: { type: object } }
  b/events:
    subscribe:
      message: { name: Thing, payload: { type: object } }
"""
    service = _load(tmp_path, text, "dup.yaml")
    keys = [op.key for op in service.operations]
    assert len(keys) == len(set(keys)), f"two channels collided on one key: {keys}"


def test_flipping_a_message_from_received_to_sent_is_visible(tmp_path: Path) -> None:
    """It reverses who breaks when the payload changes, so it is not cosmetic."""
    before = _load(tmp_path, _V2, "before.yaml")
    after = _load(tmp_path, _V2.replace("subscribe:", "publish:", 1), "after.yaml")
    changes = diff_services(before, after)
    assert changes, "reversing a message's direction produced no change at all"


# --------------------------------------------------------- direction-aware diff


def test_dropping_a_field_from_a_sent_message_is_breaking(tmp_path: Path) -> None:
    """The misclassification this fixes.

    A message the application sends is read by consumers. Dropping a required
    field from it was reported as `BRK-REQ-FIELD-OPTIONALIZED` at INFO --
    "senders are unaffected" -- when the application *is* the sender and it is
    the consumers who break.
    """
    before = _load(tmp_path, _V2, "before.yaml")
    after = _load(tmp_path, _V2.replace("required: [id, email]", "required: [id]"), "after.yaml")
    findings = evaluate_breaking(diff_services(before, after))
    matching = [f for f in findings if "email" in f.message]
    assert matching, "dropping a required field produced no finding"
    assert matching[0].rule_id == "BRK-RESP-FIELD-OPTIONALIZED", matching[0].rule_id
    assert matching[0].severity.value.upper() == "ERROR"


def test_dropping_a_field_from_a_received_message_is_a_relaxation(tmp_path: Path) -> None:
    """The other direction, which must not be swept up by the same fix.

    A message the application receives is one that producers send. Relaxing
    what the application demands of it cannot break a producer.
    """
    before = _load(tmp_path, _V2, "before.yaml")
    after = _load(tmp_path, _V2.replace("required: [id]\n", "required: []\n"), "after.yaml")
    findings = evaluate_breaking(diff_services(before, after))
    matching = [f for f in findings if "'id'" in f.message and "delete" in f.operation_key]
    assert matching, [f.message for f in findings]
    assert matching[0].rule_id == "BRK-REQ-FIELD-OPTIONALIZED"
    assert matching[0].severity.value.upper() == "INFO"


def test_an_http_request_body_is_still_treated_as_a_request(tmp_path: Path) -> None:
    """The routing keys off event direction, so HTTP must be untouched."""
    spec = """\
openapi: "3.0.3"
info: {{ title: T, version: "1.0.0" }}
paths:
  /users:
    post:
      operationId: createUser
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required: [{required}]
              properties:
                id: {{ type: string }}
                email: {{ type: string }}
      responses:
        "200": {{ description: ok }}
"""
    before = _load(tmp_path, spec.format(required="id, email"), "a.yaml")
    after = _load(tmp_path, spec.format(required="id"), "b.yaml")
    findings = evaluate_breaking(diff_services(before, after))
    matching = [f for f in findings if "email" in f.message]
    assert matching
    assert matching[0].rule_id == "BRK-REQ-FIELD-OPTIONALIZED"
    assert matching[0].severity.value.upper() == "INFO"
