"""Four published rules could not fire, and the guard for that passed anyway.

`SEC-NO-AUTH-DECLARED`, `SEC-SECRET-IN-CONTRACT`, `SEC-SENSITIVE-FIELD` and
`SEC-CORS-WILDCARD` were in the check catalogue, in `docs/check-rules.md`, and
answerable by `apiverity explain`. The only code emitting them was
`apiverity/security/packs.py` — a rule pack no command executed. So this tool
told people it checked for a credential committed into a contract, and could
not produce that finding.

`test_every_catalogued_security_rule_is_emitted_by_something` passed the whole
time. It greps the package for `rule_id="SEC-..."`, and the dead module is in
the package: dead code satisfied the guard against dead rules. The reachability
test in `test_check_catalog.py` asks the other half of the question, and this
file asserts the outcome — that a real contract now produces each of them.

The fifth rule, `SEC-CORS-WILDCARD`, was doubly unreachable: its check read
`Operation.examples`, which this parser fills from an operation-level
`examples` key that no version of OpenAPI defines. It reads declared response
headers now, which is where a wildcard origin actually appears.
"""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
from typing import Any

import pytest

from apiverity.cli.main import main
from apiverity.core.model import Operation, OperationKind, Protocol, Response, SchemaNode, Service
from apiverity.rules.policy import DEFAULT_PACK, PolicyEngine
from apiverity.security.catalog import spec_for
from apiverity.security.packs import SECURITY_PACK

_ROOT = Path(__file__).resolve().parents[2]
_FIXTURE = _ROOT / "fixtures" / "apis" / "governance" / "openapi.yaml"

#: What the two packs are for. Each was reachable by nothing before.
NEWLY_LIVE = (
    "SEC-SECRET-IN-CONTRACT",
    "SEC-SENSITIVE-FIELD",
    "SEC-CORS-WILDCARD",
    "GOV-UNUSED-SECURITY-SCHEME",
    "GOV-MISSING-OPERATION-ID",
)


def _validate(path: Path) -> dict[str, Any]:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(io.StringIO()):
        main(["--no-config", "validate", str(path), "--json"])
    return json.loads(buffer.getvalue())


def _ids(path: Path) -> set[str]:
    return {f["rule_id"] for f in _validate(path)["findings"]}


# ------------------------------------------------------ they fire at all now


@pytest.mark.parametrize("rule_id", NEWLY_LIVE)
def test_a_rule_that_could_not_fire_now_does(rule_id: str) -> None:
    assert rule_id in _ids(_FIXTURE)


@pytest.mark.parametrize("rule_id", NEWLY_LIVE)
def test_each_one_is_explainable(rule_id: str) -> None:
    """A finding whose id `explain` does not know is a finding somebody
    suppresses rather than reads."""
    spec = spec_for(rule_id)
    assert spec is not None, f"{rule_id} fires and cannot be explained"
    assert spec.instead.strip()


def test_a_committed_credential_is_an_error() -> None:
    """The rule a reader is most likely to have believed was running."""
    finding = next(
        f for f in _validate(_FIXTURE)["findings"] if f["rule_id"] == "SEC-SECRET-IN-CONTRACT"
    )
    assert finding["severity"] == "ERROR"


# ------------------------------------------------------- what was removed


def test_the_pack_no_longer_duplicates_a_live_rule() -> None:
    """`GOV-INSECURE-SERVER` said what `SEC-HTTPS-POLICY` says and
    `GOV-DEPRECATION-METADATA` said what `LIFECYCLE-DEPRECATED-NO-SUNSET`
    says. Wiring the pack up without removing them would have made one
    plaintext server URL produce two findings for one fact."""
    assert DEFAULT_PACK.rule_ids() == [
        "GOV-UNUSED-SECURITY-SCHEME",
        "GOV-MISSING-OPERATION-ID",
    ]


def test_a_plaintext_server_produces_exactly_one_finding(tmp_path: Path) -> None:
    spec = tmp_path / "http.yaml"
    spec.write_text(
        "openapi: 3.0.3\n"
        "info: {title: t, version: '1'}\n"
        "servers: [{url: 'http://plain.example.com'}]\n"
        "paths:\n"
        "  /a:\n"
        "    get:\n"
        "      operationId: a\n"
        "      responses: {'200': {description: ok}}\n",
        encoding="utf-8",
    )
    ids = [f["rule_id"] for f in _validate(spec)["findings"]]
    assert ids.count("SEC-HTTPS-POLICY") == 1
    assert "GOV-INSECURE-SERVER" not in ids


def test_every_pack_rule_declares_the_id_its_check_emits() -> None:
    """`GOV-SUNSET-MISSING` was emitted by the check attached to the
    `GOV-DEPRECATION-METADATA` definition, so the pack emitted an id it never
    declared and `rule_ids()` did not list it. A pack whose declared ids and
    emitted ids differ cannot be checked against a catalogue by either one."""
    import inspect
    import re

    for pack in (SECURITY_PACK, DEFAULT_PACK):
        declared = set(pack.rule_ids())
        for rule in pack.rules:
            emitted = set(re.findall(r'rule_id="([A-Z][A-Z0-9-]+)"', inspect.getsource(rule.check)))
            assert emitted <= declared, (
                f"{pack.name} emits {sorted(emitted - declared)} and declares none of them"
            )


# --------------------------------------------------- the auth rule's meaning


def test_the_contract_level_auth_rule_is_contract_level() -> None:
    """It used to be per-operation and duplicated `SEC-AUTH-MISSING`, while its
    catalogue entry described the contract-level check. It now does what the
    catalogue says."""
    findings = [
        f
        for f in _validate(_ROOT / "fixtures/apis/crud/openapi.yaml")["findings"]
        if f["rule_id"] == "SEC-NO-AUTH-DECLARED"
    ]
    assert len(findings) == 1
    assert "no security schemes at all" in findings[0]["message"]


def test_it_says_how_it_relates_to_the_per_operation_findings() -> None:
    """Both fire on a contract with no auth anywhere, and a reader should not
    have to reconcile two rules about one absence."""
    finding = next(
        f
        for f in _validate(_ROOT / "fixtures/apis/crud/openapi.yaml")["findings"]
        if f["rule_id"] == "SEC-NO-AUTH-DECLARED"
    )
    assert "SEC-AUTH-MISSING" in (finding["hint"] or "")


def test_a_contract_that_declares_schemes_does_not_draw_it() -> None:
    assert "SEC-NO-AUTH-DECLARED" not in _ids(_FIXTURE)


# ------------------------------------------------------------- the CORS rule


def _with_header(value: object) -> Service:
    return Service(
        title="t",
        version="1",
        protocol=Protocol.OPENAPI,
        operations=[
            Operation(
                kind=OperationKind.HTTP,
                method="GET",
                path="/a",
                responses=[
                    Response(
                        status="200",
                        headers={"Access-Control-Allow-Origin": SchemaNode(**value)},  # type: ignore[arg-type]
                    )
                ],
            )
        ],
    )


@pytest.mark.parametrize(
    "pinned",
    [{"example": "*"}, {"default": "*"}, {"const": "*"}, {"enum": ["*"]}],
)
def test_a_wildcard_is_caught_however_the_schema_pins_it(pinned: dict[str, Any]) -> None:
    """A header schema says what the service returns in whichever of these the
    author reached for."""
    findings = PolicyEngine(packs=[SECURITY_PACK]).evaluate(_with_header(pinned))
    assert "SEC-CORS-WILDCARD" in {f.rule_id for f in findings}


@pytest.mark.parametrize(
    "pinned",
    [{"example": "https://app.example.com"}, {"enum": ["*", "https://app.example.com"]}, {}],
)
def test_a_named_origin_is_not_a_wildcard(pinned: dict[str, Any]) -> None:
    """An enum of two is a choice, not a wildcard, and an unpinned header says
    nothing about what comes back."""
    findings = PolicyEngine(packs=[SECURITY_PACK]).evaluate(_with_header(pinned))
    assert "SEC-CORS-WILDCARD" not in {f.rule_id for f in findings}


def test_the_header_name_is_matched_case_insensitively() -> None:
    service = _with_header({"example": "*"})
    service.operations[0].responses[0].headers = {
        "access-control-allow-origin": SchemaNode(example="*")
    }
    findings = PolicyEngine(packs=[SECURITY_PACK]).evaluate(service)
    assert "SEC-CORS-WILDCARD" in {f.rule_id for f in findings}


# -------------------------------------------------------- failure isolation


def test_one_bad_rule_does_not_take_the_run_down() -> None:
    """`PolicyEngine` catches per rule. Now that it runs on every `validate`,
    that stops being a nicety: a rule raising on one odd contract would
    otherwise fail the command rather than report."""
    from apiverity.core.model import Severity
    from apiverity.rules.policy import RuleDefinition, RulePack

    def _boom(_svc: Service) -> list[Any]:
        raise RuntimeError("nope")

    pack = RulePack(
        name="broken",
        version="1.0.0",
        description="",
        rules=(
            RuleDefinition(
                rule_id="X-BOOM", severity=Severity.WARN, rationale="", remediation="", check=_boom
            ),
        ),
    )
    findings = PolicyEngine(packs=[pack]).evaluate(_with_header({}))
    assert [f.rule_id for f in findings] == ["POLICY-RULE-CRASHED"]
    assert "RuntimeError" in findings[0].message
