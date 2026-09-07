"""Changes the differ used to miss entirely, and the JSON contract.

Part of the compatibility-catalog work in #15. Each case below produced no
change at all before, so a consumer diffing two contracts was told nothing had
happened.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from apiverity.diff.engine import diff_services
from apiverity.specs.loader import detect_and_load

_BASE = """\
openapi: "3.0.3"
info: {{ title: Demo, version: "1.0.0" }}
paths:
  /users:
    post:
      operationId: createUser
      requestBody:
        required: true
        content:
{request_media}
      responses:
        "200":
          description: ok
          content:
            application/json:
              schema:
                type: object
                properties:
                  role: {{ type: string{role_default} }}
"""

_JSON_AND_XML = """\
          application/json:
            schema: {{ type: object }}
          application/xml:
            schema: {{ type: object }}"""

_JSON_ONLY = """\
          application/json:
            schema: {{ type: object }}"""


def _spec(tmp_path: Path, name: str, *, media: str, role_default: str = "") -> Path:
    path = tmp_path / name
    path.write_text(
        _BASE.format(request_media=media, role_default=role_default)
        .replace("{{", "{")
        .replace("}}", "}"),
        encoding="utf-8",
    )
    return path


def _changes(old: Path, new: Path) -> list:
    old_service, _, _ = detect_and_load(str(old))
    new_service, _, _ = detect_and_load(str(new))
    return diff_services(old_service, new_service)


def test_removing_a_request_media_type_is_reported(tmp_path: Path) -> None:
    """Narrowing content negotiation breaks clients still sending the old type."""
    old = _spec(tmp_path, "v1.yaml", media=_JSON_AND_XML)
    new = _spec(tmp_path, "v2.yaml", media=_JSON_ONLY)

    descriptions = [c.description for c in _changes(old, new)]
    assert any("application/xml" in d and "removed" in d for d in descriptions), descriptions

    removal = next(c for c in _changes(old, new) if "removed" in c.description)
    assert removal.direction == "request"
    assert removal.breaking_hint, "a removed request media type needs an actionable hint"


def test_adding_a_request_media_type_is_reported_as_additive(tmp_path: Path) -> None:
    old = _spec(tmp_path, "v1.yaml", media=_JSON_ONLY)
    new = _spec(tmp_path, "v2.yaml", media=_JSON_AND_XML)

    added = [c for c in _changes(old, new) if "added" in c.description]
    assert any("application/xml" in c.description for c in added), added
    assert all(c.breaking_hint is None for c in added), "adding a media type is not breaking"


def test_introducing_a_default_is_reported(tmp_path: Path) -> None:
    """A default is client-visible behaviour, not documentation."""
    old = _spec(tmp_path, "v1.yaml", media=_JSON_ONLY)
    new = _spec(tmp_path, "v2.yaml", media=_JSON_ONLY, role_default=', default: "viewer"')

    change = next((c for c in _changes(old, new) if "default changed" in c.description), None)
    assert change is not None, [c.description for c in _changes(old, new)]
    assert change.old_value is None
    assert change.new_value == "viewer"
    assert change.breaking_hint, "introducing a default where none existed needs a hint"


def test_identical_contracts_report_no_media_or_default_change(tmp_path: Path) -> None:
    """The new comparisons must not fire on an unchanged contract."""
    old = _spec(tmp_path, "v1.yaml", media=_JSON_AND_XML, role_default=', default: "viewer"')
    new = _spec(tmp_path, "v2.yaml", media=_JSON_AND_XML, role_default=', default: "viewer"')

    noisy = [
        c.description
        for c in _changes(old, new)
        if "media type" in c.description or "default changed" in c.description
    ]
    assert not noisy, noisy


def test_json_output_emits_objects_not_reprs(tmp_path: Path) -> None:
    """`--json` is a scripting contract; a Python repr string is unusable.

    `json.dumps(..., default=str)` rendered every Pydantic model as its repr,
    so consumers received strings like "id='CHG-OP-REMOVED-1' kind=<...>"
    where an object was documented.
    """
    old = _spec(tmp_path, "v1.yaml", media=_JSON_AND_XML)
    new = _spec(tmp_path, "v2.yaml", media=_JSON_ONLY)

    proc = subprocess.run(
        [sys.executable, "-m", "apiverity.cli.main", "diff", str(old), str(new), "--json"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)

    changes = payload["changes"]
    assert changes, "expected at least one change"
    for change in changes:
        assert isinstance(change, dict), f"change serialized as {type(change).__name__}: {change!r}"
        assert "id" in change and "description" in change
        assert not change["id"].startswith("id="), "looks like a repr, not an object"


def test_rule_catalog_doc_matches_the_code() -> None:
    """Every documented rule ID must exist, and every rule must be documented.

    The hand-maintained catalog documented six IDs the engine has never had
    and omitted twenty-three it does, so a severity override copied from the
    docs would have been silently ignored.
    """
    import re

    from apiverity.rules.breaking import CATALOG

    doc = (Path(__file__).resolve().parents[2] / "docs" / "rule-catalog.md").read_text(
        encoding="utf-8"
    )
    documented = set(re.findall(r"`(BRK-[A-Z0-9-]+)`", doc))
    real = set(CATALOG)
    assert not documented - real, f"documented rules that do not exist: {sorted(documented - real)}"
    assert not real - documented, f"rules missing from the catalog doc: {sorted(real - documented)}"
