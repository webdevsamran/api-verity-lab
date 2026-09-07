"""Descriptor-set input and protobuf-aware compatibility rules (#17).

The issue's own note is the standard here: do not claim protobuf
compatibility until each rule is covered. Every rule added gets a test, and
the fixtures are real `protoc --descriptor_set_out` output rather than bytes
this project encoded itself -- a decoder tested only against its own encoder
proves the two agree, not that either matches protobuf.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from apiverity.diff.engine import diff_services
from apiverity.rules.breaking import CATALOG, evaluate_breaking
from apiverity.specs.grpc import GrpcSpecPlugin
from apiverity.specs.grpc.descriptor import DescriptorError, parse_descriptor_set
from apiverity.specs.loader import detect_and_load

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "grpc"


def _rules(old: str, new: str) -> set[str]:
    a, _, _ = detect_and_load(str(FIXTURES / old))
    b, _, _ = detect_and_load(str(FIXTURES / new))
    return {f.rule_id for f in evaluate_breaking(diff_services(a, b))}


def _proto(tmp_path: Path, body: str, name: str):
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    service, _, _ = detect_and_load(str(path))
    return service


def _findings(tmp_path: Path, before: str, after: str):
    a = _proto(tmp_path, before, "a.proto")
    b = _proto(tmp_path, after, "b.proto")
    return evaluate_breaking(diff_services(a, b))


_BASE = """\
syntax = "proto3";
package demo;
message User {{
{reserved}  string id = 1;
{fields}}}
message Req {{ string id = 1; }}
service Users {{
  rpc Get({req_stream}Req) returns ({resp_stream}User);
}}
"""


def _spec(
    *, fields: str = "  string name = 2;\n", reserved: str = "", req: str = "", resp: str = ""
) -> str:
    return _BASE.format(fields=fields, reserved=reserved, req_stream=req, resp_stream=resp)


# ------------------------------------------------------------ wire decoding


def test_the_reader_matches_real_protoc_output() -> None:
    """The fixture was produced by `protoc --descriptor_set_out`.

    Everything here is a value protoc chose, not one this project encoded.
    """
    descriptor_set = parse_descriptor_set((FIXTURES / "users_v1.desc").read_bytes())
    file = descriptor_set.files[0]
    assert file.package == "demo.users"
    assert file.syntax == "proto3"

    user = next(m for m in file.messages if m.name == "User")
    # `reserved 4, 7 to 9;` -- descriptor.proto's range end is exclusive, and
    # reading it as inclusive silently drops the last reserved number.
    assert user.reserved_numbers == [4, 7, 8, 9]
    assert user.reserved_names == ["legacy_email"]
    assert user.oneofs() == {"contact": ["email", "phone"]}

    request = next(m for m in file.messages if m.name == "GetUserRequest")
    # protoc lowers `optional string trace_id` into a synthetic one-field
    # oneof named `_trace_id`. It is explicit presence, not a union, and
    # reporting it as a oneof would invent a constraint nobody wrote.
    assert request.oneof_names == ["_trace_id"]
    assert request.oneofs() == {}
    assert request.explicit_presence() == ["trace_id"]

    service = file.services[0]
    watch = next(m for m in service.methods if m.name == "WatchUsers")
    assert watch.server_streaming and not watch.client_streaming


def test_a_file_that_is_not_a_descriptor_set_is_refused_with_advice(tmp_path: Path) -> None:
    junk = tmp_path / "notes.desc"
    junk.write_text("this is not protobuf at all, it is prose", encoding="utf-8")
    with pytest.raises(ValueError, match="descriptor_set_out"):
        GrpcSpecPlugin().load(str(junk))


def test_truncated_bytes_do_not_hang_or_crash_obscurely() -> None:
    data = (FIXTURES / "users_v1.desc").read_bytes()
    with pytest.raises(DescriptorError):
        parse_descriptor_set(data[: len(data) // 2])
    with pytest.raises(DescriptorError):
        parse_descriptor_set(b"")


def test_descriptor_sets_are_detected_by_extension() -> None:
    plugin = GrpcSpecPlugin()
    for suffix in plugin.DESCRIPTOR_SUFFIXES:
        assert plugin.detect(f"api{suffix}")
    assert plugin.detect("api.proto")


# --------------------------------------------------- the two paths agree


def test_the_two_input_paths_produce_the_same_verdict() -> None:
    """A descriptor set and the .proto it was compiled from are one contract.

    If they disagreed, one of the two readers would be wrong and there would
    be no way to tell which from inside the tool.
    """
    from_descriptors = _rules("users_v1.desc", "users_v2.desc")
    from_sources = _rules("users_v1.proto", "users_v2.proto")
    assert from_descriptors == from_sources, {
        "only in descriptors": sorted(from_descriptors - from_sources),
        "only in sources": sorted(from_sources - from_descriptors),
    }
    assert from_descriptors, "the fixture pair produced no findings at all"


# ------------------------------------------------------------------ streaming


@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [
        (("", ""), ("stream ", ""), "client streaming"),
        (("", ""), ("", "stream "), "server streaming"),
        (("", ""), ("stream ", "stream "), "bidirectional streaming"),
        (("", "stream "), ("", ""), "unary"),
    ],
)
def test_every_streaming_transition_is_breaking(
    tmp_path: Path, before: tuple[str, str], after: tuple[str, str], expected: str
) -> None:
    """`stream` was captured by the regex and thrown away, so a unary RPC
    becoming bidirectional produced no change at all."""
    findings = _findings(
        tmp_path,
        _spec(req=before[0], resp=before[1]),
        _spec(req=after[0], resp=after[1]),
    )
    streaming = [f for f in findings if f.rule_id == "BRK-RPC-STREAMING-CHANGED"]
    assert streaming, [f.rule_id for f in findings]
    assert streaming[0].severity.value.upper() == "ERROR"
    assert expected in streaming[0].message


def test_an_unchanged_rpc_reports_no_streaming_change(tmp_path: Path) -> None:
    assert not [
        f
        for f in _findings(tmp_path, _spec(resp="stream "), _spec(resp="stream "))
        if f.rule_id == "BRK-RPC-STREAMING-CHANGED"
    ]


# --------------------------------------------------------------- field numbers


def test_a_rename_at_the_same_number_is_wire_compatible(tmp_path: Path) -> None:
    """The wire carries numbers, not names.

    Reporting a rename as data corruption would train people to ignore the
    rule that catches actual data corruption.
    """
    findings = _findings(
        tmp_path,
        _spec(fields="  string name = 2;\n"),
        _spec(fields="  string display_name = 2;\n"),
    )
    assert not [f for f in findings if f.rule_id == "BRK-FIELD-NUMBER-REUSED"]
    renames = [f for f in findings if "renamed" in f.message]
    assert renames and "wire-compatible" in renames[0].message


def test_a_number_reused_for_a_different_type_is_an_error(tmp_path: Path) -> None:
    """The failure `reserved` exists to prevent: old data decodes into a
    field of the wrong type."""
    findings = _findings(
        tmp_path,
        _spec(fields="  string name = 2;\n"),
        _spec(fields="  int64 name = 2;\n  string other = 3;\n"),
    )
    # A same-name type change is caught by the type rule; the number-reuse
    # rule is for a number whose *meaning* moved.
    renumbered = _findings(
        tmp_path,
        _spec(fields="  string name = 2;\n"),
        _spec(fields="  int64 count = 2;\n"),
    )
    reuse = [f for f in renumbered if f.rule_id == "BRK-FIELD-NUMBER-REUSED"]
    assert reuse, [f.rule_id for f in renumbered]
    assert reuse[0].severity.value.upper() == "ERROR"
    assert "string" in reuse[0].message and "int64" in reuse[0].message
    assert findings, "a same-name type change should still be reported"


def test_removing_a_field_without_reserving_its_number_is_flagged(tmp_path: Path) -> None:
    findings = _findings(
        tmp_path,
        _spec(fields="  string name = 2;\n  int32 age = 3;\n"),
        _spec(fields="  string name = 2;\n"),
    )
    assert any(f.rule_id == "BRK-FIELD-NUMBER-UNRESERVED" for f in findings), [
        f.rule_id for f in findings
    ]


def test_reserving_the_number_on_removal_is_accepted(tmp_path: Path) -> None:
    """Doing it correctly must not still be reported, or the rule is noise."""
    findings = _findings(
        tmp_path,
        _spec(fields="  string name = 2;\n  int32 age = 3;\n"),
        _spec(fields="  string name = 2;\n", reserved="  reserved 3;\n"),
    )
    assert not [f for f in findings if f.rule_id == "BRK-FIELD-NUMBER-UNRESERVED"]


# ------------------------------------------------------------------- reserved


def test_reserved_ranges_are_parsed(tmp_path: Path) -> None:
    service = _proto(
        tmp_path,
        _spec(reserved='  reserved 2, 15, 9 to 11;\n  reserved "old_name";\n'),
        "r.proto",
    )
    schema = service.operations[0].responses[0].content["application/x-protobuf"]
    assert schema.reserved_numbers == [2, 9, 10, 11, 15]
    assert schema.reserved_names == ["old_name"]


def test_using_a_reserved_number_is_reported_at_load(tmp_path: Path) -> None:
    path = tmp_path / "bad.proto"
    path.write_text(_spec(fields="  string name = 2;\n", reserved="  reserved 2;\n"), "utf-8")
    _service, findings = GrpcSpecPlugin().load(str(path))
    assert any(f.rule_id == "PROTO-RESERVED-NUMBER-USED" for f in findings), [
        f.rule_id for f in findings
    ]


def test_using_a_reserved_name_is_reported_at_load(tmp_path: Path) -> None:
    path = tmp_path / "bad.proto"
    path.write_text(_spec(fields="  string name = 2;\n", reserved='  reserved "name";\n'), "utf-8")
    _service, findings = GrpcSpecPlugin().load(str(path))
    assert any(f.rule_id == "PROTO-RESERVED-NAME-USED" for f in findings)


def test_field_number_reuse_is_actually_reported(tmp_path: Path) -> None:
    """The documented load-time check built a finding and dropped it.

    `_message_to_schema` returned only the schema, so every
    PROTO-FIELD-NUMBER-REUSE it constructed went out of scope unreported.
    """
    path = tmp_path / "dup.proto"
    path.write_text(_spec(fields="  string a = 2;\n  string b = 2;\n"), "utf-8")
    _service, findings = GrpcSpecPlugin().load(str(path))
    assert any(f.rule_id == "PROTO-FIELD-NUMBER-REUSE" for f in findings), [
        f.rule_id for f in findings
    ]


def test_un_reserving_a_number_is_reported(tmp_path: Path) -> None:
    findings = _findings(
        tmp_path,
        _spec(reserved="  reserved 42;\n"),
        _spec(reserved=""),
    )
    assert any(f.rule_id == "BRK-RESERVATION-REMOVED" for f in findings)


# ------------------------------------------------------------------- presence


def test_losing_explicit_presence_is_breaking(tmp_path: Path) -> None:
    """proto3 `optional` is what makes unset distinguishable from default.

    Removing it means a client can no longer tell "not sent" from "sent as
    empty string", which changes behaviour without changing any type.
    """
    findings = _findings(
        tmp_path,
        _spec(fields="  optional string nickname = 2;\n"),
        _spec(fields="  string nickname = 2;\n"),
    )
    presence = [f for f in findings if f.rule_id == "BRK-FIELD-PRESENCE-LOST"]
    assert presence, [f.rule_id for f in findings]
    assert presence[0].severity.value.upper() == "ERROR"


def test_gaining_explicit_presence_is_not_reported_as_a_loss(tmp_path: Path) -> None:
    findings = _findings(
        tmp_path,
        _spec(fields="  string nickname = 2;\n"),
        _spec(fields="  optional string nickname = 2;\n"),
    )
    assert not [f for f in findings if f.rule_id == "BRK-FIELD-PRESENCE-LOST"]


def test_moving_a_field_into_a_oneof_narrows_the_message(tmp_path: Path) -> None:
    findings = _findings(
        tmp_path,
        _spec(fields="  string email = 2;\n  string phone = 3;\n"),
        _spec(fields="  oneof contact {\n    string email = 2;\n    string phone = 3;\n  }\n"),
    )
    narrowed = [f for f in findings if f.rule_id == "BRK-ONEOF-NARROWED"]
    assert narrowed, [f.rule_id for f in findings]
    assert narrowed[0].severity.value.upper() == "ERROR"


def test_moving_a_field_out_of_a_oneof_widens_it(tmp_path: Path) -> None:
    """No existing sender can notice, so it is informational, not breaking."""
    findings = _findings(
        tmp_path,
        _spec(fields="  oneof contact {\n    string email = 2;\n    string phone = 3;\n  }\n"),
        _spec(fields="  string email = 2;\n  string phone = 3;\n"),
    )
    widened = [f for f in findings if f.rule_id == "BRK-ONEOF-WIDENED"]
    assert widened
    assert widened[0].severity.value.upper() == "INFO"
    assert not [f for f in findings if f.rule_id == "BRK-ONEOF-NARROWED"]


# ------------------------------------------------------------------- catalog


@pytest.mark.parametrize(
    "rule",
    [
        "BRK-RPC-STREAMING-CHANGED",
        "BRK-FIELD-NUMBER-REUSED",
        "BRK-FIELD-NUMBER-UNRESERVED",
        "BRK-FIELD-PRESENCE-LOST",
        "BRK-ONEOF-NARROWED",
        "BRK-ONEOF-WIDENED",
        "BRK-RESERVATION-REMOVED",
    ],
)
def test_every_new_rule_is_in_the_catalog(rule: str) -> None:
    """An emitted rule id outside CATALOG cannot have its severity overridden
    and never appears in the generated documentation."""
    assert rule in CATALOG


def test_an_unchanged_contract_produces_nothing(tmp_path: Path) -> None:
    """The most important negative: none of these rules fire on a no-op."""
    assert _findings(tmp_path, _spec(), _spec()) == []
    assert _rules("users_v1.desc", "users_v1.desc") == set()
