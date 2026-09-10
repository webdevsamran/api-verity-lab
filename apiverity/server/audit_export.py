"""Take the audit chain out of the database, so somebody else can check it.

The server has hashed every audit entry into the previous one since the
beginning, and `audit_verify_chain` returned `True` or `False` about it. Both
halves of that are a problem for the only person the log exists for.

The auditor cannot run it. Verification lived inside the process that wrote the
log, reading the database that holds it, which is the one arrangement that
proves nothing: a party who can rewrite the entries can also rewrite the
verifier. Evidence has to be checkable *away* from the thing it is evidence
about.

And `False` is not an answer. A tamper-evident log that says "invalid" without
saying which entry broke tells a responder to go and read ten thousand rows by
hand, and tells an auditor nothing they can put in a finding.

So: an export document that carries the entries, the chain, and **the algorithm
in words**, plus a verifier that reads only that document. The algorithm block
is not decoration -- it is what lets someone reimplement the check in twenty
lines of anything, which is the difference between evidence and a claim.

## What this does and does not prove

A hash chain proves **modification and reordering**. Change a byte in entry
seventeen and every hash from seventeen on stops matching.

It does not prove **completeness**. Deleting entries from the tail leaves a
chain that verifies perfectly, because the tail is where the chain ends and
nothing points past it. This is the failure that matters most in practice --
somebody removes the last four entries, which are the interesting ones -- and
no amount of hashing inside one document detects it.

What detects it is the previous export. Each export records its
`last_entry_hash`; the next export must still contain that hash, at the index
it had. `verify_export(..., against=previous)` is that check, and it is the
reason exports are worth keeping rather than regenerating on demand.

It also does not prove anything against a party who can rewrite the *whole*
table, because the algorithm is public and they can recompute every hash. What
defends against that is the optional HMAC seal, whose key is supplied from the
environment and appears in neither the database nor the export.

Each of those three sentences is stated in the export document itself, under
`limits`, because an evidence artifact that overstates what it proves is worse
than no artifact.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, field
from typing import Any

#: Bumped when the document shape changes in a way a verifier must know about.
EXPORT_SCHEMA = "apiverity-audit-export/1"

#: The chain, in words. Kept beside the code that implements it so the two
#: cannot drift, and copied into every export so a third party never has to
#: read this file.
CHAIN_ALGORITHM = {
    "hash": "sha256",
    "basis": "{prev_hash}|{ts}|{actor}|{action}|{target}|{payload_json}",
    "encoding": "utf-8",
    "digest": "lowercase hex",
    "first_prev_hash": "",
    "payload_json": "the entry's payload serialised with sorted keys",
    "note": (
        "entry_hash = sha256(basis) for each entry in ascending id order; each entry's "
        "prev_hash must equal the previous entry's entry_hash, and the first entry's "
        "prev_hash is the empty string"
    ),
}

#: What the seal covers, said once.
SEAL_ALGORITHM = {
    "hash": "hmac-sha256",
    "over": (
        "the export document with its `seal` member removed, serialised as JSON with "
        "sorted keys and no whitespace between tokens"
    ),
    "digest": "lowercase hex",
}

LIMITS = [
    "A hash chain proves modification and reordering. It does not prove completeness: "
    "entries deleted from the end leave a chain that verifies.",
    "Truncation of the tail is detected only by comparing this export against an earlier "
    "one -- the earlier export's last_entry_hash must still appear here, at the same index.",
    "A party able to rewrite every row can recompute every hash, because this algorithm is "
    "public. Only the HMAC seal defends against that, and only while its key is held "
    "outside the database.",
]

#: The fields an entry carries into the export. Named explicitly rather than
#: exporting the row: a column added to the table later would otherwise change
#: the sealed bytes and make every stored export fail to verify.
ENTRY_FIELDS = ("id", "ts", "actor", "action", "target", "payload_json", "prev_hash", "entry_hash")


def entry_basis(entry: dict[str, Any]) -> str:
    """The string an entry's hash is taken over."""
    return (
        f"{entry['prev_hash']}|{entry['ts']}|{entry['actor']}"
        f"|{entry['action']}|{entry['target']}|{entry['payload_json']}"
    )


def entry_hash(entry: dict[str, Any]) -> str:
    return hashlib.sha256(entry_basis(entry).encode("utf-8")).hexdigest()


def canonical_bytes(document: dict[str, Any]) -> bytes:
    """The exact bytes a seal covers: the document without its seal, canonical.

    `sort_keys` and no separator whitespace, so a verifier that re-serialises
    the parsed JSON in any language reaches the same bytes.
    """
    without_seal = {k: v for k, v in document.items() if k != "seal"}
    return json.dumps(without_seal, sort_keys=True, separators=(",", ":")).encode("utf-8")


def seal(document: dict[str, Any], key: bytes) -> str:
    return hmac.new(key, canonical_bytes(document), hashlib.sha256).hexdigest()


@dataclass
class ChainStatus:
    """Where the chain broke, not just that it did."""

    valid: bool
    entry_count: int
    #: The `id` of the first entry that failed, and which of the two checks it
    #: failed. `None` when the chain is intact.
    broken_at: int | None = None
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "entry_count": self.entry_count,
            "broken_at": self.broken_at,
            "reason": self.reason,
        }


def verify_chain(entries: list[dict[str, Any]]) -> ChainStatus:
    """Walk the chain, and stop at the first entry that does not hold.

    Two distinct failures, reported apart because they mean different things:
    a wrong `prev_hash` is a *link* broken -- an entry inserted, removed or
    reordered -- while a wrong `entry_hash` is that entry's own content
    edited.
    """
    previous = ""
    for entry in entries:
        if entry["prev_hash"] != previous:
            return ChainStatus(
                valid=False,
                entry_count=len(entries),
                broken_at=int(entry["id"]),
                reason=(
                    "prev_hash does not match the preceding entry: an entry was inserted, "
                    "removed or reordered here"
                ),
            )
        if entry["entry_hash"] != entry_hash(entry):
            return ChainStatus(
                valid=False,
                entry_count=len(entries),
                broken_at=int(entry["id"]),
                reason="entry_hash does not match the entry's own contents: it was edited",
            )
        previous = entry["entry_hash"]
    return ChainStatus(valid=True, entry_count=len(entries))


def build_export(
    *,
    org_id: int,
    org_name: str | None,
    entries: list[dict[str, Any]],
    exported_at: str,
    tool_version: str,
    hmac_key: bytes | None = None,
) -> dict[str, Any]:
    """The evidence document. Deterministic apart from `exported_at`."""
    rows = [{field_: entry[field_] for field_ in ENTRY_FIELDS} for entry in entries]
    status = verify_chain(rows)
    document: dict[str, Any] = {
        "schema": EXPORT_SCHEMA,
        "tool": "apiverity",
        "tool_version": tool_version,
        "exported_at": exported_at,
        "org_id": org_id,
        "org_name": org_name,
        "entry_count": len(rows),
        "first_entry_hash": rows[0]["entry_hash"] if rows else None,
        "last_entry_hash": rows[-1]["entry_hash"] if rows else None,
        # Recorded even when it is false. An export that silently refused to
        # write a broken chain would let the break be hidden by exporting.
        "chain": status.as_dict(),
        "algorithm": CHAIN_ALGORITHM,
        "seal_algorithm": SEAL_ALGORITHM,
        "limits": LIMITS,
        "entries": rows,
    }
    if hmac_key is not None:
        document["seal"] = {"algorithm": "hmac-sha256", "value": seal(document, hmac_key)}
    return document


@dataclass
class ExportVerification:
    """The answer to "is this evidence", in the parts it is made of."""

    ok: bool
    entry_count: int = 0
    chain: ChainStatus | None = None
    seal_state: str = "absent"
    continuity: str = "not checked"
    problems: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "entry_count": self.entry_count,
            "chain": self.chain.as_dict() if self.chain else None,
            "seal": self.seal_state,
            "continuity": self.continuity,
            "problems": self.problems,
        }


def verify_export(
    document: dict[str, Any],
    *,
    hmac_key: bytes | None = None,
    against: dict[str, Any] | None = None,
) -> ExportVerification:
    """Check an export using nothing but the export.

    No database, no server, no network. That is the whole point: a verifier
    that needs the system under audit is a verifier the system under audit can
    lie to.
    """
    problems: list[str] = []
    if document.get("schema") != EXPORT_SCHEMA:
        return ExportVerification(
            ok=False,
            problems=[f"not an {EXPORT_SCHEMA} document (schema: {document.get('schema')!r})"],
        )

    entries = document.get("entries")
    if not isinstance(entries, list):
        return ExportVerification(ok=False, problems=["`entries` is missing or not a list"])

    status = verify_chain(entries)
    if not status.valid:
        problems.append(f"chain broken at entry {status.broken_at}: {status.reason}")

    declared = document.get("entry_count")
    if declared != len(entries):
        problems.append(f"entry_count says {declared}, the document carries {len(entries)}")
    if entries:
        if document.get("first_entry_hash") != entries[0]["entry_hash"]:
            problems.append("first_entry_hash does not match the first entry")
        if document.get("last_entry_hash") != entries[-1]["entry_hash"]:
            problems.append("last_entry_hash does not match the last entry")

    seal_state = "absent"
    stored = document.get("seal")
    if hmac_key is not None:
        if not isinstance(stored, dict) or "value" not in stored:
            seal_state = "expected but absent"
            problems.append("a key was supplied and the document carries no seal")
        elif hmac.compare_digest(str(stored["value"]), seal(document, hmac_key)):
            seal_state = "valid"
        else:
            seal_state = "invalid"
            problems.append("the seal does not match: the document was altered, or the key differs")
    elif isinstance(stored, dict):
        # Reported rather than ignored. "The seal was fine" and "nobody looked
        # at the seal" are the two things an auditor must not confuse.
        seal_state = "present, not checked (no key supplied)"

    continuity = "not checked"
    if against is not None:
        continuity = _continuity(document, against, problems)

    return ExportVerification(
        ok=not problems,
        entry_count=len(entries),
        chain=status,
        seal_state=seal_state,
        continuity=continuity,
        problems=problems,
    )


def _continuity(document: dict[str, Any], previous: dict[str, Any], problems: list[str]) -> str:
    """Does this export still contain the previous one, unchanged?

    The check the chain cannot do for itself. Every entry the earlier export
    recorded must appear here, at the same index, with the same hash -- so a
    tail that was deleted, or a history that was rebuilt, shows up as a
    mismatch rather than as a chain that verifies beautifully and is missing
    the four entries somebody minded about.
    """
    earlier = previous.get("entries")
    current = document.get("entries")
    if not isinstance(earlier, list) or not isinstance(current, list):
        problems.append("the earlier document has no `entries` to compare against")
        return "unreadable"
    if previous.get("org_id") != document.get("org_id"):
        problems.append(
            f"the earlier export is for org {previous.get('org_id')}, this one for "
            f"{document.get('org_id')}"
        )
        return "different org"
    if len(current) < len(earlier):
        problems.append(
            f"this export has {len(current)} entries, the earlier one had {len(earlier)}: "
            "an append-only log cannot shrink"
        )
        return "truncated"
    for index, (before, now) in enumerate(zip(earlier, current, strict=False)):
        if before["entry_hash"] != now["entry_hash"]:
            problems.append(
                f"entry {index} differs from the earlier export "
                f"({before['entry_hash'][:12]}... -> {now['entry_hash'][:12]}...): "
                "history was rewritten"
            )
            return "rewritten"
    return f"continuous ({len(earlier)} earlier entries unchanged)"


__all__ = [
    "CHAIN_ALGORITHM",
    "ENTRY_FIELDS",
    "EXPORT_SCHEMA",
    "LIMITS",
    "SEAL_ALGORITHM",
    "ChainStatus",
    "ExportVerification",
    "build_export",
    "canonical_bytes",
    "entry_basis",
    "entry_hash",
    "seal",
    "verify_chain",
    "verify_export",
]
