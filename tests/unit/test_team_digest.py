"""A weekly digest, and the week-over-week comparison that lies.

Two sweeps are two walks of a tree, and the tree moves. A contract that is
absent from the second walk is not fixed -- it was not looked at. Getting that
wrong produces the report a platform team most wants to read and least should
believe.
"""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
from typing import Any

from apiverity.cli.commands.common import EXIT_FINDINGS, EXIT_OK, EXIT_USAGE
from apiverity.cli.main import main
from apiverity.reports.digest import UNOWNED, compare, render

_ROOT = Path(__file__).resolve().parents[2]
_CRUD = (_ROOT / "fixtures/apis/crud/openapi.yaml").read_text(encoding="utf-8")
#: A contract the security checks report errors on, so a digest has something
#: to say about it. A clean tree produces no documents, by design.
_FAILING = (_ROOT / "fixtures/apis/lint/openapi.yaml").read_text(encoding="utf-8")


def _sweep(*records: dict[str, Any], root: str = "/repo") -> dict[str, Any]:
    return {"tool": "apiverity", "command": "sweep", "root": root, "contracts": list(records)}


def _record(
    path: str,
    *,
    owners: list[str] | None = None,
    errors: int = 0,
    findings: list[dict[str, Any]] | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    return {
        "path": path,
        "owners": owners if owners is not None else [],
        "errors": errors,
        "warnings": 0,
        "status": status or ("failing" if errors else "ok"),
        "findings": findings or [],
    }


def _run(argv: list[str]) -> tuple[int, dict[str, Any], str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    text = out.getvalue()
    return code, (json.loads(text) if text.strip().startswith("{") else {}), err.getvalue()


# ---------------------------------------------------------------- the slicing


def test_each_team_gets_only_what_it_owns() -> None:
    sweep = _sweep(
        _record("services/orders/api.yaml", owners=["@org/orders"]),
        _record("services/users/api.yaml", owners=["@org/users"], errors=2),
    )
    digests = compare(sweep)
    assert sorted(digests) == ["@org/orders", "@org/users"]
    assert digests["@org/orders"].failing == []
    assert digests["@org/users"].failing == ["services/users/api.yaml"]


def test_a_contract_with_two_owners_appears_in_both_digests() -> None:
    sweep = _sweep(_record("api.yaml", owners=["@org/a", "@org/b"], errors=1))
    digests = compare(sweep)
    assert digests["@org/a"].failing == digests["@org/b"].failing == ["api.yaml"]


def test_unowned_contracts_are_a_team_rather_than_a_silence() -> None:
    """They are the ones nobody will be asked about, so they rot fastest."""
    digests = compare(_sweep(_record("api.yaml", errors=1)))
    assert list(digests) == [UNOWNED]
    assert digests[UNOWNED].failing == ["api.yaml"]


# ------------------------------------------------------ the comparison that lies


def test_a_contract_missing_from_this_sweep_is_not_fixed() -> None:
    """The defect this module exists to avoid.

    Last week's sweep found it failing; this week's walk did not reach it --
    a lower `--limit`, a moved service, a changed glob. Calling that "fixed"
    is the report a platform team most wants and least should believe.
    """
    before = _sweep(_record("gone.yaml", owners=["@org/a"], errors=1))
    after = _sweep(_record("kept.yaml", owners=["@org/a"]))
    digest = compare(after, before)["@org/a"]

    assert digest.fixed == [], "a contract nobody swept was reported as fixed"
    assert digest.no_longer_swept == ["gone.yaml"]
    assert "no longer swept" in digest.summary()


def test_a_contract_that_was_looked_at_and_is_clean_is_fixed() -> None:
    before = _sweep(_record("api.yaml", owners=["@org/a"], errors=1))
    after = _sweep(_record("api.yaml", owners=["@org/a"], errors=0))
    digest = compare(after, before)["@org/a"]
    assert digest.fixed == ["api.yaml"]
    assert digest.no_longer_swept == []


def test_a_team_that_lost_every_contract_still_gets_a_digest() -> None:
    """Otherwise the week a whole service vanished is the quietest week."""
    before = _sweep(_record("api.yaml", owners=["@org/a"], errors=1))
    digests = compare(_sweep(_record("other.yaml", owners=["@org/b"])), before)
    assert digests["@org/a"].no_longer_swept == ["api.yaml"]
    assert digests["@org/a"].quiet is False


# -------------------------------------------------------------- what moved


def test_newly_failing_is_separated_from_still_failing() -> None:
    before = _sweep(
        _record("old.yaml", owners=["@org/a"], errors=1),
        _record("new.yaml", owners=["@org/a"], errors=0),
    )
    after = _sweep(
        _record("old.yaml", owners=["@org/a"], errors=1),
        _record("new.yaml", owners=["@org/a"], errors=1),
    )
    digest = compare(after, before)["@org/a"]
    assert digest.newly_failing == ["new.yaml"]
    assert digest.standing == ["old.yaml"]


def test_findings_that_appeared_are_separated_from_the_standing_set() -> None:
    old = {"rule_id": "BRK-A", "operation_key": "GET /a", "message": "x"}
    new = {"rule_id": "BRK-B", "operation_key": "GET /b", "message": "y"}
    before = _sweep(_record("api.yaml", owners=["@org/a"], errors=1, findings=[old]))
    after = _sweep(_record("api.yaml", owners=["@org/a"], errors=2, findings=[old, new]))
    digest = compare(after, before)["@org/a"]
    assert [f["rule_id"] for f in digest.appeared] == ["BRK-B"]
    assert digest.resolved == []


def test_a_contract_swept_for_the_first_time_is_named_as_such() -> None:
    before = _sweep(_record("api.yaml", owners=["@org/a"]))
    after = _sweep(
        _record("api.yaml", owners=["@org/a"]),
        _record("added.yaml", owners=["@org/a"], errors=1),
    )
    digest = compare(after, before)["@org/a"]
    assert digest.newly_swept == ["added.yaml"]
    assert digest.newly_failing == ["added.yaml"]


# ------------------------------------------------------------- what it says


def test_a_first_digest_never_claims_something_was_failing_before() -> None:
    """`standing` means "failing in the previous digest too", and there is none."""
    digest = compare(_sweep(_record("api.yaml", owners=["@org/a"], errors=1)))["@org/a"]
    assert digest.baseline is True
    assert digest.standing == []
    body = render(digest)
    assert "Still failing" not in body
    assert "## Failing (1)" in body
    assert "no previous digest" in body


def test_a_quiet_team_has_nothing_to_send() -> None:
    before = _sweep(_record("api.yaml", owners=["@org/a"]))
    digest = compare(_sweep(_record("api.yaml", owners=["@org/a"])), before)["@org/a"]
    assert digest.quiet is True
    assert "nothing changed, nothing failing" in digest.summary()


def test_a_standing_failure_is_never_quiet_however_old() -> None:
    """The monitor's rule inverted: nagging about old debt is this one's job."""
    sweep = _sweep(_record("api.yaml", owners=["@org/a"], errors=1))
    digest = compare(sweep, sweep)["@org/a"]
    assert digest.appeared == [] and digest.newly_failing == []
    assert digest.quiet is False, "a contract failing every week dropped out of the digest"


def test_a_contract_that_would_not_load_is_reported_not_omitted() -> None:
    sweep = _sweep(
        _record("broken.yaml", owners=["@org/a"], errors=1, status="unreadable"),
    )
    digest = compare(sweep)["@org/a"]
    assert digest.unreadable == ["broken.yaml"]
    assert "Would not load" in render(digest)


def test_the_rendered_document_names_the_tree_it_came_from() -> None:
    digest = compare(_sweep(_record("api.yaml", owners=["@org/a"], errors=1)))["@org/a"]
    assert "Swept from `/repo`." in render(digest, root="/repo")


def test_a_long_list_says_how_many_it_did_not_print() -> None:
    records = [_record(f"api-{n}.yaml", owners=["@org/a"], errors=1) for n in range(30)]
    digest = compare(_sweep(*records))["@org/a"]
    body = render(digest, limit=5)
    assert "…and 25 more" in body


# ------------------------------------------------------------------ the command


def test_the_command_writes_one_document_per_team(tmp_path: Path) -> None:
    for relative in ("services/orders/api.yaml", "services/users/api.yaml"):
        path = tmp_path / "repo" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_FAILING, encoding="utf-8")
    (tmp_path / "repo" / "CODEOWNERS").write_text(
        "services/orders/** @org/orders\nservices/users/** @org/users\n", encoding="utf-8"
    )
    _, sweep, _ = _run(["sweep", str(tmp_path / "repo"), "--json"])
    artifact = tmp_path / "sweep.json"
    artifact.write_text(json.dumps(sweep), encoding="utf-8")

    code, payload, _ = _run(["digest", str(artifact), "--out", str(tmp_path / "out"), "--json"])
    assert code == EXIT_OK
    assert payload["teams"] == 2
    names = sorted(p.name for p in (tmp_path / "out").glob("*.md"))
    assert names == ["org-orders.md", "org-users.md"], "a team name is not a filename"


def test_a_clean_tree_writes_no_documents_and_says_so(tmp_path: Path) -> None:
    """A weekly email saying "nothing to report" to everyone is the muting."""
    path = tmp_path / "repo" / "api.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(_CRUD, encoding="utf-8")
    _, sweep, _ = _run(["sweep", str(tmp_path / "repo"), "--json"])
    artifact = tmp_path / "sweep.json"
    artifact.write_text(json.dumps(sweep), encoding="utf-8")

    code, payload, _ = _run(["digest", str(artifact), "--out", str(tmp_path / "out"), "--json"])
    assert code == EXIT_OK
    assert payload["written"] == []
    assert payload["quiet"] == [UNOWNED], "the quiet team was dropped rather than named"


def test_a_newly_failing_contract_fails_the_run(tmp_path: Path) -> None:
    before = tmp_path / "before.json"
    after = tmp_path / "after.json"
    before.write_text(json.dumps(_sweep(_record("api.yaml", owners=["@org/a"]))), encoding="utf-8")
    after.write_text(
        json.dumps(_sweep(_record("api.yaml", owners=["@org/a"], errors=1))), encoding="utf-8"
    )
    code, payload, _ = _run(["digest", str(after), "--since", str(before), "--json"])
    assert code == EXIT_FINDINGS
    assert payload["digests"][0]["newly_failing"] == ["api.yaml"]


def test_a_quiet_team_is_named_rather_than_dropped(tmp_path: Path) -> None:
    """ "Four teams had nothing to report" and "four teams were missing" differ."""
    sweep = _sweep(
        _record("a.yaml", owners=["@org/a"]),
        _record("b.yaml", owners=["@org/b"], errors=1),
    )
    path = tmp_path / "s.json"
    path.write_text(json.dumps(sweep), encoding="utf-8")
    _, payload, _ = _run(["digest", str(path), "--since", str(path), "--json"])
    assert payload["quiet"] == ["@org/a"]
    assert [d["team"] for d in payload["digests"]] == ["@org/b"]


def test_something_that_is_not_a_sweep_is_a_usage_error(tmp_path: Path) -> None:
    path = tmp_path / "nope.json"
    path.write_text(json.dumps({"tool": "apiverity", "command": "validate"}), encoding="utf-8")
    code, _, err = _run(["digest", str(path)])
    assert code == EXIT_USAGE
    assert "no top-level `contracts` array" in err
