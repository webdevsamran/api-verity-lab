"""Who breaks, not just what breaks.

`BRK-OP-REMOVED: operation 'DELETE /users/{id}' was removed` is accurate and
un-actionable. The question in the pull request is whose build fails on Monday.

Most of these tests are about the downgrade this module refuses to perform by
default. A registry is incomplete the moment somebody writes a client without
telling anyone, so "no consumer listed" is not "no consumer exists", and
softening a finding on the first is exactly how a breaking change ships.
"""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
from typing import Any

import pytest

from apiverity.cli.commands.common import EXIT_FINDINGS, EXIT_USAGE
from apiverity.cli.main import main
from apiverity.core.model import Finding, Severity
from apiverity.rules.consumers import (
    RegistryError,
    annotate,
    blast_radius,
    load_registry,
    validate_against,
)

_ROOT = Path(__file__).resolve().parents[2]
_V1 = str(_ROOT / "fixtures/apis/versioned/v1.yaml")
_V2 = str(_ROOT / "fixtures/apis/versioned/v2.yaml")

_REGISTRY = """version: 1
consumers:
  - name: checkout-service
    team: payments
    contact: "#payments"
    uses:
      - operation: "GET /users"
  - name: mobile-v3
    team: mobile
    uses:
      - operation: "GET /users"
      - operation: "DELETE /users/{id}"
"""


def _write(tmp_path: Path, body: str) -> str:
    path = tmp_path / "consumers.yaml"
    path.write_text(body, encoding="utf-8")
    return str(path)


def _finding(operation: str, severity: Severity = Severity.ERROR) -> Finding:
    return Finding(
        rule_id="BRK-OP-REMOVED",
        severity=severity,
        message=f"operation '{operation}' was removed",
        operation_key=operation,
    )


def _run(argv: list[str]) -> tuple[int, dict[str, Any], str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    text = out.getvalue()
    return code, (json.loads(text) if text.strip().startswith("{") else {}), err.getvalue()


# ------------------------------------------------------------------- parsing


def test_a_consumer_lists_the_operations_it_calls(tmp_path: Path) -> None:
    registry = load_registry(_write(tmp_path, _REGISTRY))
    assert [c.name for c in registry.consumers] == ["checkout-service", "mobile-v3"]
    assert registry.for_operation("GET /users")[0].team == "payments"


def test_a_tool_entry_uses_the_manifest_key(tmp_path: Path) -> None:
    registry = load_registry(
        _write(
            tmp_path, "version: 1\nconsumers:\n  - name: agent\n    uses:\n      - tool: search\n"
        )
    )
    assert registry.consumers[0].operations == ("tool search",)


def test_a_bare_string_entry_works(tmp_path: Path) -> None:
    registry = load_registry(
        _write(tmp_path, 'version: 1\nconsumers:\n  - name: a\n    uses: ["GET /users"]\n')
    )
    assert registry.consumers[0].operations == ("GET /users",)


def test_a_duplicate_consumer_name_is_refused(tmp_path: Path) -> None:
    """Two entries for one name means one of them silently loses."""
    body = "version: 1\nconsumers:\n  - name: a\n    uses: [x]\n  - name: a\n    uses: [y]\n"
    with pytest.raises(RegistryError, match="more than once"):
        load_registry(_write(tmp_path, body))


def test_a_future_registry_version_is_refused(tmp_path: Path) -> None:
    with pytest.raises(RegistryError, match="not supported"):
        load_registry(_write(tmp_path, "version: 2\nconsumers: []\n"))


def test_a_consumer_without_uses_is_refused(tmp_path: Path) -> None:
    with pytest.raises(RegistryError, match="needs a `uses` list"):
        load_registry(_write(tmp_path, "version: 1\nconsumers:\n  - name: a\n"))


def test_a_registry_is_incomplete_unless_it_says_otherwise(tmp_path: Path) -> None:
    assert load_registry(_write(tmp_path, _REGISTRY)).complete is False


# ---------------------------------------------------------------- annotation


def test_a_finding_names_the_consumers_it_breaks(tmp_path: Path) -> None:
    registry = load_registry(_write(tmp_path, _REGISTRY))
    (annotated,) = annotate([_finding("GET /users")], registry)
    assert "affects checkout-service, mobile-v3" in annotated.message
    assert annotated.metadata["consumers"] == ["checkout-service", "mobile-v3"]
    assert annotated.metadata["consumer_teams"] == ["mobile", "payments"]


def test_an_unconsumed_finding_keeps_its_severity(tmp_path: Path) -> None:
    """The default, and the point: information is added, never removed."""
    registry = load_registry(_write(tmp_path, _REGISTRY))
    (annotated,) = annotate([_finding("POST /users")], registry)
    assert annotated.severity is Severity.ERROR
    assert "affects" not in annotated.message


def test_an_incomplete_registry_cannot_soften_anything(tmp_path: Path) -> None:
    """Even when asked. The registry has to take responsibility first."""
    registry = load_registry(_write(tmp_path, _REGISTRY))
    (annotated,) = annotate([_finding("POST /users")], registry, adjust_severity=True)
    assert annotated.severity is Severity.ERROR


def test_a_complete_registry_may_soften_an_unconsumed_error(tmp_path: Path) -> None:
    registry = load_registry(_write(tmp_path, "complete: true\n" + _REGISTRY))
    (annotated,) = annotate([_finding("POST /users")], registry, adjust_severity=True)
    assert annotated.severity is Severity.WARN
    assert annotated.metadata["downgraded_from"] == "ERROR"


def test_a_softened_finding_names_the_file_that_made_the_claim(tmp_path: Path) -> None:
    """So a reader can go and check whether the claim was true."""
    path = _write(tmp_path, "complete: true\n" + _REGISTRY)
    (annotated,) = annotate([_finding("POST /users")], load_registry(path), adjust_severity=True)
    assert "declares itself complete" in annotated.message
    assert Path(path).name in annotated.message


def test_softening_is_never_automatic_even_with_a_complete_registry(tmp_path: Path) -> None:
    registry = load_registry(_write(tmp_path, "complete: true\n" + _REGISTRY))
    (annotated,) = annotate([_finding("POST /users")], registry)
    assert annotated.severity is Severity.ERROR


def test_a_warning_is_not_promoted_or_demoted(tmp_path: Path) -> None:
    registry = load_registry(_write(tmp_path, "complete: true\n" + _REGISTRY))
    (annotated,) = annotate(
        [_finding("POST /users", Severity.WARN)], registry, adjust_severity=True
    )
    assert annotated.severity is Severity.WARN


def test_a_finding_about_the_registry_is_not_annotated_with_it(tmp_path: Path) -> None:
    """ "'legacy' names a missing operation -- affects legacy" reads as two problems."""
    registry = load_registry(_write(tmp_path, _REGISTRY))
    finding = Finding(
        rule_id="CONSUMER-UNKNOWN-OPERATION",
        severity=Severity.ERROR,
        message="x",
        operation_key="GET /users",
    )
    (out,) = annotate([finding], registry)
    assert "affects" not in out.message


# ---------------------------------------------------------------- validation


def test_an_entry_naming_an_operation_nothing_declares_is_an_error(tmp_path: Path) -> None:
    registry = load_registry(_write(tmp_path, _REGISTRY))
    findings = validate_against(registry, {"GET /users"})
    assert [f.rule_id for f in findings] == ["CONSUMER-UNKNOWN-OPERATION"]
    assert "coverage in name only" in findings[0].message


def test_an_operation_the_new_version_removed_is_not_a_typo(tmp_path: Path) -> None:
    """The case this whole module exists to report.

    Checking the registry against the new contract alone would flag every
    removed operation as a mistake in the registry, which is backwards.
    """
    registry = load_registry(_write(tmp_path, _REGISTRY))
    both_sides = {"GET /users", "DELETE /users/{id}"}
    assert validate_against(registry, both_sides) == []


# -------------------------------------------------------------- blast radius


def test_the_radius_counts_findings_per_consumer(tmp_path: Path) -> None:
    registry = load_registry(_write(tmp_path, _REGISTRY))
    findings = annotate([_finding("GET /users"), _finding("DELETE /users/{id}")], registry)
    radius = blast_radius(findings, registry)
    assert radius["by_consumer"]["mobile-v3"]["findings"] == 2
    assert radius["by_consumer"]["checkout-service"]["findings"] == 1
    assert radius["by_consumer"]["checkout-service"]["contact"] == "#payments"


def test_an_operation_with_a_break_and_no_registered_consumer_is_named(tmp_path: Path) -> None:
    """Where an incomplete registry hurts, shown rather than left to inference."""
    registry = load_registry(_write(tmp_path, _REGISTRY))
    radius = blast_radius(annotate([_finding("POST /users")], registry), registry)
    assert radius["unclaimed_operations"] == ["POST /users"]


def test_only_errors_count_toward_a_blast_radius(tmp_path: Path) -> None:
    registry = load_registry(_write(tmp_path, _REGISTRY))
    radius = blast_radius([_finding("GET /users", Severity.WARN)], registry)
    assert radius["by_consumer"] == {}


def test_the_radius_records_whether_the_registry_claimed_completeness(tmp_path: Path) -> None:
    registry = load_registry(_write(tmp_path, _REGISTRY))
    assert blast_radius([], registry)["complete"] is False


# --------------------------------------------------------------------- CLI


def test_breaking_reports_a_blast_radius(tmp_path: Path) -> None:
    code, payload, _ = _run(
        ["breaking", _V1, _V2, "--consumers", _write(tmp_path, _REGISTRY), "--json"]
    )
    assert code == EXIT_FINDINGS
    assert payload["blast_radius"]["by_consumer"]["mobile-v3"]["team"] == "mobile"


def test_the_summary_names_the_consumers(tmp_path: Path) -> None:
    code, payload, _ = _run(
        [
            "breaking",
            _V1,
            _V2,
            "--consumers",
            _write(tmp_path, _REGISTRY),
            "--summary",
            "--json",
        ]
    )
    assert code == EXIT_FINDINGS
    assert "Registered consumers affected" in payload["summary"]["markdown"]


def test_an_unreadable_registry_is_a_usage_error(tmp_path: Path) -> None:
    code, _, err = _run(["breaking", _V1, _V2, "--consumers", str(tmp_path / "nope.yaml")])
    assert code == EXIT_USAGE
    assert "error:" in err


def test_no_registry_means_no_blast_radius_key(tmp_path: Path) -> None:
    """Absent rather than empty: the run had nothing to say about consumers."""
    _, payload, _ = _run(["breaking", _V1, _V2, "--json"])
    assert "blast_radius" not in payload
