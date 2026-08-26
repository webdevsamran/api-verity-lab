"""SQLite-backed store for the self-hosted API Verity Lab server.

Modular-monolith friendly: one file, explicit schema, no ORM dependency.
All timestamps are UTC ISO-8601. Audit events are hash-chained so tampering
is detectable.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from apiverity.server.schema import SCHEMA as _SCHEMA
from apiverity.server.schema import hash_token as _hash_token
from apiverity.server.schema import now_utc as _now


class Store:
    """SQLite persistence for organizations, contracts, runs and governance."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        # backwards-compatible column migrations (no-ops when already applied)
        for stmt in (
            "ALTER TABLE runs ADD COLUMN worker_name TEXT",
            "ALTER TABLE runs ADD COLUMN idempotency_key TEXT",
        ):
            with contextlib.suppress(sqlite3.OperationalError):
                self.conn.execute(stmt)  # column already exists
        self.conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_runs_idem"
            " ON runs(org_id, idempotency_key) WHERE idempotency_key IS NOT NULL"
        )
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

    # --- workers & distributed jobs ---------------------------------------------

    def register_worker(
        self, org_id: int, name: str, *, labels: list[str] | None = None, capacity: int = 1
    ) -> int:
        """Enroll (or re-heartbeat) a runner inside a private network."""
        self.conn.execute(
            "INSERT INTO workers (org_id, name, labels, capacity, last_seen, active)"
            " VALUES (?, ?, ?, ?, ?, 1)"
            " ON CONFLICT(org_id, name) DO UPDATE SET labels = excluded.labels,"
            " capacity = excluded.capacity, last_seen = excluded.last_seen, active = 1",
            (org_id, name, json.dumps(labels or []), capacity, _now()),
        )
        self.conn.commit()
        row = self.conn.execute(
            "SELECT id FROM workers WHERE org_id = ? AND name = ?", (org_id, name)
        ).fetchone()
        assert row is not None
        return int(row["id"])

    def list_workers(self, org_id: int) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT id, name, labels, capacity, last_seen, active FROM workers WHERE org_id = ?",
            (org_id,),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["labels"] = json.loads(d["labels"])
            out.append(d)
        return out

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
        idempotency_key: str | None = None,
    ) -> int:
        ts = _now()
        try:
            cur = self.conn.execute(
                "INSERT INTO runs (org_id, kind, status, requested_by, result_json,"
                " verification_for, environment, created_at, updated_at, idempotency_key)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                    idempotency_key,
                ),
            )
        except sqlite3.IntegrityError:
            # duplicate idempotency key → return the existing run id
            row = self.conn.execute(
                "SELECT id FROM runs WHERE org_id = ? AND idempotency_key = ?",
                (org_id, idempotency_key),
            ).fetchone()
            assert row is not None
            return int(row["id"])
        self.conn.commit()
        return int(cur.lastrowid or 0)

    def find_run_by_idempotency_key(self, org_id: int, key: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM runs WHERE org_id = ? AND idempotency_key = ?", (org_id, key)
        ).fetchone()
        return self._run_row(row) if row else None

    def claim_next_run(self, org_id: int, worker_name: str) -> dict[str, Any] | None:
        """Atomically claim the oldest queued run for this org (worker pull model)."""
        cur = self.conn.execute(
            "UPDATE runs SET status = 'running', worker_name = ?, updated_at = ?"
            " WHERE id = (SELECT id FROM runs WHERE org_id = ? AND status = 'queued'"
            " ORDER BY id LIMIT 1)"
            " RETURNING id",
            (worker_name, _now(), org_id),
        )
        row = cur.fetchone()
        self.conn.commit()
        if row is None:
            return None
        claimed = self.get_run(int(row["id"]))
        self.append_run_event(int(row["id"]), f"claimed by worker '{worker_name}'", 0)
        return claimed

    def active_run_count(self, org_id: int) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM runs WHERE org_id = ? AND status IN ('queued','running')",
            (org_id,),
        ).fetchone()
        return int(row["n"]) if row else 0

    def append_run_event(self, run_id: int, message: str, pct: int | None = None) -> None:
        self.conn.execute(
            "INSERT INTO run_events (run_id, ts, message, pct) VALUES (?, ?, ?, ?)",
            (run_id, _now(), message, pct),
        )
        self.conn.commit()

    def list_run_events(self, run_id: int) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT id, ts, message, pct FROM run_events WHERE run_id = ? ORDER BY id",
            (run_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def _run_row(self, row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        d["result"] = json.loads(d["result_json"]) if d.pop("result_json") else None
        return d

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

    # --- backup / restore / export / import --------------------------------------

    def backup_to(self, path: str | Path) -> Path:
        """Consistent online snapshot via the SQLite backup API."""
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        dest = sqlite3.connect(str(out))
        try:
            self.conn.backup(dest)
            dest.commit()
        finally:
            dest.close()
        return out

    @classmethod
    def restore_from(cls, path: str | Path, *, target: str | Path = ":memory:") -> Store:
        """Restore a backup file into a new store at ``target``."""
        src = sqlite3.connect(f"file:{Path(path)}?mode=ro", uri=True)
        try:
            dest = cls(target)
            src.backup(dest.conn)
            dest.conn.commit()
        finally:
            src.close()
        return dest

    def list_policies(self, org_id: int) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT name, content, updated_at FROM policies WHERE org_id = ?", (org_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def export_org(self, org_id: int) -> dict[str, Any]:
        """Portable JSON snapshot of one organization (no token hashes)."""
        org = self.get_org(org_id)
        if org is None:
            raise KeyError(f"org {org_id} not found")
        users = [{k: v for k, v in u.items() if k != "token_hash"} for u in self.list_users(org_id)]
        contracts = [self.get_contract(c["id"]) for c in self.list_contracts(org_id)]
        return {
            "export_schema_version": 1,
            "exported_utc": _now(),
            "org": org,
            "users": users,
            "contracts": contracts,
            "environments": self.list_environments(org_id),
            "policies": [
                {"name": p["name"], "content": p["content"]} for p in self.list_policies(org_id)
            ],
            "webhooks": self.list_webhooks(org_id),
        }

    def import_org(self, snapshot: dict[str, Any]) -> int:
        """Import an ``export_org`` snapshot as a NEW org; returns the new org id."""
        name = f"{snapshot['org']['name']}-restored-{_now()}"
        org_id = self.create_org(name)
        for u in snapshot.get("users", []):
            self.add_user(
                org_id,
                u["subject"],
                u["role"],
                display_name=u.get("display_name", ""),
                kind=u.get("kind", "user"),
            )
        for c in snapshot.get("contracts", []):
            if c is None:
                continue
            self.publish_contract(
                org_id,
                c["title"],
                c["version"],
                c["protocol"],
                c.get("spec", {}),
                c.get("published_by", "import"),
            )
        for e in snapshot.get("environments", []):
            self.register_environment(
                org_id,
                e["name"],
                e["base_url"],
                e["safety_class"],
                owner=e.get("owner"),
                allowed_modes=e.get("allowed_modes", "read-only"),
            )
        for p in snapshot.get("policies", []):
            self.set_policy(org_id, p["name"], p["content"])
        self.audit_append(org_id, "system", "org.imported", name)
        return org_id
