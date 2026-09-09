"""Findings mapped onto published security frameworks.

The failure mode this guards is not a wrong mapping, it is a *flattering* one.
A report that lists the three controls it hit and stays silent about the other
seven reads as a clean bill of health for all ten, which is the easiest way for
a governance tool to mislead the person relying on it. So the tests are mostly
about what the report is forced to say when it has nothing.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from apiverity.reports.compliance import (
    FRAMEWORKS,
    Framework,
    assess,
    producing_commands,
    render_markdown,
    report,
)

_ROOT = Path(__file__).resolve().parents[2]


def _artifact(command: str, *rule_ids: str) -> dict[str, Any]:
    return {
        "tool": "apiverity",
        "command": command,
        "spec": "tools.mcp.json",
        "findings": [
            {"rule_id": rule_id, "severity": "ERROR", "message": "x"} for rule_id in rule_ids
        ],
    }


#: A whole string literal shaped like a rule id: screaming-kebab, at least two
#: segments. Matching the literal rather than `rule_id=` is deliberate --
#: `mcp_poisoning.py` passes ids positionally to a helper, and a scan keyed on
#: the keyword silently found none of them while the test still passed.
_RULE_LITERAL = re.compile(r'"([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+)"')


def _known_rule_ids() -> set[str]:
    """Every rule id the engine can emit, read out of the source.

    The catalogue alone is not enough: it holds breaking rules, and half the
    families here (`MCP-POISON-`, `MCP-AUTH-`, `SEC-`) are emitted directly.
    """
    from apiverity.rules.breaking import CATALOG

    found = set(CATALOG)
    for path in (_ROOT / "apiverity").rglob("*.py"):
        found.update(
            literal
            for literal in _RULE_LITERAL.findall(path.read_text(encoding="utf-8"))
            if len(literal) >= 8
        )
    return found


ALL = pytest.mark.parametrize("framework", sorted(FRAMEWORKS.values(), key=lambda f: f.key))


# ------------------------------------------------------------ the frameworks


@ALL
def test_every_framework_has_ten_controls(framework: Framework) -> None:
    assert len(framework.controls) == 10


@ALL
def test_control_ids_are_the_published_numbering(framework: Framework) -> None:
    prefix = {"owasp-mcp": "MCP", "owasp-asi": "ASI", "owasp-api": "API"}[framework.key]
    width = 1 if prefix == "API" else 2
    expected = [f"{prefix}{i:0{width}d}" for i in range(1, 11)]
    assert [c.id for c in framework.controls] == expected


@ALL
def test_every_framework_cites_a_source_and_when_it_was_read(framework: Framework) -> None:
    """A framework quoted from memory is the fabrication this repo fixes twice a month."""
    assert framework.url.startswith("https://")
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", framework.read_on)
    assert framework.version


@ALL
def test_no_control_is_an_unexplained_blank(framework: Framework) -> None:
    """Rules, or a stated reason there are none. Never neither."""
    silent = [c.id for c in framework.controls if not c.rules and not c.limitation]
    assert not silent, f"{silent} have no mapping and no explanation of why not"


@ALL
def test_every_mapped_prefix_matches_a_rule_the_engine_can_emit(framework: Framework) -> None:
    """A mapping to a renamed rule promises coverage that cannot happen."""
    known = _known_rule_ids()
    dangling = [
        (c.id, prefix)
        for c in framework.controls
        for prefix in c.rules
        if not any(rule.startswith(prefix) for rule in known)
    ]
    assert not dangling, f"mapped to rule prefixes nothing emits: {dangling}"


@ALL
def test_every_mapped_prefix_names_a_command_that_produces_it(framework: Framework) -> None:
    """Otherwise `not-exercised` cannot tell the reader what to run."""
    orphans = [
        (c.id, prefix)
        for c in framework.controls
        for prefix in c.rules
        if not producing_commands(prefix)
    ]
    assert not orphans, f"no command is known to produce: {orphans}"


# ---------------------------------------------------------------- assessment


def test_a_control_with_evidence_reports_it() -> None:
    control = FRAMEWORKS["owasp-mcp"].controls[2]
    entry = assess(control, _artifact("validate", "MCP-POISON-INVISIBLE-TEXT"))
    assert entry["state"] == "findings"
    assert entry["control"] == "MCP03"


def test_a_control_whose_rules_ran_and_found_nothing_is_clear() -> None:
    control = FRAMEWORKS["owasp-mcp"].controls[2]
    assert assess(control, _artifact("validate"))["state"] == "clear"


def test_a_control_whose_rules_could_not_have_run_is_not_clear() -> None:
    """The distinction an audit exists to remove.

    `validate` cannot produce an `MCP-AUTH-` finding, so silence about
    authentication from a `validate` artifact is not evidence of anything.
    """
    control = next(c for c in FRAMEWORKS["owasp-mcp"].controls if c.id == "MCP07")
    entry = assess(control, _artifact("validate"))
    assert entry["state"] == "not-exercised"
    assert "apiverity drift" in entry["detail"]


def test_the_same_control_is_clear_when_the_right_command_ran() -> None:
    control = next(c for c in FRAMEWORKS["owasp-mcp"].controls if c.id == "MCP07")
    assert assess(control, _artifact("drift"))["state"] == "clear"


def test_a_control_this_tool_cannot_see_says_why() -> None:
    control = next(c for c in FRAMEWORKS["owasp-mcp"].controls if c.id == "MCP05")
    entry = assess(control, _artifact("validate"))
    assert entry["state"] == "not-assessable"
    assert "inside the server" in entry["detail"]


@ALL
def test_every_control_appears_whatever_the_artifact_says(framework: Framework) -> None:
    """Silence about a control is the misleading part, so silence is not allowed."""
    result = report(framework, _artifact("validate"))
    assert len(result["controls"]) == 10
    assert sum(result["counts"].values()) == 10


# ------------------------------------------------------------------ rendering


@ALL
def test_the_rendered_report_lists_all_ten_controls(framework: Framework) -> None:
    text = render_markdown(framework, _artifact("validate"))
    for control in framework.controls:
        assert control.id in text


def test_the_rendered_report_disclaims_an_endorsement() -> None:
    """The control names are OWASP's. The mapping is this project's reading."""
    text = render_markdown(FRAMEWORKS["owasp-asi"], _artifact("validate"))
    assert "not endorsed by OWASP" in text


def test_the_rendered_report_refuses_to_let_clear_mean_secure() -> None:
    text = render_markdown(FRAMEWORKS["owasp-api"], _artifact("validate"))
    assert "not a statement that the system is secure" in text


def test_the_rendered_report_cites_the_source_and_the_date_it_was_read() -> None:
    text = render_markdown(FRAMEWORKS["owasp-mcp"], _artifact("validate"))
    assert "owasp.org/www-project-mcp-top-10" in text
    assert "read 2026-09-09" in text


def test_findings_are_quoted_under_the_control_they_are_evidence_for() -> None:
    text = render_markdown(FRAMEWORKS["owasp-mcp"], _artifact("validate", "MCP-POISON-CROSS-TOOL"))
    assert "### MCP06 Intent Flow Subversion" in text
    assert "`MCP-POISON-CROSS-TOOL`" in text


def test_one_finding_can_be_evidence_for_several_controls() -> None:
    """Deliberate: MCP03 and MCP06 are different risks with a shared symptom."""
    result = report(FRAMEWORKS["owasp-mcp"], _artifact("validate", "MCP-POISON-INSTRUCTION"))
    hit = [e["control"] for e in result["controls"] if e["state"] == "findings"]
    assert hit == ["MCP03", "MCP06"]


# ---------------------------------------------------------------------- wiring


@pytest.mark.parametrize("fmt", ["owasp-mcp", "owasp-asi", "owasp-api"])
def test_each_framework_is_reachable_as_a_report_format(fmt: str) -> None:
    from apiverity.reports.renderers import RENDERERS

    assert fmt in RENDERERS
    assert RENDERERS[fmt](_artifact("validate")).startswith("# OWASP")


def test_a_renderer_does_not_raise_on_a_bundle_with_no_findings_key() -> None:
    """Renderers must survive an artifact written by an older build."""
    from apiverity.reports.renderers import RENDERERS

    assert RENDERERS["owasp-mcp"]({"command": "validate"})


def test_the_published_mapping_document_matches_the_code() -> None:
    """`--check` runs in CI; failing here too is faster feedback."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "generate_compliance_map", _ROOT / "scripts" / "generate_compliance_map.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    committed = (_ROOT / "docs" / "compliance-mapping.md").read_text(encoding="utf-8")
    assert committed == module.render(), "run scripts/generate_compliance_map.py"
