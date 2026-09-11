"""Reading somebody else's ruleset, and not overstating what we can do with it.

Migration cost is the real competitor. A migration report that listed only the
rules this project covers would be claiming a completeness it does not have —
so the number that decides whether to migrate is the *other* two lists, and
these tests are mostly about those.
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
from apiverity.rules.check_catalog import catalog
from apiverity.rules.spectral import EQUIVALENTS, NOT_EXPRESSIBLE, SpectralError, read

_ROOT = Path(__file__).resolve().parents[2]
_FIXTURE = _ROOT / "fixtures/rulesets/.spectral.yaml"


def _run(argv: list[str]) -> tuple[int, dict[str, Any], str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    text = out.getvalue()
    return code, (json.loads(text) if text.strip().startswith("{") else {}), err.getvalue()


def _ruleset(tmp_path: Path, body: str) -> Path:
    path = tmp_path / ".spectral.yaml"
    path.write_text(body, encoding="utf-8")
    return path


# ------------------------------------------------------------ classification


def test_a_rule_with_an_equivalent_is_named_not_just_counted() -> None:
    imported = read(_FIXTURE)
    assert imported.covered["operation-operationId"] == "GOV-MISSING-OPERATION-ID"
    assert imported.covered["oas3-valid-schema-example"] == "LINT-INVALID-EXAMPLE"


def test_a_rule_this_project_could_express_and_does_not_is_the_backlog(tmp_path: Path) -> None:
    imported = read(_ruleset(tmp_path, "rules:\n  acme-house-style: error\n"))
    assert imported.not_covered == ["acme-house-style"]


def test_a_custom_rule_lands_in_the_backlog_even_if_we_happen_to_check_it(
    tmp_path: Path,
) -> None:
    """Over-reporting the backlog is the safe direction to be wrong in.

    Spectral rule names are conventional, not standardised, so a team's own
    name for "every operation needs an operationId" is unrecognisable. Claiming
    coverage of a rule nobody matched would be the other kind of wrong.
    """
    imported = read(_ruleset(tmp_path, "rules:\n  acme-every-op-has-an-id: error\n"))
    assert imported.not_covered == ["acme-every-op-has-an-id"]
    assert imported.covered == {}


def test_a_rule_about_the_document_is_separated_from_the_backlog(tmp_path: Path) -> None:
    """`info-description` is not work this project is behind on."""
    imported = read(_ruleset(tmp_path, "rules:\n  info-description: warn\n"))
    assert imported.not_covered == []
    assert "wording" in imported.not_expressible["info-description"]


def test_a_disabled_rule_is_named_rather_than_quietly_re_enabled(tmp_path: Path) -> None:
    """A migration that silently turned somebody's disabled rule back on has
    changed their gate."""
    imported = read(
        _ruleset(
            tmp_path,
            "rules:\n  operation-tags: off\n  oas3-api-servers: false\n"
            "  info-contact:\n    severity: off\n",
        )
    )
    assert imported.disabled == ["info-contact", "oas3-api-servers", "operation-tags"]
    assert imported.not_expressible == {}


# ------------------------------------------------------------------- extends


def test_extends_is_reported_because_the_file_does_not_list_those_rules() -> None:
    """`extends: spectral:oas` is sixty-odd rules the file never names.

    A report counting only the named ones describes a fraction of the gate
    being migrated, and reads as though the migration is nearly done.
    """
    imported = read(_FIXTURE)
    assert imported.extends == ["spectral:oas"]
    assert "not listed in the file and are not counted above" in imported.summary()


@pytest.mark.parametrize(
    "raw",
    [
        "extends: spectral:oas\n",
        "extends:\n  - spectral:oas\n",
        'extends:\n  - ["spectral:oas", "off"]\n',
    ],
)
def test_every_shape_extends_takes_is_read(tmp_path: Path, raw: str) -> None:
    assert read(_ruleset(tmp_path, raw + "rules: {}\n")).extends == ["spectral:oas"]


def test_a_ruleset_with_no_extends_says_nothing_about_one(tmp_path: Path) -> None:
    imported = read(_ruleset(tmp_path, "rules:\n  info-description: warn\n"))
    assert imported.extends == []
    assert "extends" not in imported.summary()


# ------------------------------------------------------------- what it reads


def test_something_that_is_not_a_ruleset_is_refused(tmp_path: Path) -> None:
    for body in ["just a string\n", "- a\n- list\n", "openapi: 3.1.0\ninfo: {}\n"]:
        with pytest.raises(SpectralError):
            read(_ruleset(tmp_path, body))


def test_a_rules_key_that_is_not_a_mapping_is_refused(tmp_path: Path) -> None:
    with pytest.raises(SpectralError, match="not a mapping"):
        read(_ruleset(tmp_path, "rules:\n  - a\n  - b\n"))


def test_a_file_that_is_not_there_is_refused(tmp_path: Path) -> None:
    with pytest.raises(SpectralError, match="could not read"):
        read(tmp_path / "nope.yaml")


def test_a_ruleset_that_only_extends_is_valid(tmp_path: Path) -> None:
    imported = read(_ruleset(tmp_path, "extends: spectral:oas\n"))
    assert imported.named == 0
    assert imported.extends == ["spectral:oas"]


# ------------------------------------------------------------ the mapping


def test_every_rule_this_claims_to_cover_exists() -> None:
    """A mapping to a rule id nothing emits is a coverage claim about nothing."""
    known = set(catalog())
    # `SPEC-*` are loader findings rather than catalogued check rules, so they
    # are the one family this mapping may name without an entry.
    missing = {
        spectral: ours
        for spectral, ours in EQUIVALENTS.items()
        if ours not in known and not ours.startswith("SPEC-")
    }
    assert not missing, f"these map to rule ids that do not exist: {missing}"


def test_no_rule_is_both_covered_and_inexpressible() -> None:
    overlap = set(EQUIVALENTS) & set(NOT_EXPRESSIBLE)
    assert not overlap, f"{sorted(overlap)} are classified twice"


# ------------------------------------------------------------- the command


def test_the_command_reports_the_backlog_as_a_finding() -> None:
    code, payload, _ = _run(["import-rules", str(_FIXTURE), "--json"])
    assert code == EXIT_FINDINGS
    assert payload["not_covered"] == ["acme-no-internal-hosts", "acme-paths-kebab-case"]
    assert payload["rules_named_in_the_file"] == 10


def test_a_ruleset_this_project_fully_covers_passes(tmp_path: Path) -> None:
    code, payload, _ = _run(
        [
            "import-rules",
            str(_ruleset(tmp_path, "rules:\n  operation-operationId: warn\n")),
            "--json",
        ]
    )
    assert code == EXIT_OK
    assert payload["covered"] == {"operation-operationId": "GOV-MISSING-OPERATION-ID"}


def test_a_bad_file_is_a_usage_error(tmp_path: Path) -> None:
    code, _, err = _run(["import-rules", str(_ruleset(tmp_path, "nope\n"))])
    assert code == EXIT_USAGE
    assert "not a Spectral ruleset" in err
