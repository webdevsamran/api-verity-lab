"""A monorepo view, and the ownership file the repository already keeps.

A repo with twelve services has twelve contract gates and no view across them.
`sweep` walks the tree once and answers the two questions a platform team
actually has: which contracts are failing, and whose they are.

Ownership is read from CODEOWNERS rather than from a second file, because a
second ownership file goes stale the week after it is written. GitHub's
matching rule is the part worth testing: **the last matching pattern wins**,
not the most specific one, and getting that backwards silently assigns the
wrong team.
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
from apiverity.core.ownership import Ownership, load_ownership, parse_codeowners

_ROOT = Path(__file__).resolve().parents[2]
_CRUD = (_ROOT / "fixtures/apis/crud/openapi.yaml").read_text(encoding="utf-8")

_OWNERS = """\
# Everything, unless something later says otherwise.
*                       @org/platform
/api/                   @org/payments
api/orders/*.yaml       @org/orders @alice
docs/**                 @org/docs
*.proto                 @org/protos
"""


def _own(text: str = _OWNERS) -> Ownership:
    return Ownership(rules=parse_codeowners(text))


def _run(argv: list[str]) -> tuple[int, dict[str, Any], str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    text = out.getvalue()
    return code, (json.loads(text) if text.strip().startswith("{") else {}), err.getvalue()


def _service(root: Path, relative: str, body: str = _CRUD) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


# ---------------------------------------------------------------- CODEOWNERS


def test_the_last_matching_pattern_wins() -> None:
    """Not the most specific one. Reading top-down gives the opposite answer."""
    assert _own().owners_of("api/users.yaml") == ("@org/payments",)


def test_a_later_more_specific_rule_still_wins() -> None:
    assert _own().owners_of("api/orders/orders.yaml") == ("@org/orders", "@alice")


def test_a_star_does_not_cross_a_slash() -> None:
    """`api/orders/*.yaml` owns the directory, not the tree below it."""
    assert _own().owners_of("api/orders/deep/x.yaml") == ("@org/payments",)


def test_a_double_star_does() -> None:
    assert _own().owners_of("docs/a/b/c.md") == ("@org/docs",)


def test_a_pattern_with_no_slash_matches_at_any_depth() -> None:
    assert _own().owners_of("services/a/schema.proto") == ("@org/protos",)


def test_the_catch_all_covers_what_nothing_else_does() -> None:
    assert _own().owners_of("README.md") == ("@org/platform",)


def test_a_path_nothing_matches_is_unowned_rather_than_guessed() -> None:
    """A plausible team that never agreed to anything is worse than none."""
    assert _own("/api/ @org/payments\n").owners_of("web/index.html") == ()


def test_comments_and_blank_lines_are_not_rules() -> None:
    rules = parse_codeowners("# a comment\n\n*   @org/x   # trailing\n")
    assert [r.pattern for r in rules] == ["*"]
    assert rules[0].owners == ("@org/x",)


def test_a_pattern_with_no_owner_is_not_a_rule() -> None:
    """GitHub uses those to *remove* ownership; treating it as one would lie."""
    assert parse_codeowners("/api/\n") == []


@pytest.mark.parametrize("location", [".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS"])
def test_every_location_github_looks_in_is_read(tmp_path: Path, location: str) -> None:
    path = tmp_path / location
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("* @org/x\n", encoding="utf-8")
    ownership = load_ownership(tmp_path)
    assert ownership.source is not None
    assert ownership.owners_of("anything") == ("@org/x",)


def test_a_repository_with_no_codeowners_has_no_rules(tmp_path: Path) -> None:
    ownership = load_ownership(tmp_path)
    assert ownership.source is None
    assert ownership.owners_of("api/x.yaml") == ()


# --------------------------------------------------------------------- sweep


def test_contracts_are_found_wherever_a_monorepo_keeps_them(tmp_path: Path) -> None:
    """`services/<name>/api/openapi.yaml` is the shape, and none of those
    directory names appear at the root."""
    _service(tmp_path, "services/orders/api/openapi.yaml")
    _service(tmp_path, "services/users/api/openapi.yaml")

    code, payload, _ = _run(["sweep", str(tmp_path), "--json"])
    assert code == EXIT_OK
    assert payload["contracts_found"] == 2


def test_each_contract_gets_its_owner(tmp_path: Path) -> None:
    _service(tmp_path, "services/orders/api/openapi.yaml")
    (tmp_path / "CODEOWNERS").write_text(
        "* @org/platform\nservices/orders/** @org/orders\n", encoding="utf-8"
    )
    _, payload, _ = _run(["sweep", str(tmp_path), "--json"])
    assert payload["contracts"][0]["owners"] == ["@org/orders"]
    assert payload["by_owner"]["@org/orders"]["contracts"] == ["services/orders/api/openapi.yaml"]


def test_an_unowned_contract_is_listed_as_unowned(tmp_path: Path) -> None:
    _service(tmp_path, "api/openapi.yaml")
    _, payload, _ = _run(["sweep", str(tmp_path), "--json"])
    assert payload["unowned"] == ["api/openapi.yaml"]
    assert "(unowned)" in payload["by_owner"]


def test_a_contract_that_will_not_load_is_the_loudest_finding_about_it(tmp_path: Path) -> None:
    """Skipping it would make the sweep read cleaner than the repository is."""
    _service(tmp_path, "api/good.yaml")
    # Malformed YAML, which raises `yaml.YAMLError` -- not a `ValueError`, and
    # therefore exactly the exception a narrow `except` clause misses. One bad
    # file in a hundred-service monorepo used to end the run with "internal
    # error", which is the least useful thing a sweep can say.
    (tmp_path / "api" / "broken.yaml").write_text(
        "openapi: 3.1.0\ninfo:\n  title: X\n   version: bad indent\npaths: {\n",
        encoding="utf-8",
    )
    code, payload, _ = _run(["sweep", str(tmp_path), "--json"])
    statuses = {c["path"]: c["status"] for c in payload["contracts"]}
    assert statuses["api/broken.yaml"] == "unreadable"
    assert statuses["api/good.yaml"] == "ok", "one bad file must not end the sweep"
    assert code == EXIT_FINDINGS


def test_an_empty_tree_is_a_usage_error_not_a_clean_sweep(tmp_path: Path) -> None:
    """Zero contracts found and zero contracts broken read identically."""
    code, _, err = _run(["sweep", str(tmp_path)])
    assert code == EXIT_USAGE
    assert "not the same as nothing being wrong" in err


# ---------------------------------------------------------- comparing a base


def test_a_base_tree_gives_one_breaking_verdict_for_the_whole_repo(tmp_path: Path) -> None:
    base = tmp_path / "base"
    head = tmp_path / "head"
    _service(
        base, "api/openapi.yaml", (_ROOT / "fixtures/apis/versioned/v1.yaml").read_text("utf-8")
    )
    _service(
        head, "api/openapi.yaml", (_ROOT / "fixtures/apis/versioned/v2.yaml").read_text("utf-8")
    )

    code, payload, _ = _run(["sweep", str(head), "--base", str(base), "--json"])
    assert code == EXIT_FINDINGS
    record = payload["contracts"][0]
    assert record["errors"] > 0
    assert "BRK-OP-REMOVED" in {f["rule_id"] for f in record["findings"]}


def test_a_contract_with_no_counterpart_says_so_rather_than_passing(tmp_path: Path) -> None:
    """ "No findings" for something never compared is not the same claim."""
    base = tmp_path / "base"
    base.mkdir()
    head = tmp_path / "head"
    _service(head, "api/new-service.yaml")

    _, payload, _ = _run(["sweep", str(head), "--base", str(base), "--json"])
    record = payload["contracts"][0]
    assert record["compared"] is None
    assert "nothing to compare against" in record["detail"]
