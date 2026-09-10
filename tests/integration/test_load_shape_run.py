"""A declared arrival rate, driven at a real server.

`tests/unit/test_load_shapes.py` proves the schedule is honoured against a
virtual clock. That is the part a fake can prove. What it cannot prove is that
the requests reach a socket at roughly the rate the profile names -- a
generator can honour a schedule perfectly against a clock it controls and still
be three seconds behind against a real one.
"""

from __future__ import annotations

import contextlib
import io
import json
from typing import Any

import pytest

from apiverity.cli.main import main
from apiverity.mock import MockServer
from apiverity.performance.profiles import SCHEDULE_TOLERANCE_MS
from apiverity.specs.loader import detect_and_load

_SPEC = "fixtures/apis/crud/openapi.yaml"


@pytest.fixture
def service():
    loaded, _findings, _plugin = detect_and_load(_SPEC)
    return loaded


def _run(argv: list[str]) -> tuple[int, dict[str, Any]]:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = main(argv)
    try:
        return code, json.loads(buffer.getvalue())
    except ValueError:
        return code, {}


def _shape(base_url: str, *extra: str) -> list[str]:
    return [
        "--no-config",
        "regression",
        _SPEC,
        "--base-url",
        base_url,
        "--shape",
        "constant:2s@20",
        "--operation",
        "GET /users",
        "--json",
        *extra,
    ]


def test_the_requested_rate_is_roughly_the_rate_that_arrives(service) -> None:
    with MockServer(service, port=0) as mock:
        code, payload = _run(_shape(mock.base_url))
    shape = payload["shape"]
    assert code == 0
    assert shape["scheduled"] == shape["sent"] + shape["errors"]
    assert shape["requested_rps"] == 20.0
    # Not "the achieved rate is 20" -- that is a claim about the machine, and a
    # loaded CI runner falsifies it. The property that holds everywhere is the
    # one the feature exists for: either the generator kept up and the rate is
    # what was asked for, or it did not and the run says so. A run that missed
    # the rate *and* claimed to have kept up would be the actual defect.
    if shape["kept_up"]:
        assert 15.0 <= shape["achieved_rps"] <= 25.0
    else:
        assert shape["max_late_ms"] > SCHEDULE_TOLERANCE_MS


def test_the_run_reports_whether_the_generator_kept_up(service) -> None:
    """Not a verdict on the service. With requests going out seconds after
    they were due, the latencies describe a load nobody asked for -- so the
    report says which it was rather than leaving the reader to assume."""
    with MockServer(service, port=0) as mock:
        _code, payload = _run(_shape(mock.base_url))
    assert "kept_up" in payload["shape"]
    assert "max_late_ms" in payload["shape"]


def _with_shape(base_url: str, spec: str) -> dict[str, Any]:
    argv = _shape(base_url)
    argv[argv.index("constant:2s@20")] = spec
    code, payload = _run(argv)
    assert code == 0, payload
    return dict(payload["shape"])


def test_a_ramp_climbs_above_the_rate_it_started_at(service) -> None:
    """The shape reaching a socket, not just a schedule. A run that ramps from
    2/s to 40/s sends several times what a flat 2/s does over the same two
    seconds -- which is the only externally visible difference between the two,
    and was not visible at all while the offsets were discarded."""
    with MockServer(service, port=0) as mock:
        flat = _with_shape(mock.base_url, "constant:2s@2")
        ramp = _with_shape(mock.base_url, "ramp:2s@2..40")
    assert ramp["profile"].startswith("ramp 2s at 2/s -> 40/s")
    # A count, not a duration: how many requests the schedule called for is a
    # fact about the profile, and how long they took is a fact about the
    # machine.
    assert ramp["scheduled"] > flat["scheduled"] * 3
    assert ramp["sent"] > flat["sent"] * 3


def test_an_unreachable_target_reports_unreachable() -> None:
    """Distinct from a service with a 100% error rate, which is a different
    thing to tell somebody."""
    code, _payload = _run(
        [
            "--no-config",
            "regression",
            _SPEC,
            "--base-url",
            "http://127.0.0.1:1",
            "--shape",
            "constant:0.2s@5",
            "--operation",
            "GET /users",
            "--json",
        ]
    )
    assert code != 0
