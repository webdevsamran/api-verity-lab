"""What a contract is assembled from, treated as a dependency graph.

`specs/bundle.py` has always recorded every external reference it resolved and
every source it read. The OpenAPI parser copied the source list to
`self.sources`. **Nothing read either.** So a run that pulled four files
reported a `contract_hash` for the entry document and said nothing about the
other three, and a `$ref` to somebody else's server -- a build-time dependency
on a host nobody in the repository controls -- appeared in no report at all.

`Service.dependencies` carries the declared references now, and these are the
three things worth saying about them.
"""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
from typing import Any

import pytest

from apiverity.cli.main import main
from apiverity.core.model import Protocol, Service
from apiverity.security.dependencies import (
    check_dependencies,
    escapes_tree,
    is_pinned,
    is_remote,
)
from apiverity.specs.loader import detect_and_load

_ROOT = Path(__file__).resolve().parents[2]
_FIXTURE = "fixtures/apis/supplychain/openapi.yaml"
_MULTIFILE = "fixtures/apis/multifile/openapi.yaml"
_SINGLE = "fixtures/apis/crud/openapi.yaml"


def _service(**kwargs: Any) -> Service:
    return Service(title="t", version="1.0.0", protocol=Protocol.OPENAPI, **kwargs)


# ------------------------------------------------------ what the model carries


def test_a_contract_records_the_references_it_declares() -> None:
    service, _findings, _plugin = detect_and_load(str(_ROOT / _FIXTURE))
    assert service.dependencies == [
        "../shared/error.yaml",
        "./schemas/order.yaml",
        "https://schemas.example.com/problem.yaml",
        "https://schemas.example.com/v2.1.0/money.yaml",
    ]


def test_a_single_file_contract_declares_none() -> None:
    service, _findings, _plugin = detect_and_load(str(_ROOT / _SINGLE))
    assert service.dependencies == []


def test_the_references_are_what_the_document_wrote_not_where_they_resolved() -> None:
    """`../shared/error.yaml` is what a reader can act on. The resolved
    absolute path is a fact about this checkout."""
    service, _findings, _plugin = detect_and_load(str(_ROOT / _MULTIFILE))
    assert all(not Path(ref).is_absolute() for ref in service.dependencies)
    assert "../shared/customer.yaml" in service.dependencies


def test_a_refused_remote_reference_is_still_a_dependency() -> None:
    """The one that matters most, and the one a list built from `rewritten`
    would have missed: a remote ref returns before it is rewritten when
    `--allow-remote-refs` is off, and that is exactly the run where the schema
    behind it is absent from the model.
    """
    service, findings, _plugin = detect_and_load(str(_ROOT / _FIXTURE))
    assert "SPEC-REF-REMOTE-REFUSED" in {f.rule_id for f in findings}
    assert any(is_remote(ref) for ref in service.dependencies)


# ------------------------------------------------------------------ the rules


def test_a_remote_reference_is_reported() -> None:
    findings = check_dependencies(_service(dependencies=["https://x.example.com/v1/a.yaml"]))
    assert [f.rule_id for f in findings] == ["SEC-DEP-REMOTE"]


def test_an_unpinned_remote_reference_is_reported_as_well() -> None:
    findings = check_dependencies(_service(dependencies=["https://x.example.com/a.yaml"]))
    assert [f.rule_id for f in findings] == ["SEC-DEP-REMOTE", "SEC-DEP-UNPINNED"]


@pytest.mark.parametrize(
    "url",
    [
        "https://x.example.com/v2/a.yaml",
        "https://x.example.com/1.2.3/a.yaml",
        "https://x.example.com/schemas/a-v1.4.yaml",
        "https://x.example.com/3f9a1c7/a.yaml",
        "https://x.example.com/2026-04-15/a.yaml",
    ],
)
def test_a_pinned_url_is_one_anybody_could_refetch(url: str) -> None:
    assert is_pinned(url)
    assert [f.rule_id for f in check_dependencies(_service(dependencies=[url]))] == [
        "SEC-DEP-REMOTE"
    ]


def test_a_version_in_the_hostname_is_not_a_pin() -> None:
    """`api.v2.example.com/schema.yaml` still serves whatever is there today,
    and counting the host would call the whole class pinned."""
    assert not is_pinned("https://api.v2.example.com/schema.yaml")


def test_a_reference_that_climbs_out_of_the_tree_is_reported() -> None:
    findings = check_dependencies(_service(dependencies=["../../shared/error.yaml"]))
    assert [f.rule_id for f in findings] == ["SEC-DEP-OUTSIDE-TREE"]


@pytest.mark.parametrize(
    ("reference", "escapes"),
    [
        ("./schemas/a.yaml", False),
        ("schemas/a.yaml", False),
        ("../shared/a.yaml", True),
        ("./a/../../b.yaml", True),
        ("./a/../b.yaml", False),
        ("https://x.example.com/../a.yaml", False),
    ],
)
def test_what_counts_as_climbing_out(reference: str, escapes: bool) -> None:
    assert escapes_tree(reference) is escapes


def test_a_sibling_reference_is_not_reported() -> None:
    """A contract with a `schemas/` directory beside it is the normal shape,
    and reporting it on every run would be noise in the reports of the people
    who least need it."""
    assert check_dependencies(_service(dependencies=["./schemas/order.yaml"])) == []


def test_a_contract_with_no_external_references_produces_nothing() -> None:
    assert check_dependencies(_service()) == []


def test_there_is_no_integrity_rule_and_the_module_says_why() -> None:
    """`$ref` has no digest and there is no lockfile for it. A checksum sidecar
    only this tool understands would be a mechanism nobody else honours, so the
    advice is to pin the URL instead."""
    import apiverity.security.dependencies as module

    assert "no integrity rule" in (module.__doc__ or "")
    assert not any(
        "INTEGRITY" in rule
        for rule in ("SEC-DEP-REMOTE", "SEC-DEP-UNPINNED", "SEC-DEP-OUTSIDE-TREE")
    )


# ------------------------------------------------------------ through validate


def _run(argv: list[str]) -> tuple[int, dict[str, Any]]:
    out = io.StringIO()
    code = 0
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        try:
            code = main(argv)
        except SystemExit as stop:
            code = int(stop.code or 0)
    try:
        return code, json.loads(out.getvalue())
    except ValueError:
        return code, {}


def test_validate_reports_the_dependency_surface() -> None:
    _code, payload = _run(["--no-config", "validate", _FIXTURE, "--json"])
    rules = [f["rule_id"] for f in payload["findings"]]
    assert rules.count("SEC-DEP-REMOTE") == 2
    assert rules.count("SEC-DEP-UNPINNED") == 1
    assert rules.count("SEC-DEP-OUTSIDE-TREE") == 1


def test_the_artifact_names_what_the_contract_was_assembled_from() -> None:
    """`contract_hash` covers the entry document only. Without this, an
    artifact for a four-file contract named one file."""
    _code, payload = _run(["--no-config", "validate", _FIXTURE, "--json"])
    assert len(payload["dependencies"]) == 4
    assert payload["contract_hash"] != "0" * 64


def test_a_single_file_contract_carries_no_dependency_block() -> None:
    """An empty list on every artifact is a key readers learn to ignore."""
    _code, payload = _run(["--no-config", "validate", _SINGLE, "--json"])
    assert "dependencies" not in payload


def test_the_rules_are_catalogued_and_explainable() -> None:
    from apiverity.rules.check_catalog import catalog

    known = catalog()
    for rule in ("SEC-DEP-REMOTE", "SEC-DEP-UNPINNED", "SEC-DEP-OUTSIDE-TREE"):
        assert rule in known, rule
        assert known[rule].produced_by == "validate"
        assert known[rule].family == "Supply chain"
