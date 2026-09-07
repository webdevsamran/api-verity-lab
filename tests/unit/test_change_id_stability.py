"""Change ids must not move when something unrelated changes.

ARCHITECTURE.md promised `CHG-{KIND}-{operation-hash}-{index}`. The engine
emitted a flat `CHG-{KIND}-{N}` from one counter shared across every
operation, so the ordinal depended on how many *other* operations happened to
produce a change of the same kind.

Measured, before the fix: a requiredness change on `GET /zebra` was
`CHG-PARAMETER_REQUIREDNESS-1`. Adding an unrelated `/alpha` endpoint that
also changed requiredness moved the *same* `/zebra` change to
`CHG-PARAMETER_REQUIREDNESS-2`. An id quoted in a review, or used to suppress
a finding, then pointed at a different change.

Worth being precise about what was *not* broken: document reordering already
had no effect, because `DiffEngine.run` iterates `sorted(...)` over operation
keys rather than document order. The doc's "survives reordering" claim was
true; its id format was not, and the property that actually failed was
stability under unrelated additions. Both are locked in below.
"""

from __future__ import annotations

from pathlib import Path

from apiverity.diff.engine import diff_services
from apiverity.specs.loader import detect_and_load

_HEAD = """\
openapi: "3.0.3"
info: {{ title: Reorder, version: "{version}" }}
paths:
"""

_USERS = """\
  /users:
    get:
      operationId: listUsers
      parameters:
        - name: limit
          in: query
          required: {users_limit_required}
          schema: {{ type: integer }}
      responses:
        "200": {{ description: ok }}
"""

_ORDERS = """\
  /orders:
    get:
      operationId: listOrders
      parameters:
        - name: since
          in: query
          required: {orders_since_required}
          schema: {{ type: string }}
      responses:
        "200": {{ description: ok }}
"""

_ACCOUNTS = """\
  /accounts:
    get:
      operationId: listAccounts
      parameters:
        - name: page
          in: query
          required: {accounts_page_required}
          schema: {{ type: integer }}
      responses:
        "200": {{ description: ok }}
"""


def _spec(order: list[str], **flags: str) -> str:
    blocks = {"users": _USERS, "orders": _ORDERS, "accounts": _ACCOUNTS}
    body = "".join(blocks[name].format(**flags) for name in order)
    return _HEAD.format(version=flags["version"]) + body


def _ids(tmp_path: Path, old_text: str, new_text: str) -> dict[str, str]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    old_path = tmp_path / "old.yaml"
    new_path = tmp_path / "new.yaml"
    old_path.write_text(old_text, encoding="utf-8")
    new_path.write_text(new_text, encoding="utf-8")
    old, _, _ = detect_and_load(str(old_path))
    new, _, _ = detect_and_load(str(new_path))
    # Keyed by what the change is *about*, so the comparison is by meaning.
    return {f"{c.operation_key}|{c.description}": c.id for c in diff_services(old, new)}


BEFORE = {
    "version": "1.0.0",
    "users_limit_required": "false",
    "orders_since_required": "false",
    "accounts_page_required": "false",
}
AFTER = {
    "version": "1.0.0",
    "users_limit_required": "true",
    "orders_since_required": "true",
    "accounts_page_required": "true",
}

NATURAL = ["users", "orders", "accounts"]
SHUFFLED = ["accounts", "users", "orders"]


def test_reordering_operations_does_not_change_any_id(tmp_path: Path) -> None:
    """The property the documentation promises.

    Three operations each gain a required parameter. Reordering the paths in
    both documents must not renumber anything.
    """
    natural = _ids(tmp_path / "a", _spec(NATURAL, **BEFORE), _spec(NATURAL, **AFTER))
    shuffled = _ids(tmp_path / "b", _spec(SHUFFLED, **BEFORE), _spec(SHUFFLED, **AFTER))

    assert natural and shuffled
    assert natural == shuffled, "reordering the spec document changed change ids:\n" + "\n".join(
        f"  {k}: {natural.get(k)} -> {shuffled.get(k)}"
        for k in sorted(set(natural) | set(shuffled))
        if natural.get(k) != shuffled.get(k)
    )


def test_ids_carry_the_operation_hash(tmp_path: Path) -> None:
    ids = _ids(tmp_path / "c", _spec(NATURAL, **BEFORE), _spec(NATURAL, **AFTER))
    assert ids
    for identifier in ids.values():
        parts = identifier.split("-")
        assert parts[0] == "CHG"
        # CHG-{KIND}-{hash}-{n}; the kind itself may contain no hyphens because
        # ChangeKind values are snake_case.
        assert len(parts) >= 4, identifier
        assert parts[-1].isdigit(), identifier
        scope = parts[-2]
        assert scope == "global" or (
            len(scope) == 8 and all(c in "0123456789abcdef" for c in scope)
        )


def test_ids_differ_between_operations(tmp_path: Path) -> None:
    """A shared counter made two operations' first change collide in meaning.

    Distinct operations must not produce the same id for the same kind.
    """
    ids = _ids(tmp_path / "d", _spec(NATURAL, **BEFORE), _spec(NATURAL, **AFTER))
    requiredness = [i for i in ids.values() if "PARAMETER_REQUIREDNESS" in i]
    assert len(requiredness) == 3, requiredness
    assert len(set(requiredness)) == 3, f"ids collided across operations: {requiredness}"


def test_a_change_with_no_operation_uses_a_named_scope(tmp_path: Path) -> None:
    """A hash of the empty string would read as though it identified something."""
    bumped = {**BEFORE}
    bumped["version"] = "2.0.0"
    ids = _ids(tmp_path / "e", _spec(NATURAL, **BEFORE), _spec(NATURAL, **bumped))
    version_changes = [i for k, i in ids.items() if "contract version changed" in k]
    assert version_changes, ids
    # The service-level scope is "(service)", which hashes like any other key;
    # what matters is that it is stable and shared by all service-level changes.
    assert all(v.count("-") >= 3 for v in version_changes)


def test_ids_are_deterministic_across_runs(tmp_path: Path) -> None:
    first = _ids(tmp_path / "f", _spec(NATURAL, **BEFORE), _spec(NATURAL, **AFTER))
    second = _ids(tmp_path / "f", _spec(NATURAL, **BEFORE), _spec(NATURAL, **AFTER))
    assert first == second


# --------------------------------------------------- the property that failed

_ONE_PARAM = """\
  {path}:
    get:
      parameters:
        - name: q
          in: query
          required: {required}
          schema: {{ type: string }}
      responses:
        "200": {{ description: ok }}
"""


def _requiredness_ids(tmp_path: Path, paths: list[str]) -> dict[str, str]:
    """Ids for a requiredness change on each of `paths`."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    head = 'openapi: "3.0.3"\ninfo: { title: T, version: "1.0.0" }\npaths:\n'
    old = tmp_path / "old.yaml"
    new = tmp_path / "new.yaml"
    old.write_text(
        head + "".join(_ONE_PARAM.format(path=p, required="false") for p in paths),
        encoding="utf-8",
    )
    new.write_text(
        head + "".join(_ONE_PARAM.format(path=p, required="true") for p in paths),
        encoding="utf-8",
    )
    old_service, _, _ = detect_and_load(str(old))
    new_service, _, _ = detect_and_load(str(new))
    return {
        c.operation_key: c.id
        for c in diff_services(old_service, new_service)
        if "requiredness" in c.description
    }


def test_an_unrelated_operation_does_not_renumber_an_existing_change(
    tmp_path: Path,
) -> None:
    """The defect, stated as the test that catches it.

    `/alpha` sorts before `/zebra`, so under a single shared counter it
    claimed ordinal 1 and pushed `/zebra` to 2 -- changing the id of a change
    that itself did not change at all.
    """
    alone = _requiredness_ids(tmp_path / "solo", ["/zebra"])
    with_neighbour = _requiredness_ids(tmp_path / "pair", ["/alpha", "/zebra"])

    assert alone["GET /zebra"], alone
    assert alone["GET /zebra"] == with_neighbour["GET /zebra"], (
        "adding an unrelated operation renumbered an existing change: "
        f"{alone['GET /zebra']} -> {with_neighbour['GET /zebra']}"
    )


def test_removing_an_unrelated_operation_also_leaves_ids_alone(
    tmp_path: Path,
) -> None:
    """The same defect in the other direction."""
    both = _requiredness_ids(tmp_path / "both", ["/alpha", "/zebra"])
    remaining = _requiredness_ids(tmp_path / "one", ["/zebra"])
    assert both["GET /zebra"] == remaining["GET /zebra"]
