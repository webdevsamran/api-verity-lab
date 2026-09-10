"""A hash chain nobody outside the server could check was not evidence.

The chain has been correct since the beginning. What was missing is the only
thing an auditor can use: a document that leaves the building, and a verifier
that reads *only* that document. Verification that runs inside the process that
wrote the log, against the database that holds it, proves nothing -- a party
who can rewrite the entries can rewrite the verifier too.

So the tests below are mostly about the failures, because a tamper-evident log
is only worth having if the tampering is actually detected and named. Each of
the three things a chain cannot do on its own gets a test that shows it cannot,
and then a test that shows what does:

- an edited entry is caught by the chain;
- a **deleted tail** is not, and is caught only against an earlier export;
- a **rebuilt history** is not, and is caught only by the seal.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
from typing import Any

import pytest

from apiverity.cli.main import main
from apiverity.server import Store
from apiverity.server.api import create_app
from apiverity.server.audit_export import (
    EXPORT_SCHEMA,
    LIMITS,
    build_export,
    canonical_bytes,
    entry_hash,
    seal,
    verify_chain,
    verify_export,
)

pytestmark = pytest.mark.integration


@pytest.fixture()
def store() -> Store:
    s = Store(":memory:")
    org = s.create_org("acme")
    for index in range(5):
        s.audit_append(org, "sam", "policy.updated", f"policy-{index}", {"index": index})
    return s


def _export(store: Store, **kwargs: Any) -> dict[str, Any]:
    return store.audit_export(1, **kwargs)


def _run(argv: list[str]) -> tuple[int, dict[str, Any]]:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(io.StringIO()):
        code = main(argv)
    text = buffer.getvalue()
    return code, (json.loads(text) if text.strip().startswith("{") else {})


# ------------------------------------------------------------- the happy path


def test_an_intact_chain_verifies_from_the_document_alone(store: Store) -> None:
    """No database, no server, no network -- the document and nothing else."""
    document = _export(store)
    result = verify_export(document)
    assert result.ok
    assert result.entry_count == 5
    assert result.chain is not None and result.chain.valid


def test_the_export_carries_the_algorithm_in_words(store: Store) -> None:
    """The difference between evidence and a claim: somebody has to be able to
    reimplement the check without reading this codebase."""
    document = _export(store)
    algorithm = document["algorithm"]
    assert algorithm["hash"] == "sha256"
    assert algorithm["basis"] == "{prev_hash}|{ts}|{actor}|{action}|{target}|{payload_json}"
    assert algorithm["first_prev_hash"] == ""


def test_the_export_states_what_it_does_not_prove(store: Store) -> None:
    """An evidence artifact that overstates what it proves is worse than no
    artifact, and the reader of one is not holding the source."""
    document = _export(store)
    assert document["limits"] == LIMITS
    joined = " ".join(document["limits"]).lower()
    assert "does not prove completeness" in joined
    assert "hmac" in joined


def test_the_export_is_every_entry_not_a_page(store: Store) -> None:
    """`audit_list` caps at a hundred for a screen. An export that stopped
    there would be a shorter history presented as the whole one."""
    for index in range(150):
        store.audit_append(1, "sam", "run.completed", f"run-{index}")
    assert len(store.audit_list(1)) == 100
    assert _export(store)["entry_count"] == 155


# ------------------------------------------------- what the chain does catch


def test_an_edited_entry_is_caught_and_named(store: Store) -> None:
    """And named: "invalid" without an entry id sends a responder to read the
    whole table by hand."""
    document = _export(store)
    document["entries"][2]["target"] = "policy-hijacked"
    result = verify_export(document)
    assert not result.ok
    assert result.chain is not None
    assert result.chain.broken_at == document["entries"][2]["id"]
    assert "was edited" in (result.chain.reason or "")


def test_a_removed_middle_entry_breaks_the_link(store: Store) -> None:
    document = _export(store)
    del document["entries"][2]
    result = verify_export(document)
    assert not result.ok
    assert result.chain is not None
    assert "inserted, removed or reordered" in (result.chain.reason or "")


def test_reordering_is_caught(store: Store) -> None:
    document = _export(store)
    document["entries"][1], document["entries"][3] = (
        document["entries"][3],
        document["entries"][1],
    )
    assert not verify_export(document).ok


def test_the_two_failures_are_reported_apart() -> None:
    """A broken link and an edited entry mean different things: one is the
    log's shape, the other is one row's contents."""
    good = {
        "id": 1,
        "ts": "t",
        "actor": "a",
        "action": "x",
        "target": "y",
        "payload_json": "{}",
        "prev_hash": "",
    }
    good["entry_hash"] = entry_hash(good)
    assert verify_chain([good]).valid

    edited = dict(good, target="z")
    assert "was edited" in (verify_chain([edited]).reason or "")

    unlinked = dict(good, prev_hash="deadbeef")
    assert "inserted, removed or reordered" in (verify_chain([unlinked]).reason or "")


# --------------------------------------------- what the chain does NOT catch


def test_a_deleted_tail_still_verifies(store: Store) -> None:
    """The failure that matters most in practice, and the one hashing cannot
    see: the tail is where the chain ends, so nothing points past it."""
    document = _export(store)
    document["entries"] = document["entries"][:3]
    document["entry_count"] = 3
    document["last_entry_hash"] = document["entries"][-1]["entry_hash"]
    assert verify_chain(document["entries"]).valid
    assert verify_export(document).ok  # on its own, this document is clean


def test_a_deleted_tail_is_caught_against_an_earlier_export(store: Store) -> None:
    """Which is why exports are kept rather than regenerated on demand."""
    earlier = _export(store)
    store.audit_append(1, "sam", "approval.granted", "release-9")

    truncated = _export(store)
    truncated["entries"] = truncated["entries"][:2]
    truncated["entry_count"] = 2

    result = verify_export(truncated, against=earlier)
    assert not result.ok
    assert result.continuity == "truncated"
    assert "cannot shrink" in " ".join(result.problems)


def test_a_rebuilt_history_is_caught_against_an_earlier_export(store: Store) -> None:
    """Recomputing every hash produces a chain that verifies. It does not
    produce the *same* chain."""
    earlier = _export(store)
    forged = json.loads(json.dumps(earlier))
    forged["entries"][1]["target"] = "policy-hijacked"
    previous = ""
    for entry in forged["entries"]:
        entry["prev_hash"] = previous
        entry["entry_hash"] = entry_hash(entry)
        previous = entry["entry_hash"]
    forged["last_entry_hash"] = previous
    forged["first_entry_hash"] = forged["entries"][0]["entry_hash"]

    assert verify_chain(forged["entries"]).valid
    result = verify_export(forged, against=earlier)
    assert not result.ok
    assert result.continuity == "rewritten"


def test_continuity_across_two_honest_exports_is_reported(store: Store) -> None:
    earlier = _export(store)
    store.audit_append(1, "sam", "approval.granted", "release-9")
    later = _export(store)
    result = verify_export(later, against=earlier)
    assert result.ok
    assert "continuous" in result.continuity


def test_comparing_two_different_orgs_is_refused(store: Store) -> None:
    other = store.create_org("beta")
    store.audit_append(other, "sam", "org.created", "beta")
    result = verify_export(store.audit_export(other), against=_export(store))
    assert not result.ok
    assert result.continuity == "different org"


# ------------------------------------------------------------------ the seal


def test_a_sealed_document_detects_a_rebuilt_history_without_an_earlier_copy(
    store: Store,
) -> None:
    """The other half. Someone who can rewrite every row can recompute every
    hash -- the algorithm is public -- but not the HMAC, whose key was never
    in the database."""
    document = _export(store, hmac_key=b"a key kept elsewhere")
    assert verify_export(document, hmac_key=b"a key kept elsewhere").seal_state == "valid"

    document["entries"][0]["actor"] = "someone-else"
    assert verify_export(document, hmac_key=b"a key kept elsewhere").seal_state == "invalid"


def test_the_wrong_key_is_not_reported_as_tampering_alone(store: Store) -> None:
    """Both readings are real, so the message says both rather than accusing."""
    document = _export(store, hmac_key=b"right")
    result = verify_export(document, hmac_key=b"wrong")
    assert result.seal_state == "invalid"
    assert "or the key differs" in " ".join(result.problems)


def test_an_unchecked_seal_says_so_rather_than_passing_quietly(store: Store) -> None:
    """ "The seal was fine" and "nobody looked at the seal" are the two things
    an auditor must not confuse."""
    document = _export(store, hmac_key=b"k")
    result = verify_export(document)
    assert result.ok
    assert result.seal_state == "present, not checked (no key supplied)"


def test_a_missing_seal_when_a_key_was_supplied_is_a_problem(store: Store) -> None:
    result = verify_export(_export(store), hmac_key=b"k")
    assert not result.ok
    assert result.seal_state == "expected but absent"


def test_the_sealed_bytes_do_not_include_the_seal(store: Store) -> None:
    """Otherwise the seal would have to cover itself."""
    document = _export(store, hmac_key=b"k")
    assert b'"seal"' not in canonical_bytes(document)
    assert seal(document, b"k") == document["seal"]["value"]


def test_the_seal_is_stable_across_reserialisation(store: Store) -> None:
    """A verifier in another language parses the JSON and re-serialises it.
    Canonical bytes are what make that reach the same digest."""
    document = _export(store, hmac_key=b"k")
    round_tripped = json.loads(json.dumps(document))
    assert verify_export(round_tripped, hmac_key=b"k").seal_state == "valid"


# ------------------------------------------------------------ shape and misuse


def test_a_document_that_is_not_an_export_is_rejected_by_name() -> None:
    result = verify_export({"schema": "something-else", "entries": []})
    assert not result.ok
    assert EXPORT_SCHEMA in result.problems[0]


def test_a_mismatched_count_is_reported(store: Store) -> None:
    document = _export(store)
    document["entry_count"] = 99
    result = verify_export(document)
    assert not result.ok
    assert "entry_count says 99" in " ".join(result.problems)


def test_an_empty_log_exports_rather_than_failing() -> None:
    empty = build_export(
        org_id=1,
        org_name="acme",
        entries=[],
        exported_at="2026-01-01T00:00:00+00:00",
        tool_version="0.0.0",
    )
    assert empty["entry_count"] == 0
    assert empty["last_entry_hash"] is None
    assert verify_export(empty).ok


def test_a_broken_chain_is_still_exported(store: Store) -> None:
    """An export that refused to write a broken chain would let the break be
    hidden by exporting."""
    store.conn.execute("UPDATE audit_events SET target = 'tampered' WHERE id = 2")
    store.conn.commit()
    document = _export(store)
    assert document["chain"]["valid"] is False
    assert document["chain"]["broken_at"] == 2
    assert document["entry_count"] == 5


# -------------------------------------------------------------------- the CLI


def test_the_cli_exports_and_verifies(tmp_path: Path) -> None:
    db = tmp_path / "server.db"
    store = Store(str(db))
    org = store.create_org("acme")
    store.audit_append(org, "sam", "policy.updated", "p1")
    store.close()

    out = tmp_path / "audit.json"
    code, payload = _run(
        [
            "--no-config",
            "audit",
            "export",
            "--db",
            str(db),
            "--org-id",
            "1",
            "-o",
            str(out),
            "--json",
        ]
    )
    assert code == 0
    assert payload["entry_count"] == 1
    assert out.is_file()

    code, payload = _run(["--no-config", "audit", "verify", str(out), "--json"])
    assert code == 0
    assert payload["ok"] is True


def test_the_cli_fails_the_run_when_the_chain_is_broken(tmp_path: Path) -> None:
    """Exit 0 on a broken chain would mean the export succeeded and the log
    did not, which is the wrong half to report."""
    out = tmp_path / "audit.json"
    document = build_export(
        org_id=1,
        org_name="acme",
        entries=[
            {
                "id": 1,
                "ts": "t",
                "actor": "a",
                "action": "x",
                "target": "y",
                "payload_json": "{}",
                "prev_hash": "not-empty",
                "entry_hash": "nope",
            }
        ],
        exported_at="2026-01-01T00:00:00+00:00",
        tool_version="0.0.0",
    )
    out.write_text(json.dumps(document), encoding="utf-8")
    code, payload = _run(["--no-config", "audit", "verify", str(out), "--json"])
    assert code == 1
    assert payload["ok"] is False


def test_the_seal_key_comes_from_the_environment_not_the_command_line(tmp_path: Path) -> None:
    """A key in argv is in the shell history, the CI log and the process
    table."""
    db = tmp_path / "server.db"
    store = Store(str(db))
    org = store.create_org("acme")
    store.audit_append(org, "sam", "policy.updated", "p1")
    store.close()

    out = tmp_path / "audit.json"
    os.environ["APIVERITY_TEST_SEAL"] = "a key"
    try:
        code, payload = _run(
            [
                "--no-config",
                "audit",
                "export",
                "--db",
                str(db),
                "--org-id",
                "1",
                "-o",
                str(out),
                "--hmac-key-env",
                "APIVERITY_TEST_SEAL",
                "--json",
            ]
        )
        assert code == 0
        assert payload["sealed"] is True
        code, payload = _run(
            [
                "--no-config",
                "audit",
                "verify",
                str(out),
                "--hmac-key-env",
                "APIVERITY_TEST_SEAL",
                "--json",
            ]
        )
        assert code == 0
        assert payload["seal"] == "valid"
    finally:
        del os.environ["APIVERITY_TEST_SEAL"]


def test_an_unset_key_variable_is_a_usage_error_not_a_silent_unsealed_export(
    tmp_path: Path,
) -> None:
    """Silently exporting unsealed would hand somebody a document they believe
    is sealed."""
    db = tmp_path / "server.db"
    Store(str(db)).close()
    code, _payload = _run(
        [
            "--no-config",
            "audit",
            "export",
            "--db",
            str(db),
            "--org-id",
            "1",
            "--hmac-key-env",
            "APIVERITY_DEFINITELY_NOT_SET",
            "--json",
        ]
    )
    assert code == 2


# ------------------------------------------------------------------ over HTTP


def test_the_server_serves_the_export_and_names_where_a_chain_broke() -> None:
    store = Store(":memory:")
    app = create_app(store)
    app.config["TESTING"] = True
    with app.test_client() as client:
        body = client.post("/v1/orgs", json={"name": "acme"}).get_json()
        token = str(body["owner_token"])
        headers = {"Authorization": f"Bearer {token}"}

        export = client.get("/v1/audit/export", headers=headers).get_json()
        assert export["schema"] == EXPORT_SCHEMA
        assert export["chain"]["valid"] is True

        store.conn.execute("UPDATE audit_events SET target = 'tampered' WHERE id = 1")
        store.conn.commit()
        listing = client.get("/v1/audit", headers=headers).get_json()
        assert listing["chain_valid"] is False
        assert listing["chain"]["broken_at"] == 1


def test_the_export_route_needs_the_audit_permission() -> None:
    store = Store(":memory:")
    app = create_app(store)
    app.config["TESTING"] = True
    with app.test_client() as client:
        client.post("/v1/orgs", json={"name": "acme"})
        assert client.get("/v1/audit/export").status_code in (401, 403)
