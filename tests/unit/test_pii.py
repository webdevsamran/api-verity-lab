"""Personal data, found by shape, and the shapes deliberately not looked for.

`leakage.py` finds credentials in what a service returns. This is the other
category and it needs the opposite default: a leaked credential is always
wrong, and a returned email address is usually the entire point of the
endpoint.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from apiverity.security import pii, run_security_checks
from apiverity.specs.loader import detect_and_load

# Structurally valid and published as test values, not anybody's.
_CARD = "4111 1111 1111 1111"  # the Visa test number, passes Luhn
_NOT_A_CARD = "4111111111111112"  # same length, fails Luhn: an order reference
_IBAN = "GB82WEST12345698765432"  # the ISO 13616 worked example


def _kinds(hits: list[pii.Hit]) -> set[str]:
    return {h.kind for h in hits}


# ------------------------------------------------------ checksums, not guesses


def test_a_card_number_is_confirmed_by_luhn() -> None:
    assert _kinds(pii.scan_text(_CARD)) == {"payment card number"}


def test_a_number_of_the_same_length_that_fails_luhn_is_not_a_card() -> None:
    """An order reference is sixteen digits too. Without the checksum this
    rule would redact half the identifiers in a corpus."""
    assert pii.scan_text(_NOT_A_CARD) == []
    assert pii.luhn("4111111111111111") is True
    assert pii.luhn(_NOT_A_CARD) is False


def test_an_iban_is_confirmed_by_mod_97() -> None:
    assert _kinds(pii.scan_text(_IBAN)) == {"bank account number (IBAN)"}
    assert pii.iban_valid(_IBAN) is True
    assert pii.iban_valid("GB00WEST12345698765432") is False


def test_an_ip_address_is_parsed_not_pattern_matched() -> None:
    assert _kinds(pii.scan_text("from 203.0.113.42")) == {"IP address"}
    # A version string has the same shape and is not an address.
    assert pii.scan_text("version 999.1.1.1") == []


def test_an_ipv6_address_is_recognised() -> None:
    assert _kinds(pii.scan_text("2001:db8::1")) == {"IP address"}


def test_an_email_is_recognised() -> None:
    assert _kinds(pii.scan_text("write to ada@example.test please")) == {"email address"}


@pytest.mark.parametrize(
    "text",
    [
        "Ada Lovelace",
        "12 Rue de Rivoli, Paris",
        "1990-03-14",
        "she lives in Paris",
    ],
)
def test_what_has_no_shape_is_deliberately_not_detected(text: str) -> None:
    """Names, addresses and dates of birth have no shape.

    "Paris" is a city and a person; `1990-03-14` is a birthday and a release
    date; any string at all can be a name. A detector for them is wrong most of
    the time, and a check that is wrong most of the time trains people to
    ignore the times it is right.
    """
    assert pii.scan_text(text) == []


def test_a_very_large_value_is_not_scanned() -> None:
    """A megabyte of base64 is not personal data, and scanning it is the check
    becoming the slow part of the run."""
    assert pii.scan_text("x" * (pii.MAX_SCAN + 1)) == []


# -------------------------------------------------------------- reporting


def test_a_hit_carries_the_kind_and_the_path_and_not_the_value() -> None:
    hit = pii.scan({"user": {"contact": "ada@example.test"}})[0]
    assert hit.kind == "email address"
    assert hit.pointer == "user.contact"
    assert hit.length == len("ada@example.test")
    assert "ada" not in hit.describe()


def test_a_list_carries_an_index_in_the_path() -> None:
    hits = pii.scan({"items": [{"e": "a@b.test"}, {"e": "c@d.test"}]})
    assert [h.pointer for h in hits] == ["items[0].e", "items[1].e"]


def test_a_structure_with_nothing_in_it_produces_nothing() -> None:
    assert pii.scan({"a": 1, "b": [None, True], "c": "hello"}) == []


# -------------------------------------------------------------- redaction


def test_redaction_replaces_what_is_recognised_and_nothing_else() -> None:
    before = {
        "nickname": "ada@example.test",
        "seen_from": "203.0.113.42",
        "card": _CARD,
        "order_ref": _NOT_A_CARD,
        "note": "not personal at all",
    }
    after = pii.redact(before)
    assert after["nickname"] == pii.REPLACEMENT
    assert after["seen_from"] == pii.REPLACEMENT
    assert after["card"] == pii.REPLACEMENT
    assert after["order_ref"] == _NOT_A_CARD, "an order reference is not a card"
    assert after["note"] == "not personal at all"


def test_the_replacement_is_distinct_from_the_credential_one() -> None:
    """A reader of a redacted corpus can tell which rule fired."""
    from apiverity.traffic.redact import RedactionConfig

    assert RedactionConfig().replacement != pii.REPLACEMENT


def test_redaction_leaves_the_original_alone() -> None:
    before = {"e": "ada@example.test"}
    pii.redact(before)
    assert before["e"] == "ada@example.test"


# ------------------------------------------------- it reaches the capture path


def test_a_recorded_corpus_carries_no_personal_data() -> None:
    """A corpus is something people commit, and no credential pattern names
    the field a customer's email arrived in."""
    from apiverity.traffic.capture import Capture

    capture = Capture(target="http://x.test")
    capture.record(
        method="GET",
        url="http://x.test/u",
        request_headers={},
        request_body=b"",
        status=200,
        response_headers={"content-type": "application/json"},
        response_body=json.dumps({"nickname": "ada@example.test", "card": _CARD}).encode(),
        started="2026-01-01T00:00:00Z",
        duration_ms=1,
    )
    text = capture.entries[0]["response"]["content"]["text"]
    assert "ada@example.test" not in text
    assert "4111" not in text
    assert pii.REPLACEMENT in text


def test_it_can_be_turned_off_for_a_run_that_needs_the_values() -> None:
    from apiverity.traffic.capture import Capture

    capture = Capture(target="http://x.test", redact_pii=False)
    capture.record(
        method="GET",
        url="http://x.test/u",
        request_headers={},
        request_body=b"",
        status=200,
        response_headers={"content-type": "application/json"},
        response_body=json.dumps({"nickname": "ada@example.test"}).encode(),
        started="2026-01-01T00:00:00Z",
        duration_ms=1,
    )
    assert "ada@example.test" in capture.entries[0]["response"]["content"]["text"]


# ------------------------------------------ the classification that did nothing


def _spec(tmp_path: Path, annotation: str = "") -> str:
    path = tmp_path / "s.yaml"
    path.write_text(
        "openapi: 3.1.0\n"
        'info: {title: X, version: "1.0.0"}\n'
        "paths:\n  /u:\n    get:\n      responses:\n        '200':\n"
        "          description: ok\n          content:\n"
        "            application/json:\n              schema:\n"
        "                type: object\n                properties:\n"
        "                  ssn:\n                    type: string" + annotation + "\n",
        encoding="utf-8",
    )
    return str(path)


def test_the_annotation_the_hint_tells_you_to_add_now_silences_the_rule(
    tmp_path: Path,
) -> None:
    """`SEC-SENSITIVE-FIELD` read `data_classification` off a model that never
    declared it, so the value was always `None` and the rule fired whatever the
    document said. Its own hint told people to add the annotation.

    Two defects, in fact: the field did not exist, and it was read off the
    *parent* object rather than the sensitive property.
    """
    bare, _, _ = detect_and_load(_spec(tmp_path))
    fired = {f.rule_id for f in run_security_checks(bare)}
    assert "SEC-SENSITIVE-FIELD" in fired

    annotated, _, _ = detect_and_load(
        _spec(tmp_path, "\n                    x-data-classification: pii")
    )
    assert "SEC-SENSITIVE-FIELD" not in {f.rule_id for f in run_security_checks(annotated)}


def test_the_classification_reaches_the_model(tmp_path: Path) -> None:
    service, _, _ = detect_and_load(
        _spec(tmp_path, "\n                    x-data-classification: pii")
    )
    schema = service.operations[0].responses[0].content["application/json"]
    assert schema.properties["ssn"].data_classification == "pii"


# ------------------------------------------------ undeclared PII at runtime


class _Service:
    def __init__(self, body: dict[str, Any]) -> None:
        payload = json.dumps(body).encode()

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args: Any) -> None:  # pragma: no cover - quiet
                return

            def do_GET(self) -> None:
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    def __enter__(self) -> _Service:
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=5)


def _drift(tmp_path: Path, spec_body: str, response: dict[str, Any]) -> list[Any]:
    from apiverity.runtime.drift import detect_drift

    path = tmp_path / "s.yaml"
    path.write_text(spec_body, encoding="utf-8")
    service, _, _ = detect_and_load(str(path))
    with _Service(response) as server:
        report = detect_drift(service, f"http://127.0.0.1:{server.port}", timeout=5)
    return [f for f in report.findings if f.rule_id == "DRIFT-RESPONSE-PII"]


_SPEC = (
    "openapi: 3.1.0\n"
    'info: {title: X, version: "1.0.0"}\n'
    "paths:\n  /users:\n    get:\n      responses:\n        '200':\n"
    "          description: ok\n          content:\n"
    "            application/json:\n              schema:\n"
    "                type: object\n                properties:\n"
    "                  nickname: {type: string}\n"
    "                  contact:\n                    type: string\n"
    "                    x-data-classification: pii\n"
)


def test_personal_data_the_contract_does_not_declare_is_reported(tmp_path: Path) -> None:
    findings = _drift(
        tmp_path, _SPEC, {"nickname": "ada@example.test", "contact": "grace@example.test"}
    )
    assert len(findings) == 1
    assert "nickname" in findings[0].message
    assert findings[0].severity == "WARN"


def test_personal_data_the_contract_declares_is_not_a_finding(tmp_path: Path) -> None:
    """Returning an email from an endpoint that says it returns one is the
    endpoint working."""
    assert _drift(tmp_path, _SPEC, {"contact": "grace@example.test"}) == []


def test_the_value_never_reaches_the_finding(tmp_path: Path) -> None:
    findings = _drift(tmp_path, _SPEC, {"nickname": "ada@example.test"})
    assert "ada@example.test" not in findings[0].message
    assert "16 characters" in findings[0].message


def test_a_response_with_nothing_personal_produces_nothing(tmp_path: Path) -> None:
    assert _drift(tmp_path, _SPEC, {"nickname": "ada"}) == []
