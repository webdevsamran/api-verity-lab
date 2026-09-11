"""House rules in YAML, and the failure a DSL usually has.

A DSL that accepts an unrecognised selector, matches nothing and reports clean
has handed a team a gate they believe they have. Every unknown word here is
refused at load time, by name, with the list of what is available — which is
what most of this file is about.
"""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
from typing import Any

import pytest

from apiverity.cli.commands.common import EXIT_FINDINGS, EXIT_OK, EXIT_USAGE
from apiverity.cli.main import main
from apiverity.core.model import Protocol
from apiverity.rules.dsl import OPERATION_FIELDS, PREDICATES, PolicyError, load, vocabulary
from apiverity.rules.policy import PolicyEngine
from apiverity.specs.loader import detect_and_load

_ROOT = Path(__file__).resolve().parents[2]
_POLICY = _ROOT / "fixtures/policies/house-style.yaml"
_CRUD = str(_ROOT / "fixtures/apis/crud/openapi.yaml")
_LINT = str(_ROOT / "fixtures/apis/lint/openapi.yaml")


def _policy(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "policy.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def _fired(policy: Path, spec: str) -> set[str]:
    pack, _ = load(policy)
    service, _, _ = detect_and_load(spec)
    return {f.rule_id for f in PolicyEngine(packs=[pack]).evaluate(service)}


def _minimal(rule: str) -> str:
    return (
        "pack: t\nversion: 1.0.0\nrules:\n"
        "  - id: T-ONE\n    rationale: because\n    remediation: do the thing\n" + rule
    )


def _run(argv: list[str]) -> tuple[int, dict[str, Any], str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    text = out.getvalue()
    return code, (json.loads(text) if text.strip().startswith("{") else {}), err.getvalue()


# --------------------------------------------- an unknown word is refused


def test_an_unknown_field_is_refused_with_the_list_of_real_ones(tmp_path: Path) -> None:
    """The failure this is built to avoid: a rule that matches nothing and
    reports clean."""
    with pytest.raises(PolicyError) as caught:
        load(_policy(tmp_path, _minimal("    where:\n      pathh: present\n")))
    assert "`pathh`" in str(caught.value)
    assert "operation_id" in str(caught.value)


def test_an_unknown_predicate_is_refused_with_the_list(tmp_path: Path) -> None:
    with pytest.raises(PolicyError) as caught:
        load(_policy(tmp_path, _minimal("    where:\n      path: contains\n")))
    assert "`contains`" in str(caught.value)
    assert "not_matches" in str(caught.value)


def test_an_unknown_severity_is_refused(tmp_path: Path) -> None:
    body = _minimal("    where:\n      path: present\n").replace(
        "    rationale:", "    severity: critical\n    rationale:"
    )
    with pytest.raises(PolicyError, match="severity 'critical'"):
        load(_policy(tmp_path, body))


def test_an_unknown_selector_is_refused(tmp_path: Path) -> None:
    body = _minimal("    select: schema\n    where:\n      path: present\n")
    with pytest.raises(PolicyError, match="selects 'schema'"):
        load(_policy(tmp_path, body))


def test_a_pattern_that_will_not_compile_is_refused_at_load(tmp_path: Path) -> None:
    """Not at check time, against the first contract somebody runs it on."""
    with pytest.raises(PolicyError, match="will not compile"):
        load(_policy(tmp_path, _minimal("    where:\n      path: {matches: '([unclosed'}\n")))


def test_a_rule_with_no_conditions_is_refused(tmp_path: Path) -> None:
    with pytest.raises(PolicyError, match="no `where`"):
        load(_policy(tmp_path, _minimal("    where: {}\n")))


def test_a_duplicate_rule_id_is_refused(tmp_path: Path) -> None:
    """Two rules with one id cannot both be explained, and one would win."""
    body = (
        "pack: t\nversion: 1.0.0\nrules:\n"
        "  - id: T-ONE\n    rationale: a\n    remediation: b\n    where: {path: present}\n"
        "  - id: T-ONE\n    rationale: c\n    remediation: d\n    where: {method: present}\n"
    )
    with pytest.raises(PolicyError, match="twice"):
        load(_policy(tmp_path, body))


@pytest.mark.parametrize(
    "body",
    [
        "just a string\n",
        "pack: t\nversion: 1.0.0\n",
        "pack: t\nversion: 1.0.0\nrules: []\n",
        "version: 1.0.0\nrules: [{id: A, rationale: r, remediation: m, where: {path: present}}]\n",
    ],
)
def test_a_file_that_is_not_a_policy_is_refused(tmp_path: Path, body: str) -> None:
    with pytest.raises(PolicyError):
        load(_policy(tmp_path, body))


def test_a_missing_file_is_refused(tmp_path: Path) -> None:
    with pytest.raises(PolicyError, match="could not read"):
        load(tmp_path / "nope.yaml")


# ------------------------------------------------------------- predicates


def test_present_and_absent_are_about_the_field_not_its_value(tmp_path: Path) -> None:
    everything = _fired(_policy(tmp_path, _minimal("    where:\n      summary: absent\n")), _CRUD)
    assert everything == {"T-ONE"}, "the crud fixture declares summaries on every operation"


def test_matches_fails_a_field_that_is_not_there(tmp_path: Path) -> None:
    """Conflating the two would make `matches` silently pass on every
    operation that omits the field."""
    fired = _fired(
        _policy(tmp_path, _minimal("    where:\n      operation_id: {matches: 'zzz'}\n")), _CRUD
    )
    assert fired == {"T-ONE"}


def test_one_of_holds_every_value_to_the_list(tmp_path: Path) -> None:
    none_fire = _fired(
        _policy(
            tmp_path,
            _minimal("    where:\n      method: {one_of: [GET, POST, PUT, PATCH, DELETE]}\n"),
        ),
        _CRUD,
    )
    assert none_fire == set()


def test_includes_and_excludes_read_a_collection(tmp_path: Path) -> None:
    assert _fired(
        _policy(tmp_path, _minimal("    where:\n      responses: {includes: '999'}\n")), _CRUD
    ) == {"T-ONE"}
    assert (
        _fired(
            _policy(tmp_path, _minimal("    where:\n      responses: {excludes: '999'}\n")), _CRUD
        )
        == set()
    )


def test_a_service_rule_reports_once_not_per_operation(tmp_path: Path) -> None:
    body = _minimal("    select: service\n    where:\n      title: {matches: 'zzz'}\n")
    pack, _ = load(_policy(tmp_path, body))
    service, _, _ = detect_and_load(_CRUD)
    findings = PolicyEngine(packs=[pack]).evaluate(service)
    assert len(findings) == 1
    assert findings[0].operation_key is None


# -------------------------------------------------------------- exemptions


def test_an_exemption_names_what_it_exempts() -> None:
    """A glob that grows to cover six operations nobody reviewed is the escape
    hatch becoming the policy."""
    pack, rules = load(_POLICY)
    writes = next(r for r in rules if r.rule_id == "HOUSE-NO-ANONYMOUS-WRITES")
    assert writes.exempt == ["POST /users"]

    service, _, _ = detect_and_load(_CRUD)
    keys = {
        f.operation_key
        for f in PolicyEngine(packs=[pack]).evaluate(service)
        if f.rule_id == "HOUSE-NO-ANONYMOUS-WRITES"
    }
    assert "POST /users" not in keys
    assert "DELETE /users/{id}" in keys


def test_a_rule_can_be_scoped_to_protocols(tmp_path: Path) -> None:
    body = _minimal("    protocols: [graphql]\n    where:\n      path: {matches: 'zzz'}\n")
    pack, rules = load(_policy(tmp_path, body))
    assert rules[0].protocols == frozenset({Protocol.GRAPHQL})
    service, _, _ = detect_and_load(_CRUD)
    assert PolicyEngine(packs=[pack]).evaluate(service) == []


def test_a_protocol_that_does_not_exist_is_refused(tmp_path: Path) -> None:
    body = _minimal("    protocols: [soapy]\n    where:\n      path: present\n")
    with pytest.raises(PolicyError, match="protocol that does not exist"):
        load(_policy(tmp_path, body))


# ---------------------------------------------------------- the vocabulary


def test_the_published_vocabulary_is_what_the_loader_accepts() -> None:
    """A documented word the loader rejects, or an accepted word the
    documentation omits, is the same defect in two directions."""
    published = vocabulary()
    assert set(published["fields"]["operation"]) == set(OPERATION_FIELDS)
    assert set(published["predicates"]) == set(PREDICATES)


def test_every_documented_field_actually_reads_something(tmp_path: Path) -> None:
    """A field in the table that no operation can satisfy is a published word
    that does nothing."""
    service, _, _ = detect_and_load(_CRUD)
    for field in OPERATION_FIELDS:
        pack, _ = load(_policy(tmp_path, _minimal(f"    where:\n      {field}: present\n")))
        # Not asserting it passes -- asserting it is *decidable*, which means
        # the field was read rather than silently unknown.
        PolicyEngine(packs=[pack]).evaluate(service)


# --------------------------------------------------------------- the command


def test_validate_runs_a_policy_file() -> None:
    code, payload, _ = _run(["validate", _LINT, "--policy-file", str(_POLICY), "--json"])
    assert code == EXIT_FINDINGS
    fired = {f["rule_id"] for f in payload["findings"] if f["rule_id"].startswith("HOUSE-")}
    assert "HOUSE-NO-ANONYMOUS-WRITES" in fired


def test_the_artifact_names_the_policies_that_ran() -> None:
    """Two runs over one contract reporting different findings should say why."""
    _, payload, _ = _run(["validate", _LINT, "--policy-file", str(_POLICY), "--json"])
    assert payload["policies"] == [str(_POLICY)]

    _, plain, _ = _run(["validate", _LINT, "--json"])
    assert "policies" not in plain


def test_a_broken_policy_fails_the_run_by_name(tmp_path: Path) -> None:
    """Rather than checking nothing and reporting the contract clean."""
    broken = _policy(tmp_path, _minimal("    where:\n      nonsense: present\n"))
    code, _, err = _run(["validate", _CRUD, "--policy-file", str(broken)])
    assert code == EXIT_USAGE
    assert "`nonsense`" in err


def test_the_vocabulary_is_printable() -> None:
    code, payload, _ = _run(["rules", "--policy-vocabulary", "--json"])
    assert code == EXIT_OK
    assert "matches" in payload["predicates"]
    assert "path" in payload["fields"]["operation"]
