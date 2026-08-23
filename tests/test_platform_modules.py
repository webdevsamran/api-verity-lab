"""Tests for reports renderers, artifact envelope, auth profiles,
plugin builtins and the export bundle."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from apiverity.core.artifact import ArtifactMeta, contract_hash, enrich
from apiverity.plugins.builtins import (
    core_rules,
    httpx_transport,
    report_exporters,
    schema_case_generator,
    security_checks,
)
from apiverity.reports.renderers import RENDERERS
from apiverity.traffic.auth import (
    AuthKind,
    AuthProfile,
    AuthProfileSet,
    resolve_headers,
    resolve_verify,
)

SAMPLE = {
    "tool": "apiverity",
    "command": "breaking",
    "findings": [
        {"rule_id": "BRK-OP-REMOVED", "severity": "ERROR", "message": "op removed"},
        {"rule_id": "BRK-DEPRECATION-ADDED", "severity": "WARN", "message": "deprecated"},
    ],
}


def test_renderers_all_formats() -> None:
    for fmt, render in RENDERERS.items():
        out = render(SAMPLE)
        assert isinstance(out, str) and len(out) > 20, fmt
    assert "BRK-OP-REMOVED" in RENDERERS["markdown"](SAMPLE)
    assert "<html>" in RENDERERS["html"](SAMPLE).lower()
    sarif = json.loads(RENDERERS["sarif"](SAMPLE))
    assert sarif["version"] == "2.1.0"
    assert sarif["runs"][0]["results"][0]["ruleId"] == "BRK-OP-REMOVED"
    junit = RENDERERS["junit"]({"total": 3, "failed": 1})
    assert 'tests="3"' in junit and 'failures="1"' in junit


def test_terminal_renderer_skips_nested() -> None:
    out = RENDERERS["terminal"](SAMPLE)
    assert "breaking:" in out
    assert "[ERROR] BRK-OP-REMOVED op removed" in out


def test_contract_hash_stable_and_missing() -> None:
    p = Path("fixtures/apis/crud/openapi.yaml")
    h1 = contract_hash(str(p))
    h2 = contract_hash(str(p))
    assert h1 == h2 and len(h1) == 64
    assert contract_hash("does/not/exist.yaml") == "0" * 64
    assert contract_hash(None) == "0" * 64


def test_enrich_adds_metadata() -> None:
    payload = enrich({"tool": "apiverity", "command": "validate"}, spec_path=None)
    assert payload["result_schema_version"] == 1
    assert payload["tool_version"]
    assert payload["redaction"]["applied"] is True
    meta = ArtifactMeta()
    assert meta.contract_hash == "0" * 64


def test_auth_bearer_and_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("T_TOKEN", "tok-123")
    monkeypatch.setenv("T_KEY", "key-456")
    bearer = AuthProfile(name="b", kind=AuthKind.bearer, token_env="T_TOKEN")
    assert resolve_headers(bearer) == {"Authorization": "Bearer tok-123"}
    api_key = AuthProfile(name="k", kind=AuthKind.api_key, key_env="T_KEY")
    headers = resolve_headers(api_key)
    assert headers == {"X-Api-Key": "key-456"}
    # references only — no secret values in the summary
    summary = str(bearer.redacted_summary())
    assert "tok-123" not in summary


def test_auth_basic_and_missing_env(monkeypatch: pytest.MonkeyPatch) -> None:
    import base64

    monkeypatch.setenv("U", "alice")
    monkeypatch.setenv("P", "s3cret")
    basic = AuthProfile(name="x", kind=AuthKind.basic, username_env="U", password_env="P")
    expected = base64.b64encode(b"alice:s3cret").decode()
    assert resolve_headers(basic) == {"Authorization": f"Basic {expected}"}
    with pytest.raises(ValueError, match="not set"):
        resolve_headers(AuthProfile(name="y", kind=AuthKind.bearer, token_env="MISSING_ENV_X"))


def test_auth_mtls(tmp_path: Path) -> None:
    cert = tmp_path / "c.pem"
    cert.write_text("cert")
    prof = AuthProfile(name="m", kind=AuthKind.mtls, cert_file=str(cert), key_file=str(cert))
    assert resolve_headers(prof) == {}
    assert resolve_verify(prof) == (str(cert), str(cert))
    with pytest.raises(ValueError, match="not found"):
        resolve_headers(
            AuthProfile(name="m2", kind=AuthKind.mtls, cert_file="nope.pem", key_file="nope.pem")
        )


def test_auth_profile_set(tmp_path: Path) -> None:
    manifest = tmp_path / "auth.yaml"
    manifest.write_text("profiles:\n  - name: ci\n    kind: bearer\n    token_env: CI_T\n")
    ps = AuthProfileSet.load(str(manifest))
    assert ps.get("ci").token_env == "CI_T"
    with pytest.raises(KeyError):
        ps.get("nope")


def test_plugin_builtins_load() -> None:
    rules = core_rules()
    assert "BRK-OP-REMOVED" in rules
    assert callable(security_checks())
    assert callable(schema_case_generator())
    exporters = report_exporters()
    assert "sarif" in exporters and "html" in exporters
    make_client = httpx_transport()
    client = make_client(timeout=1.0)
    try:
        assert client.timeout.read == 1.0
    finally:
        client.close()


def test_export_bundle_contents(tmp_path: Path) -> None:
    from apiverity.cli.main import main as cli_main

    out = tmp_path / "bundle.apiverity"
    code = cli_main(
        [
            "export",
            "--data",
            json.dumps(
                {
                    **SAMPLE,
                    "results": [
                        {"case_id": "c1", "status": "pass"},
                        {"case_id": "c2", "status": "fail", "violations": ["v"]},
                    ],
                }
            ),
            "-o",
            str(out),
            "--spec",
            "fixtures/apis/crud/openapi.yaml",
        ]
    )
    assert code == 0
    names = {p.name for p in out.iterdir()}
    assert {"result.json", "contract-snapshot", "SHA256SUMS"} <= names
    result = json.loads((out / "result.json").read_text(encoding="utf-8"))
    assert result["contract_hash"] == contract_hash("fixtures/apis/crud/openapi.yaml")
    failing = json.loads((out / "failing-cases.json").read_text(encoding="utf-8"))
    assert [f["case_id"] for f in failing] == ["c2"]
