"""Explicit SQLite schema and helpers for the self-hosted server store.

Kept separate from :class:`apiverity.server.store.Store` so the DDL can be
inspected or migrated without instantiating a connection. No ORM dependency,
by design. All timestamps are UTC ISO-8601.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

SCHEMA = """
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
CREATE TABLE IF NOT EXISTS workers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id INTEGER NOT NULL REFERENCES orgs(id),
    name TEXT NOT NULL,
    labels TEXT NOT NULL DEFAULT '[]',
    capacity INTEGER NOT NULL DEFAULT 1,
    last_seen TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    UNIQUE (org_id, name)
);
CREATE TABLE IF NOT EXISTS run_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(id),
    ts TEXT NOT NULL,
    message TEXT NOT NULL,
    pct INTEGER
);
CREATE INDEX IF NOT EXISTS idx_runs_org_status ON runs(org_id, status);
"""


def now_utc() -> str:
    return datetime.now(UTC).isoformat()


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
