"""The guide the API owner already wrote, reaching the finding that blocks.

`DeprecationInfo.migration_guide` had been in the model since the beginning,
populated by no parser and read by no rule. `Approval.migration_guide` is a
column in the server database, accepted on every request, typed in the
dashboard — and rendered nowhere.

Two fields, two places, both written and never read.
"""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
from typing import Any

from apiverity.cli.main import main
from apiverity.core.model import Finding, Operation, Severity
from apiverity.rules.migration import attach, collect, deprecation_of, summarize
from apiverity.specs.loader import detect_and_load

_ROOT = Path(__file__).resolve().parents[2]
_V1 = str(_ROOT / "fixtures/apis/deprecated/v1.yaml")
_V2 = str(_ROOT / "fixtures/apis/deprecated/v2.yaml")


def _run(argv: list[str]) -> tuple[int, dict[str, Any]]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        code = main(argv)
    text = out.getvalue()
    return code, (json.loads(text) if text.strip().startswith("{") else {})


def _op(**extensions: Any) -> Operation:
    return Operation(method="GET", path="/users", extensions=extensions)


# ----------------------------------------------------- reading what is written


def test_the_structured_block_is_read() -> None:
    info = deprecation_of(
        _op(
            **{
                "x-deprecation": {
                    "announced": "2026-01-15",
                    "sunset": "2027-01-01",
                    "guide": "https://docs.example.test/v2",
                    "impact": "mobile below 3.4",
                }
            }
        )
    )
    assert info is not None
    assert info.sunset_date == "2027-01-01"
    assert info.migration_guide == "https://docs.example.test/v2"
    assert info.consumer_impact == "mobile below 3.4"


def test_the_flat_spellings_are_read_too() -> None:
    """A rule that only understood the tidy form would report "points nowhere"
    about contracts that point somewhere."""
    info = deprecation_of(_op(**{"x-migration": "https://x.test/v2", "x-sunset": "2027-01-01"}))
    assert info is not None
    assert info.migration_guide == "https://x.test/v2"
    assert info.sunset_date == "2027-01-01"


def test_x_deprecation_as_a_bare_date_is_the_announcement() -> None:
    info = deprecation_of(_op(**{"x-deprecation": "2026-01-15"}))
    assert info is not None and info.announced_date == "2026-01-15"


def test_an_operation_that_says_nothing_produces_nothing() -> None:
    assert deprecation_of(_op()) is None
    assert deprecation_of(_op(**{"x-deprecation": {}})) is None


def test_an_empty_string_is_not_a_guide() -> None:
    assert deprecation_of(_op(**{"x-migration": "   "})) is None


# --------------------------------------------------------------- attaching it


def test_a_finding_carries_the_guide_for_its_operation() -> None:
    old, _, _ = detect_and_load(_V1)
    findings = [
        Finding(
            rule_id="BRK-RESP-FIELD-REMOVED",
            severity=Severity.ERROR,
            message="a field went",
            operation_key="GET /users/{id}",
        )
    ]
    out = attach(findings, old)
    assert out[0].metadata["migration_guide"] == "https://docs.example.test/migrating-to-v2"
    assert out[0].metadata["consumer_impact"].startswith("mobile clients")
    assert out[0].metadata["sunset_date"] == "2027-01-01"


def test_a_finding_about_an_operation_with_no_guide_carries_nothing() -> None:
    old, _, _ = detect_and_load(_V1)
    findings = [
        Finding(
            rule_id="BRK-OP-REMOVED",
            severity=Severity.ERROR,
            message="gone",
            operation_key="GET /reports",
        )
    ]
    assert attach(findings, old)[0].metadata == {}


def test_the_originals_are_not_mutated() -> None:
    """The same list is read by the semver policy and the summary after this."""
    old, _, _ = detect_and_load(_V1)
    findings = [
        Finding(
            rule_id="BRK-RESP-FIELD-REMOVED",
            severity=Severity.ERROR,
            message="x",
            operation_key="GET /users/{id}",
        )
    ]
    attach(findings, old)
    assert findings[0].metadata == {}


def test_a_contract_with_no_guides_at_all_is_left_alone() -> None:
    new, _, _ = detect_and_load(str(_ROOT / "fixtures/apis/crud/openapi.yaml"))
    findings = [
        Finding(rule_id="X", severity=Severity.WARN, message="y", operation_key="GET /users")
    ]
    assert attach(findings, new) is findings


def test_collect_ignores_a_deprecation_with_dates_but_no_guidance() -> None:
    """A sunset date is not guidance. It says when, not where to."""
    old, _, _ = detect_and_load(_V1)
    guides = collect(old)
    assert set(guides.by_operation) == {"GET /users/{id}"}


# ------------------------------------------------------------- reporting it


def test_one_operation_is_listed_once_however_many_findings_it_has() -> None:
    """Eleven findings about one removed operation should not print the same
    link eleven times, which is how a useful line becomes noise."""
    findings = [
        Finding(
            rule_id=f"BRK-{n}",
            severity=Severity.ERROR,
            message="x",
            operation_key="GET /users/{id}",
            metadata={"migration_guide": "https://x.test/v2"},
        )
        for n in range(11)
    ]
    assert summarize(findings) == [{"operation": "GET /users/{id}", "guide": "https://x.test/v2"}]


def test_a_finding_with_no_guide_is_not_listed() -> None:
    assert summarize([Finding(rule_id="X", severity=Severity.WARN, message="y")]) == []


# --------------------------------------------------------------- end to end


def test_breaking_carries_the_guide_to_the_reader() -> None:
    code, payload = _run(["breaking", _V1, _V2, "--json"])
    assert code == 1
    assert payload["migration_guides"] == [
        {
            "operation": "GET /users/{id}",
            "guide": "https://docs.example.test/migrating-to-v2",
            "impact": "mobile clients pinned below 3.4 need a release",
        }
    ]
    removed = next(f for f in payload["findings"] if f["rule_id"] == "BRK-RESP-FIELD-REMOVED")
    assert removed["metadata"]["migration_guide"]


def test_the_summary_prints_it_above_the_generic_advice() -> None:
    """The API owner's own guide beats anything this tool can say about their API."""
    _, payload = _run(["breaking", _V1, _V2, "--summary", "--json"])
    markdown = payload["summary"]["markdown"]
    assert "https://docs.example.test/migrating-to-v2" in markdown
    assert "mobile clients pinned below 3.4" in markdown
    assert markdown.index("migration guide") < markdown.index("apiverity explain")


def test_a_contract_with_no_guides_says_nothing_about_them() -> None:
    _, payload = _run(
        [
            "breaking",
            str(_ROOT / "fixtures/apis/versioned/v1.yaml"),
            str(_ROOT / "fixtures/apis/versioned/v2.yaml"),
            "--json",
        ]
    )
    assert "migration_guides" not in payload


# ------------------------------------------- the false positives this removed


def test_the_lifecycle_rules_read_the_structured_block() -> None:
    """Two published rules fired on a contract that satisfies both of them.

    `x-deprecation` is read as a flat date *and* published in the wild as an
    object with `sunset` and `guide` inside it. Reading only the flat form
    reported "names no retirement date" and "points nowhere" about a contract
    that names one and points somewhere — which is the kind of false positive
    that gets a governance rule switched off along with its neighbours.
    """
    _, payload = _run(["validate", _V1, "--json"])
    lifecycle = [f for f in payload["findings"] if f["rule_id"].startswith("LIFECYCLE-")]
    assert lifecycle == [], lifecycle


def test_and_still_fire_when_the_contract_really_says_nothing(tmp_path: Path) -> None:
    spec = tmp_path / "bare.yaml"
    spec.write_text(
        "openapi: 3.1.0\ninfo: {title: X, version: '1.0.0'}\n"
        "paths:\n  /u:\n    get:\n      deprecated: true\n"
        "      responses:\n        '200':\n          description: ok\n",
        encoding="utf-8",
    )
    _, payload = _run(["validate", str(spec), "--json"])
    fired = {f["rule_id"] for f in payload["findings"] if f["rule_id"].startswith("LIFECYCLE-")}
    assert "LIFECYCLE-DEPRECATED-NO-SUNSET" in fired
    assert "LIFECYCLE-DEPRECATED-NO-GUIDANCE" in fired
