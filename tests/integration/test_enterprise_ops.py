"""Enterprise operations: worker enrollment, job queue, SSE progress,
backup/restore/export/import and API rate limiting."""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

import pytest

from apiverity.exporters.otel import TraceRecorder, redact_attributes
from apiverity.server import Store
from apiverity.server.api import create_app
from apiverity.server.jobs import JobQueue, QueueFull


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def store() -> Store:
    return Store(":memory:")


@pytest.fixture()
def client(store: Store):
    app = create_app(store, max_active_jobs=2)
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _mk_org(client, name: str = "acme") -> tuple[int, str]:
    body = client.post("/v1/orgs", json={"name": name}).get_json()
    return int(body["org_id"]), str(body["owner_token"])


class TestWorkersAndJobs:
    def test_worker_enrollment_and_listing(self, client) -> None:
        _, token = _mk_org(client)
        r = client.post(
            "/v1/workers", headers=_auth(token), json={"name": "runner-1", "labels": ["gpu"]}
        )
        assert r.status_code == 201
        workers = client.get("/v1/workers", headers=_auth(token)).get_json()
        assert len(workers) == 1
        assert workers[0]["name"] == "runner-1"
        assert workers[0]["labels"] == ["gpu"]
        # re-enroll is a heartbeat, not a duplicate
        client.post("/v1/workers", headers=_auth(token), json={"name": "runner-1"})
        assert len(client.get("/v1/workers", headers=_auth(token)).get_json()) == 1

    def test_enqueue_claim_complete_flow(self, client) -> None:
        _, token = _mk_org(client)
        run_id = client.post(
            "/v1/jobs",
            headers=_auth(token),
            json={"kind": "test", "idempotency_key": "ci-run-42"},
        ).get_json()["run_id"]
        claimed = client.post("/v1/jobs/claim", headers=_auth(token), json={"worker": "runner-1"})
        assert claimed.status_code == 200
        job = claimed.get_json()
        assert job["id"] == run_id
        assert job["status"] == "running"
        assert job["worker_name"] == "runner-1"
        # empty queue → 204
        empty = client.post("/v1/jobs/claim", headers=_auth(token), json={"worker": "runner-1"})
        assert empty.status_code == 204

    def test_idempotent_enqueue(self, client) -> None:
        _, token = _mk_org(client)
        first = client.post(
            "/v1/jobs", headers=_auth(token), json={"kind": "load", "idempotency_key": "k1"}
        )
        assert first.status_code == 201
        second = client.post(
            "/v1/jobs", headers=_auth(token), json={"kind": "load", "idempotency_key": "k1"}
        )
        assert second.status_code == 200
        assert second.get_json()["run_id"] == first.get_json()["run_id"]
        assert second.get_json()["deduplicated"] is True

    def test_backpressure_rejects_with_409(self, client) -> None:
        _, token = _mk_org(client)
        for i in range(2):  # max_active_jobs=2 in fixture
            ok = client.post("/v1/jobs", headers=_auth(token), json={"kind": f"t{i}"})
            assert ok.status_code == 201
        full = client.post("/v1/jobs", headers=_auth(token), json={"kind": "third"})
        assert full.status_code == 409

    def test_cross_org_isolation_on_claim(self, client) -> None:
        _, tok_a = _mk_org(client, "a")
        _, tok_b = _mk_org(client, "b")
        client.post("/v1/jobs", headers=_auth(tok_a), json={"kind": "test"})
        claimed_b = client.post("/v1/jobs/claim", headers=_auth(tok_b), json={"worker": "w"})
        assert claimed_b.status_code == 204  # org B cannot claim org A's jobs

    def test_sse_progress_stream(self, client, store: Store) -> None:
        _, token = _mk_org(client)
        run_id = client.post("/v1/jobs", headers=_auth(token), json={"kind": "fuzz"}).get_json()[
            "run_id"
        ]
        store.append_run_event(run_id, "generated 100 cases", 50)
        resp = client.get(f"/v1/runs/{run_id}/events", headers=_auth(token))
        assert resp.status_code == 200
        assert resp.mimetype == "text/event-stream"
        body = resp.get_data(as_text=True)
        assert "event: progress" in body
        assert "generated 100 cases" in body
        assert "event: status" in body
        # other org's runs are not readable via SSE
        _, tok_b = _mk_org(client, "other")
        assert client.get(f"/v1/runs/{run_id}/events", headers=_auth(tok_b)).status_code == 404


class TestRateLimit:
    def test_fixed_window_limit(self, store: Store) -> None:
        app = create_app(store, rate_limit_per_minute=3)
        app.config["TESTING"] = True
        with app.test_client() as c:
            assert c.get("/healthz").status_code == 200  # health exempt
            org = c.post("/v1/orgs", json={"name": "rl"}).get_json()
            hdr = {"Authorization": f"Bearer {org['owner_token']}"}
            codes = [c.get("/v1/workers", headers=hdr).status_code for _ in range(5)]
            assert codes.count(200) == 3
            assert codes.count(429) == 2
            metrics = c.get("/metrics").get_data(as_text=True)
            assert "apiverity_rate_limited_total" in metrics


class TestBackupRestoreExportImport:
    def test_backup_and_restore_roundtrip(self, store: Store, tmp_path: Path) -> None:
        org_id = store.create_org("snap")
        store.publish_contract(org_id, "Pay", "1.0.0", "openapi", {"openapi": "3.0"}, "alice")
        backup_path = store.backup_to(tmp_path / "backups" / "snap.db")
        assert backup_path.exists()
        restored = Store.restore_from(backup_path)
        contracts = restored.list_contracts(org_id)
        assert len(contracts) == 1
        assert contracts[0]["title"] == "Pay"

    def test_export_excludes_token_hashes_and_import_creates_new_org(self, store: Store) -> None:
        org_id = store.create_org("exp")
        store.add_user(org_id, "alice", "owner", token="secret-token-value")
        store.set_policy(org_id, "breaking", "max_breaking=0")
        snap = store.export_org(org_id)
        assert "token_hash" not in json.dumps(snap["users"])
        new_id = store.import_org(snap)
        assert new_id != org_id
        users = store.list_users(new_id)
        assert [u["subject"] for u in users] == ["alice"]
        assert store.get_policy(new_id, "breaking")["content"] == "max_breaking=0"
        # restored audit chain still verifies (append-only history preserved)
        assert store.audit_verify_chain(new_id)

    def test_backup_file_is_valid_sqlite(self, store: Store, tmp_path: Path) -> None:
        org_id = store.create_org("dbcheck")
        store.record_run(org_id, "test", "a", status="passed")
        p = store.backup_to(tmp_path / "x.db")
        conn = sqlite3.connect(str(p))
        try:
            n = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        finally:
            conn.close()
        assert n == 1


class TestOtelExport:
    def test_sensitive_attributes_redacted(self) -> None:
        rec = TraceRecorder(seed="run-1")
        h = rec.start_span(
            "apiverity.test",
            operation="GET /users",
            authorization="Bearer sk-live-123",
            request_body='{"password": "hunter2"}',
            case_count=9,
        )
        rec.end_span(h, status="ok")
        blob = json.dumps(rec.to_otlp_json())
        assert "sk-live-123" not in blob
        assert "hunter2" not in blob
        assert "[REDACTED]" in blob
        assert "GET /users" in blob

    def test_redact_attributes_util(self) -> None:
        out = redact_attributes({"api_key": "k", "Cookie": "c", "count": 1})
        assert out == {"api_key": "[REDACTED]", "Cookie": "[REDACTED]", "count": 1}

    def test_export_only_to_explicit_endpoint(self) -> None:
        rec = TraceRecorder(seed="run-2")
        h = rec.start_span("op")
        rec.end_span(h)
        sent: list[tuple[str, dict]] = []
        code = rec.export(
            "https://otel.internal:4318/v1/traces",
            transport=lambda url, body: (sent.append((url, body)), 200)[1],
        )
        assert code == 200
        assert sent[0][0].endswith("/v1/traces")
        assert sent[0][1]["resourceSpans"][0]["scopeSpans"][0]["spans"]

    def test_trace_ids_deterministic_per_seed(self) -> None:
        assert TraceRecorder(seed="s").trace_id == TraceRecorder(seed="s").trace_id


class TestJobQueueUnit:
    def test_cancel_appends_event(self, store: Store) -> None:
        q = JobQueue(store)
        run_id, created = q.enqueue(store.create_org("q"), "test", "u")
        assert created
        assert q.cancel(run_id)
        events = store.list_run_events(run_id)
        assert events[-1]["message"] == "cancelled"

    def test_queue_full_exception(self, store: Store) -> None:
        q = JobQueue(store, max_active_per_org=1)
        org_id = store.create_org("qq")
        q.enqueue(org_id, "a", "u")
        with pytest.raises(QueueFull):
            q.enqueue(org_id, "b", "u")


class TestServerDbCli:
    def test_backup_restore_export_import_via_cli(self, store: Store, tmp_path: Path) -> None:
        from apiverity.cli.main import main as cli_main

        org_id = store.create_org("cliorg")
        store.publish_contract(org_id, "Cat", "1.0.0", "openapi", {"openapi": "3.1"}, "alice")
        db = tmp_path / "server.db"
        store2 = Store(db)
        store2.publish_contract(
            store2.create_org("cliorg"), "Cat", "1.0.0", "openapi", {"openapi": "3.1"}, "alice"
        )
        backup = tmp_path / "snap.db"
        assert cli_main(["server-db", "backup", "--db", str(db), "-o", str(backup), "--json"]) == 0
        restored_db = tmp_path / "restored.db"
        assert (
            cli_main(
                ["server-db", "restore", "--db", str(backup), "-o", str(restored_db), "--json"]
            )
            == 0
        )
        export_json = tmp_path / "org.json"
        assert (
            cli_main(
                [
                    "server-db",
                    "export",
                    "--db",
                    str(restored_db),
                    "--org-id",
                    "1",
                    "-o",
                    str(export_json),
                    "--json",
                ]
            )
            == 0
        )
        snap = json.loads(export_json.read_text(encoding="utf-8"))
        assert snap["contracts"][0]["title"] == "Cat"
        assert cli_main(["server-db", "import", "--db", str(db), "--input", str(export_json)]) == 0


def _parallel_enqueues(path: Path, org_id: int, key: str, results: list[int]) -> None:
    store_t = Store(path)
    q = JobQueue(store_t)
    run_id, _ = q.enqueue(org_id, "test", "u", idempotency_key=key)
    results.append(run_id)


class TestIdempotencyUnderConcurrency:
    def test_duplicate_threads_get_one_run(self, tmp_path: Path) -> None:
        db_path = tmp_path / "conc.db"
        org_id = Store(db_path).create_org("conc")
        results: list[int] = []
        threads = [
            threading.Thread(target=_parallel_enqueues, args=(db_path, org_id, "same", results))
            for _ in range(6)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(set(results)) == 1
