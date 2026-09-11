"""The parser's own findings, and the setting that never reached them.

These are the first findings anybody sees. A `$ref` that will not resolve, a
Swagger 2.0 file whose OAuth metadata cannot survive conversion, a WSDL
construct the model does not carry — every one was reported and none could be
looked up. `apiverity explain SPEC-REF-UNRESOLVED` answered *"no rule with id
..."* about a rule the loader emits on a bad first run, which is the worst
place in the tool to have that gap: a reader whose first command produced a
finding they could not explain has no reason to run a second one.

The second half is the same defect wearing different clothes.
`.apiverity.yaml`'s `severity_overrides` reached `breaking` and nothing else, so
a project that wrote `SEC-AUTH-MISSING: INFO` to stop `validate` failing got a
setting the config validator accepted, the published schema allowed, and no
command applied.
"""

from __future__ import annotations

import ast
import contextlib
import io
import json
from pathlib import Path
from typing import Any

import pytest

from apiverity.cli.main import main
from apiverity.rules.check_catalog import catalog as check_catalog
from apiverity.specs.spec_catalog import ASYNCAPI_CATALOG, SPEC_CATALOG, SWAGGER2_CATALOG

_ROOT = Path(__file__).resolve().parents[2]
_FIXTURE = _ROOT / "fixtures" / "apis" / "crud" / "openapi.yaml"

_FAMILIES = {
    "SPEC": SPEC_CATALOG,
    "SWAGGER2": SWAGGER2_CATALOG,
    "ASYNCAPI": ASYNCAPI_CATALOG,
}

#: Where the parsers live. Scanned in both directions, so an entry for a rule
#: nothing emits fails as loudly as a rule with no entry.
_SOURCES = (
    "apiverity/specs/openapi/parser.py",
    "apiverity/specs/bundle.py",
    "apiverity/specs/swagger2.py",
    "apiverity/specs/asyncapi.py",
    "apiverity/specs/wsdl.py",
    "apiverity/specs/graphql/__init__.py",
    "apiverity/specs/loader.py",
    "apiverity/core/canonical.py",
    "apiverity/rules/spectral.py",
)


def _run(argv: list[str], cwd: Path | None = None) -> tuple[int, dict[str, Any]]:
    import os

    previous = Path.cwd()
    if cwd is not None:
        os.chdir(cwd)
    try:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main([*argv, "--json"])
        return code, json.loads(out.getvalue())
    finally:
        os.chdir(previous)


# -- the entries ----------------------------------------------------------


@pytest.mark.parametrize("prefix", sorted(_FAMILIES))
def test_every_entry_is_in_the_merged_catalogue(prefix: str) -> None:
    merged = check_catalog()
    for rule_id in _FAMILIES[prefix]:
        assert rule_id in merged


@pytest.mark.parametrize("prefix", sorted(_FAMILIES))
def test_every_entry_says_what_to_do(prefix: str) -> None:
    for rule_id, spec in _FAMILIES[prefix].items():
        assert spec.rule_id == rule_id
        assert len(spec.description.strip()) > 20, rule_id
        assert len(spec.instead.strip()) > 20, rule_id
        assert spec.family != "Security", f"{rule_id} is filed under the default family"


def test_the_entries_cover_exactly_what_the_parsers_emit() -> None:
    emitted: set[str] = set()
    for name in _SOURCES:
        tree = ast.parse((_ROOT / name).read_text(encoding="utf-8"))
        docstrings = {
            ast.get_docstring(node, clean=False)
            for node in ast.walk(tree)
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        }
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            value = node.value
            if value in docstrings:
                continue
            if value.split("-")[0] in _FAMILIES and "-" in value and value == value.upper():
                emitted.add(value)

    catalogued = set().union(*(set(family) for family in _FAMILIES.values()))
    assert not emitted - catalogued, f"emitted and not catalogued: {sorted(emitted - catalogued)}"
    assert not catalogued - emitted, f"catalogued and not emitted: {sorted(catalogued - emitted)}"


@pytest.mark.parametrize(
    "rule_id",
    [
        "SPEC-REF-UNRESOLVED",
        "SPEC-OPID-DUPLICATE",
        "SPEC-WSDL-ENCODED",
        "SWAGGER2-SERVER-SYNTHESIZED",
        "ASYNCAPI-OPERATION-BAD-ACTION",
    ],
)
def test_explain_answers_for_a_rule_the_parser_emits(rule_id: str) -> None:
    code, payload = _run(["explain", rule_id])
    assert code == 0
    assert payload["rule_id"] == rule_id
    assert payload["instead"]
    assert payload["group"] != "Other"
    assert payload["documentation"] == "docs/check-rules.md"


def test_the_spec_prefix_resolves_to_three_different_groups() -> None:
    """`SPEC-` covers reference resolution, document structure and WSDL. One
    heading over all twenty-four would help nobody, and `explain` would give
    the same unhelpful answer for a dangling `$ref` and an encoded SOAP body."""
    groups = {
        rule: _run(["explain", rule])[1]["group"]
        for rule in ("SPEC-REF-CYCLE", "SPEC-OP-DUPLICATE", "SPEC-WSDL-NO-SERVICE")
    }
    assert len(set(groups.values())) == 3, groups


# -- the setting that reached nothing --------------------------------------


def test_validate_applies_the_configs_severity_overrides(
    tmp_path: Path, use_project_config: Any
) -> None:
    """Both directions, because one alone could be a coincidence: a rule
    demoted out of the error count and a rule promoted into it."""
    import shutil

    shutil.copy(_FIXTURE, tmp_path / "openapi.yaml")
    config = tmp_path / ".apiverity.yaml"
    config.write_text(
        "version: 1\nseverity_overrides:\n"
        "  SEC-AUTH-MISSING: INFO\n"
        "  SEC-NO-AUTH-DECLARED: ERROR\n",
        encoding="utf-8",
    )
    # `conftest.isolate_project_config` blanks `find_config` for every test, so
    # a test about config handling has to opt back in.
    use_project_config(config)

    _, payload = _run(["validate", "openapi.yaml"], cwd=tmp_path)
    severities = {f["rule_id"]: f["severity"] for f in payload["findings"]}
    assert severities["SEC-AUTH-MISSING"] == "INFO"
    assert severities["SEC-NO-AUTH-DECLARED"] == "ERROR"
    # And the promotion reached the exit-code arithmetic, not only the display.
    assert payload["errors"] >= 1


def test_a_rule_nobody_overrode_keeps_its_catalogue_severity(
    tmp_path: Path, use_project_config: Any
) -> None:
    """The other half. An override that changed everything would be worse than
    one that changed nothing."""
    import shutil

    shutil.copy(_FIXTURE, tmp_path / "openapi.yaml")
    _, before = _run(["validate", "openapi.yaml"], cwd=tmp_path)

    config = tmp_path / ".apiverity.yaml"
    config.write_text(
        "version: 1\nseverity_overrides:\n  SEC-AUTH-MISSING: INFO\n", encoding="utf-8"
    )
    use_project_config(config)
    _, after = _run(["validate", "openapi.yaml"], cwd=tmp_path)

    untouched_before = {
        f["rule_id"]: f["severity"]
        for f in before["findings"]
        if f["rule_id"] != "SEC-AUTH-MISSING"
    }
    untouched_after = {
        f["rule_id"]: f["severity"] for f in after["findings"] if f["rule_id"] != "SEC-AUTH-MISSING"
    }
    assert untouched_after == untouched_before
