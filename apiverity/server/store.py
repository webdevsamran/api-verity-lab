"""SQLite-backed store for the self-hosted API Verity Lab server.

Modular-monolith friendly: one file, explicit schema, no ORM dependency.
All timestamps are UTC ISO-8601. Audit events are hash-chained so tampering
is detectable.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS orgs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id INTEGER NOT NULL REFERENCES orgs(id),
    subject TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL CHECK (role IN ('owner','admin','member','viewer')),
    kind TEXT NOT NULL DEFAULT 'user' CHECK (kind IN ('user','service_account')),
    token_hash TEXT,
    UNIQUE (org_id, subject)
);
CREATE TABLE IF NOT EXISTS contracts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id INTEGER NOT NULL REFERENCES orgs(id),
    title TEXT NOT NULL,
    version TEXT NOT NULL,
    protocol TEXT NOT NULL,
    checksum TEXT NOT NULL,
    spec_json TEXT NOT NULL,
    published_by TEXT NOT NULL,
    published_at TEXT NOT NULL,
    superseded_by INTEGER,
    UNIQUE (org_id, title, version)
);
CREATE TABLE IF NOT EXISTS findings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    contract_id INTEGER NOT NULL REFERENCES contracts(id),
    rule_id TEXT NOT NULL,
    severity TEXT NOT NULL,
    message TEXT NOT NULL,
    operation_key TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id INTEGER NOT NULL REFERENCES orgs(id),
    kind TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    requested_by TEXT NOT NULL,
    result_json TEXT,
    verification_for TEXT,
    environment TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS environments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id INTEGER NOT NULL REFERENCES orgs(id),
    name TEXT NOT NULL,
    base_url TEXT NOT NULL,
    safety_class TEXT NOT NULL DEFAULT 'dev',
    owner TEXT,
    allowed_modes TEXT NOT NULL DEFAULT 'read-only',
    UNIQUE (org_id, name)
);
CREATE TABLE IF NOT EXISTS policies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id INTEGER NOT NULL REFERENCES orgs(id),
    name TEXT NOT NULL,
    content TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (org_id, name)
);
CREATE TABLE IF NOT EXISTS approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id INTEGER NOT NULL REFERENCES orgs(id),
    contract_title TEXT NOT NULL,
    from_version TEXT NOT NULL,
    to_version TEXT NOT NULL,
    justification TEXT NOT NULL,
    migration_guide TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected')),
    requested_by TEXT NOT NULL,
    decided_by TEXT,
    created_at TEXT NOT NULL,
    decided_at TEXT
);
CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id INTEGER NOT NULL REFERENCES orgs(id),
    ts TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    target TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    prev_hash TEXT NOT NULL DEFAULT '',
    entry_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS webhooks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id INTEGER NOT NULL REFERENCES orgs(id),
    url TEXT NOT NULL,
    secret_ref TEXT NOT NULL,
    events TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class Store:
    """SQLite persistence for organizations, contracts, runs and governance."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # --- orgs & users ---------------------------------------------------

    def create_org(self, name: str) -> int:
        cur = self.conn.execute("INSERT INTO orgs (name, created_at) VALUES (?, ?)", (name, _now()))
        self.conn.commit()
        return int(cur.lastrowid or 0)

    def get_org(self, org_id: int) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM orgs WHERE id = ?", (org_id,)).fetchone()
        return dict(row) if row else None

    def add_user(
        self,
        org_id: int,
        subject: str,
        role: str,
        *,
        display_name: str = "",
        kind: str = "user",
        token: str | None = None,
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO users (org_id, subject, display_name, role, kind, token_hash)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (org_id, subject, display_name, role, kind, _hash_token(token) if token else None),
        )
        self.conn.commit()
        return int(cur.lastrowid or 0)

    def resolve_token(self, token: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM users WHERE token_hash = ?", (_hash_token(token),)
        ).fetchone()
        return dict(row) if row else None

    def list_users(self, org_id: int) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT id, subject, display_name, role, kind FROM users WHERE org_id = ?",
            (org_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # --- contracts --------------------------------------------------------

    def publish_contract(
        self,
        org_id: int,
        title: str,
        version: str,
        protocol: str,
        spec: dict[str, Any],
        published_by: str,
    ) -> int:
        checksum = hashlib.sha256(json.dumps(spec, sort_keys=True).encode("utf-8")).hexdigest()
        # supersede any prior latest? keep full history; mark nothing deleted
        cur = self.conn.execute(
            "INSERT INTO contracts (org_id, title, version, protocol, checksum,"
            " spec_json, published_by, published_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (org_id, title, version, protocol, checksum, json.dumps(spec), published_by, _now()),
        )
        self.conn.commit()
        return int(cur.lastrowid or 0)

    def list_contracts(self, org_id: int, title: str | None = None) -> list[dict[str, Any]]:
        sql = (
            "SELECT id, title, version, protocol, checksum, published_by, published_at"
            " FROM contracts WHERE org_id = ?"
        )
        params: tuple[Any, ...] = (org_id,)
        if title:
            sql += " AND title = ?"
            params = (org_id, title)
        rows = self.conn.execute(sql + " ORDER BY published_at", params).fetchall()
        return [dict(r) for r in rows]

    def get_contract(self, contract_id: int) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM contracts WHERE id = ?", (contract_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["spec"] = json.loads(d.pop("spec_json"))
        return d

    # --- findings -----------------------------------------------------------

    def add_findings(self, contract_id: int, findings: list[dict[str, Any]]) -> int:
        count = 0
        for f in findings:
            self.conn.execute(
                "INSERT INTO findings (contract_id, rule_id, severity, message,"
                " operation_key, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    contract_id,
                    f.get("rule_id", ""),
                    f.get("severity", "INFO"),
                    f.get("message", ""),
                    f.get("operation_key"),
                    _now(),
                ),
            )
            count += 1
        self.conn.commit()
        return count

    def list_findings(self, contract_id: int) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM findings WHERE contract_id = ?", (contract_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    # --- runs -----------------------------------------------------------------

    def record_run(
        self,
        org_id: int,
        kind: str,
        requested_by: str,
        *,
        result: dict[str, Any] | None = None,
        status: str = "queued",
        verification_for: str | None = None,
        environment: str | None = None,
    ) -> int:
        ts = _now()
        cur = self.conn.execute(
            "INSERT INTO runs (org_id, kind, status, requested_by, result_json,"
            " verification_for, environment, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                org_id,
                kind,
                status,
                requested_by,
                json.dumps(result) if result else None,
                verification_for,
                environment,
                ts,
                ts,
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid or 0)

    def update_run(self, run_id: int, *, status: str, result: dict[str, Any] | None = None) -> None:
        self.conn.execute(
            "UPDATE runs SET status = ?, result_json = COALESCE(?, result_json),"
            " updated_at = ? WHERE id = ?",
            (status, json.dumps(result) if result else None, _now(), run_id),
        )
        self.conn.commit()

    def get_run(self, run_id: int) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["result"] = json.loads(d["result_json"]) if d.pop("result_json") else None
        return d

    def cancel_run(self, run_id: int) -> bool:
        row = self.get_run(run_id)
        if not row or row["status"] not in ("queued", "running"):
            return False
        self.update_run(run_id, status="cancelled")
        return True

    # --- environments ------------------------------------------------------

    def register_environment(
        self,
        org_id: int,
        name: str,
        base_url: str,
        safety_class: str,
        owner: str | None = None,
        allowed_modes: str = "read-only",
    ) -> int:
        cur = self.conn.execute(
            "INSERT OR REPLACE INTO environments (org_id, name, base_url, safety_class,"
            " owner, allowed_modes) VALUES (?, ?, ?, ?, ?, ?)",
            (org_id, name, base_url, safety_class, owner, allowed_modes),
        )
        self.conn.commit()
        return int(cur.lastrowid or 0)

    def list_environments(self, org_id: int) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM environments WHERE org_id = ?", (org_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    # --- policies -------------------------------------------------------------

    def set_policy(self, org_id: int, name: str, content: str) -> None:
        self.conn.execute(
            "INSERT INTO policies (org_id, name, content, updated_at) VALUES (?, ?, ?, ?)"
            " ON CONFLICT(org_id, name) DO UPDATE SET content = excluded.content,"
            " updated_at = excluded.updated_at",
            (org_id, name, content, _now()),
        )
        self.conn.commit()

    def get_policy(self, org_id: int, name: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM policies WHERE org_id = ? AND name = ?", (org_id, name)
        ).fetchone()
        return dict(row) if row else None

    # --- approvals ---------------------------------------------------------------

    def request_approval(
        self,
        org_id: int,
        contract_title: str,
        from_version: str,
        to_version: str,
        justification: str,
        requested_by: str,
        migration_guide: str | None = None,
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO approvals (org_id, contract_title, from_version, to_version,"
            " justification, migration_guide, requested_by, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                org_id,
                contract_title,
                from_version,
                to_version,
                justification,
                migration_guide,
                requested_by,
                _now(),
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid or 0)

    def decide_approval(self, approval_id: int, decision: str, decided_by: str) -> bool:
        if decision not in ("approved", "rejected"):
            raise ValueError(decision)
        cur = self.conn.execute(
            "UPDATE approvals SET status = ?, decided_by = ?, decided_at = ?"
            " WHERE id = ? AND status = 'pending'",
            (decision, decided_by, _now(), approval_id),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def get_approval(self, approval_id: int) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
        return dict(row) if row else None

    # --- audit (hash-chained, append-only) ------------------------------------------

    def audit_append(
        self,
        org_id: int,
        actor: str,
        action: str,
        target: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        last = self.conn.execute(
            "SELECT entry_hash FROM audit_events WHERE org_id = ? ORDER BY id DESC LIMIT 1",
            (org_id,),
        ).fetchone()
        prev_hash = last["entry_hash"] if last else ""
        payload_json = json.dumps(payload or {}, sort_keys=True)
        ts = _now()
        basis = f"{prev_hash}|{ts}|{actor}|{action}|{target}|{payload_json}"
        entry_hash = hashlib.sha256(basis.encode("utf-8")).hexdigest()
        cur = self.conn.execute(
            "INSERT INTO audit_events (org_id, ts, actor, action, target, payload_json,"
            " prev_hash, entry_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (org_id, ts, actor, action, target, payload_json, prev_hash, entry_hash),
        )
        self.conn.commit()
        return {
            "id": int(cur.lastrowid or 0),
            "ts": ts,
            "actor": actor,
            "action": action,
            "target": target,
            "entry_hash": entry_hash,
        }

    def audit_list(self, org_id: int, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM audit_events WHERE org_id = ? ORDER BY id DESC LIMIT ?",
            (org_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def audit_verify_chain(self, org_id: int) -> bool:
        rows = self.conn.execute(
            "SELECT * FROM audit_events WHERE org_id = ? ORDER BY id", (org_id,)
        ).fetchall()
        prev = ""
        for r in rows:
            basis = (
                f"{r['prev_hash']}|{r['ts']}|{r['actor']}|{r['action']}|{r['target']}"
                f"|{r['payload_json']}"
            )
            if (
                r["prev_hash"] != prev
                or r["entry_hash"] != hashlib.sha256(basis.encode("utf-8")).hexdigest()
            ):
                return False
            prev = r["entry_hash"]
        return True

    # --- webhooks ------------------------------------------------------------------

    def register_webhook(self, org_id: int, url: str, secret_ref: str, events: list[str]) -> int:
        cur = self.conn.execute(
            "INSERT INTO webhooks (org_id, url, secret_ref, events, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (org_id, url, secret_ref, json.dumps(events), _now()),
        )
        self.conn.commit()
        return int(cur.lastrowid or 0)

    def list_webhooks(self, org_id: int, event: str | None = None) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM webhooks WHERE org_id = ? AND active = 1", (org_id,)
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["events"] = json.loads(d["events"])
            if event is None or event in d["events"]:
                out.append(d)
        return out

    # --- retention --------------------------------------------------------------------

    def purge_older_than(self, days: int) -> dict[str, int]:
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        purged: dict[str, int] = {}
        for table in ("findings",):
            cur = self.conn.execute(f"DELETE FROM {table} WHERE created_at < ?", (cutoff,))
            purged[table] = cur.rowcount
        cur = self.conn.execute("DELETE FROM runs WHERE created_at < ?", (cutoff,))
        purged["runs"] = cur.rowcount
        self.conn.commit()
        return purged
