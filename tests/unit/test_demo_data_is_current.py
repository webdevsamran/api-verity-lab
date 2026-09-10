"""The committed demo artifact must carry every section the pages read.

`scripts/generate-demo-data.py` raised `AttributeError` on every run for
months -- `TestCase.path` had been renamed to `url_path` and the generator kept
the old name. Nothing runs the generator in CI, so nobody found out; the
committed `web/public/demo-data.json` simply stopped being updated in August,
and six pages that read sections written after that point rendered
"Loading..." on the public demo the entire time.

Two failures, and this file guards both. The generator has to still work, and
the artifact it produces has to still contain what `data.ts` says a `DemoData`
has. A dashboard whose data went stale looks exactly like a dashboard that is
broken, and neither the build nor the tests could tell the difference.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_DATA = _ROOT / "web" / "public" / "demo-data.json"
_TYPES = _ROOT / "web" / "src" / "data.ts"
_GENERATOR = _ROOT / "scripts" / "generate-demo-data.py"


#: Keys the *app* stamps at load time rather than the generator writing.
#:
#: `source` says where the data came from -- a file, or a live server -- so it
#: is a property of the load, not of the artifact. An artifact that carried one
#: would be asserting how it would later be read.
_STAMPED_BY_THE_APP = {"source"}


def _declared_sections() -> set[str]:
    """Top-level keys `DemoData` declares, required and optional alike."""
    source = _TYPES.read_text(encoding="utf-8")
    body = source[source.index("export interface DemoData {") :]
    body = body[: body.index(chr(10) + "}")]
    # `name?: T` and `name: T`, ignoring comment lines.
    declared = {
        match.group(1) for line in body.splitlines() if (match := re.match(r"\s{2}(\w+)\??:", line))
    }
    return declared - _STAMPED_BY_THE_APP


def _artifact() -> dict[str, object]:
    payload = json.loads(_DATA.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_the_artifact_carries_every_section_the_types_declare() -> None:
    missing = sorted(_declared_sections() - set(_artifact()))
    assert not missing, (
        f"web/public/demo-data.json has no {missing}. The pages that read those sections "
        "render an empty state on the public demo. Re-run scripts/generate-demo-data.py."
    )


def test_the_artifact_declares_no_section_the_types_do_not_know() -> None:
    """A section nothing reads is dead weight in a file people download."""
    extra = sorted(set(_artifact()) - _declared_sections())
    assert not extra, f"demo-data.json carries sections `DemoData` does not declare: {extra}"


@pytest.mark.parametrize(
    ("section", "shape"),
    [
        ("agents", ("fleet", "poisoning", "budget")),
        ("org", ("users", "contracts", "approvals", "audit_events")),
        ("replay", ("manifest", "dry_run")),
        ("catalog", ("services",)),
    ],
)
def test_a_section_that_exists_is_not_empty(section: str, shape: tuple[str, ...]) -> None:
    """Present-but-hollow is the other way this goes wrong quietly."""
    payload = _artifact()[section]
    assert isinstance(payload, dict)
    assert not [key for key in shape if key not in payload], (
        f"demo-data.json's `{section}` is missing {sorted(set(shape) - set(payload))}"
    )


def test_the_fleet_section_came_from_real_probes() -> None:
    """Every row is a measurement, not a mockup, and the numbers show it."""
    fleet = _artifact()["agents"]["fleet"]  # type: ignore[index]
    assert isinstance(fleet, list) and len(fleet) >= 2
    for server in fleet:
        assert server["endpoint"].startswith("http://127.0.0.1:")
        assert server["tools_served"] >= 0
        assert server["protocol_revision"], "a probe that established nothing is not a row"


def test_the_performance_section_measured_something_that_answered() -> None:
    """The demo Performance page plotted a closed port for months.

    `measure` sat one line below the `with MockServer(...)` block in the
    generator, so it ran after the mock had been shut down. Every operation
    came back `unreachable: 15`, `errors: 15`, `p50_ms: 2055` -- the connect
    timeout -- and `throughput_rps: 7`. The dashboard rendered all of it as a
    service under load, and the artifact said `unreachable` the whole time.

    Nothing here compares numbers to expected values; timing is not
    reproducible and asserting on it would produce a flaky test that gets
    deleted. What is asserted is the distinction the artifact already draws
    and nobody read: something answered.
    """
    performance = _artifact()["performance"]
    assert isinstance(performance, dict)
    operations = performance["operations"]
    assert isinstance(operations, list) and operations

    dead = [op["operation_key"] for op in operations if op["unreachable"] == op["samples"]]
    assert not dead, (
        f"the demo performance section measured nothing for {dead}: every request was "
        "refused. Re-run scripts/generate-demo-data.py -- and check `measure` is inside "
        "the MockServer block, which is the mistake this test exists for."
    )


def test_the_performance_section_reports_response_size() -> None:
    """A p95 of 12 ms and a response of four megabytes are both facts about
    the same call, and the artifact used to carry only one of them."""
    operations = _artifact()["performance"]["operations"]  # type: ignore[index]
    assert any(op.get("bytes_max", 0) > 0 for op in operations), (
        "no operation reported a response size; either nothing answered or the "
        "artifact predates the byte counters"
    )


def test_the_performance_section_carries_the_connection_probe() -> None:
    """And the sentence saying it is not inside the percentiles, which is what
    stops a reader adding a handshake to a p95."""
    connection = _artifact()["performance"]["connection"]  # type: ignore[index]
    assert isinstance(connection, dict)
    assert connection["tcp_ms"] is not None
    assert "reuse a pooled connection" in connection["note"]


def test_the_generator_does_not_reference_a_field_the_model_renamed() -> None:
    """The exact regression: `TestCase.path` became `url_path` and this broke.

    Cheaper than running the generator in the unit suite, and it catches the
    shape of the failure rather than only this instance of it.
    """
    from apiverity.fuzz.models import TestCase

    source = _GENERATOR.read_text(encoding="utf-8")
    # Fields *and* attributes: `c.model_dump()` is a pydantic method, not a
    # typo, and a check that cannot tell those apart would be turned off.
    known = set(TestCase.model_fields) | set(dir(TestCase))
    used = set(re.findall(r"\bc\.(\w+)\b", source))
    unknown = sorted(used - known)
    assert not unknown, (
        f"generate-demo-data.py reads {unknown} off a TestCase, which has "
        f"{sorted(known)}. The generator would raise at run time and the demo "
        "artifact would silently stop being updated."
    )
