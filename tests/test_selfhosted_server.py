"""Tests for the self-hosted server: store, RBAC, REST API, audit chain,
webhooks and can-i-deploy."""

from __future__ import annotations

import pytest

from apiverity.server import Store, create_app
from apiverity.server.auth import Identity, LocalTokenProvider, Role, authenticate, authorize
from apiverity.server.webhooks import Delivery, dispatch, sign_payload


@pytest.fixture()
def store() -> Store:
    return Store(":memory:")


@pytest.fixture()
def org(store: Store) -> tuple[int, str]:
    org_id = store.create_org("acme")
    token = "owner-token-123"
    store.add_user(org_id, "alice", "owner", display_name="Alice", token=token)
    return org_id, token


@pytest.fixture()
def client(store: Store, org: tuple[int, str]):
    app = create_app(store)
    app.config["TESTING"] = True
    _, token = org
    client = app.test_client()
    client.environ_base["HTTP_AUTHORIZATION"] = f"Bearer {token}"
    return client


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class TestStore:
    def test_org_and_users(self, store: Store) -> None:
        org_id = store.create_org("beta")
        uid = store.add_user(org_id, "bob", "member", token="tok-bob")
        assert uid > 0
        users = store.list_users(org_id)
        assert [u["subject"] for u in users] == ["bob"]
        resolved = store.resolve_token("tok-bob")
        assert resolved is not None and resolved["role"] == "member"

    def test_contract_publish_and_history(self, store: Store) -> None:
        org_id = store.create_org("c")
        store.publish_contract(org_id, "Catalog", "1.0.0", "openapi", {"openapi": "3.1.0"}, "a")
        i2 = store.publish_contract(
            org_id, "Catalog", "1.1.0", "openapi", {"openapi": "3.1.0"}, "a"
        )
        versions = [c["version"] for c in store.list_contracts(org_id, title="Catalog")]
        assert versions == ["1.0.0", "1.1.0"]
        full = store.get_contract(i2)
        assert full is not None and full["spec"] == {"openapi": "3.1.0"}
        assert len(full["checksum"]) == 64

    def test_audit_chain_tamper_detection(self, store: Store) -> None:
        org_id = store.create_org("d")
        store.audit_append(org_id, "alice", "policy.updated", "breaking")
        store.audit_append(org_id, "alice", "contract.published", "X@1")
        assert store.audit_verify_chain(org_id)
        # tamper with a payload directly in SQL
        store.conn.execute("UPDATE audit_events SET target = 'TAMPERED' WHERE id = 1")
        store.conn.commit()
        assert not store.audit_verify_chain(org_id)

    def test_retention_purge(self, store: Store) -> None:
        org_id = store.create_org("e")
        run_id = store.record_run(org_id, "test", "a", status="passed")
        purged = store.purge_older_than(days=0)
        assert purged["runs"] >= 1
        assert store.get_run(run_id) is None

    def test_run_cancel(self, store: Store) -> None:
        org_id = store.create_org("f")
        rid = store.record_run(org_id, "load", "a")
        assert store.cancel_run(rid)
        assert not store.cancel_run(rid)  # already cancelled
        assert store.get_run(rid)["status"] == "cancelled"


class TestRBAC:
    def _identity(self, role: Role) -> Identity:
        return Identity(subject="x", org_id=1, role=role)

    def test_matrix(self) -> None:
        assert authorize(self._identity(Role.VIEWER), "read")
        assert not authorize(self._identity(Role.VIEWER), "publish_contract")
        assert authorize(self._identity(Role.MEMBER), "publish_contract")
        assert not authorize(self._identity(Role.MEMBER), "set_policy")
        assert authorize(self._identity(Role.ADMIN), "set_policy")
        assert not authorize(self._identity(Role.ADMIN), "create_org")
        assert authorize(self._identity(Role.OWNER), "create_org")

    def test_authenticate_via_local_provider(self, store: Store) -> None:
        org_id = store.create_org("g")
        store.add_user(org_id, "carol", "admin", token="tok-carol")
        identity = authenticate([LocalTokenProvider(store)], "tok-carol")
        assert identity is not None
        assert identity.role == Role.ADMIN and identity.org_id == org_id
        assert authenticate([LocalTokenProvider(store)], "bad") is None


class TestAPI:
    def test_health(self, client) -> None:
        resp = client.get("/healthz")
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "ok"

    def test_readyz(self, client) -> None:
        assert client.get("/readyz").status_code == 200

    def test_metrics_exposed(self, client) -> None:
        text = client.get("/metrics").get_data(as_text=True)
        assert "apiverity_requests_total" in text

    def test_unauthenticated_rejected(self, store: Store) -> None:
        app = create_app(store)
        resp = app.test_client().get("/v1/contracts")
        assert resp.status_code == 401

    def test_viewer_cannot_publish(self, store: Store, org: tuple[int, str]) -> None:
        org_id, _ = org
        store.add_user(org_id, "vic", "viewer", token="tok-vic")
        app = create_app(store)
        resp = app.test_client().post(
            "/v1/contracts",
            json={"title": "T", "version": "1", "spec": {}},
            headers=_auth("tok-vic"),
        )
        assert resp.status_code == 403

    def test_publish_list_get_contract(self, client) -> None:
        resp = client.post(
            "/v1/contracts",
            json={
                "title": "Catalog",
                "version": "2.0.0",
                "protocol": "openapi",
                "spec": {"openapi": "3.1.0"},
                "findings": [{"rule_id": "GOV-X", "severity": "WARN", "message": "m"}],
            },
        )
        assert resp.status_code == 201
        cid = resp.get_json()["contract_id"]
        listing = client.get("/v1/contracts?title=Catalog").get_json()
        assert any(c["version"] == "2.0.0" for c in listing)
        detail = client.get(f"/v1/contracts/{cid}").get_json()
        assert detail["spec"] == {"openapi": "3.1.0"}
        findings = client.get(f"/v1/contracts/{cid}/findings").get_json()
        assert findings[0]["rule_id"] == "GOV-X"

    def test_cross_org_isolation(self, store: Store) -> None:
        o1 = store.create_org("one")
        t1 = "tok-one"
        store.add_user(o1, "u1", "owner", token=t1)
        o2 = store.create_org("two")
        t2 = "tok-two"
        store.add_user(o2, "u2", "owner", token=t2)
        app = create_app(store)
        c = app.test_client()
        cid = c.post(
            "/v1/contracts", json={"title": "S", "version": "1", "spec": {}}, headers=_auth(t1)
        ).get_json()["contract_id"]
        assert c.get(f"/v1/contracts/{cid}", headers=_auth(t2)).status_code == 404

    def test_runs_lifecycle(self, client) -> None:
        rid = client.post(
            "/v1/runs",
            json={
                "kind": "verification",
                "verification_for": "Catalog@2.0.0",
                "environment": "staging",
                "status": "passed",
            },
        ).get_json()["run_id"]
        run = client.get(f"/v1/runs/{rid}").get_json()
        assert run["status"] == "passed"
        assert client.post(f"/v1/runs/{rid}/cancel").status_code == 409

    def test_can_i_deploy_flow(self, client) -> None:
        client.post("/v1/contracts", json={"title": "Pay", "version": "3.1.0", "spec": {}})
        denied = client.post(
            "/v1/can-i-deploy",
            json={"provider": "Pay", "provider_version": "3.1.0", "environment": "prod"},
        ).get_json()
        assert denied["deployable"] is False
        client.post(
            "/v1/runs",
            json={
                "kind": "verification",
                "verification_for": "Pay@3.1.0",
                "environment": "prod",
                "status": "passed",
            },
        )
        allowed = client.post(
            "/v1/can-i-deploy",
            json={"provider": "Pay", "provider_version": "3.1.0", "environment": "prod"},
        ).get_json()
        assert allowed["deployable"] is True

    def test_approvals_rbac_and_flow(self, store: Store, org: tuple[int, str]) -> None:
        org_id, owner_token = org
        store.add_user(org_id, "mem", "member", token="tok-mem")
        store.add_user(org_id, "adm", "admin", token="tok-adm")
        app = create_app(store)
        c = app.test_client()
        aid = c.post(
            "/v1/approvals",
            headers=_auth("tok-mem"),
            json={
                "contract_title": "Pay",
                "from_version": "1.0.0",
                "to_version": "2.0.0",
                "justification": "removing legacy field",
            },
        ).get_json()["approval_id"]
        # member cannot decide
        assert (
            c.post(
                f"/v1/approvals/{aid}/decision",
                headers=_auth("tok-mem"),
                json={"decision": "approved"},
            ).status_code
            == 403
        )
        assert (
            c.post(
                f"/v1/approvals/{aid}/decision",
                headers=_auth("tok-adm"),
                json={"decision": "approved"},
            ).status_code
            == 200
        )
        # double decision conflicts
        assert (
            c.post(
                f"/v1/approvals/{aid}/decision",
                headers=_auth(owner_token),
                json={"decision": "approved"},
            ).status_code
            == 409
        )

    def test_audit_endpoint_chain_valid(self, client) -> None:
        client.post("/v1/contracts", json={"title": "A", "version": "1", "spec": {}})
        data = client.get("/v1/audit").get_json()
        assert data["chain_valid"] is True
        assert data["events"]

    def test_webhook_registration_and_delivery(self, store: Store, org: tuple[int, str]) -> None:
        delivered: list[tuple[str, str, str]] = []

        def transport(url: str, body: str, headers: dict[str, str]) -> int:
            delivered.append((url, body, headers.get("X-Verity-Signature", "")))
            return 200

        app = create_app(
            store, webhook_transport=transport, secret_resolver=lambda ref: f"secret-for-{ref}"
        )
        c = app.test_client()
        owner = _auth("owner-token-123")
        c.post(
            "/v1/webhooks",
            headers=owner,
            json={
                "url": "https://hooks.internal/verity",
                "secret_ref": "wh-1",
                "events": ["contract.published"],
            },
        )
        c.post("/v1/contracts", headers=owner, json={"title": "W", "version": "1", "spec": {}})
        assert len(delivered) == 1
        url, body, sig = delivered[0]
        assert url == "https://hooks.internal/verity"
        assert sig == sign_payload("secret-for-wh-1", body)

    def test_policies(self, client) -> None:
        assert (
            client.put("/v1/policies/breaking", json={"content": "max_breaking=0"}).status_code
            == 200
        )
        got = client.get("/v1/policies/breaking").get_json()
        assert got["content"] == "max_breaking=0"


class TestWebhookSigning:
    def test_sign_deterministic(self) -> None:
        assert sign_payload("s", "body") == sign_payload("s", "body")
        assert sign_payload("s", "body") != sign_payload("other", "body")

    def test_dispatch_filters_events(self) -> None:
        calls: list[str] = []
        result = dispatch(
            [
                {"url": "http://h/1", "events": ["a"], "secret_ref": ""},
                {"url": "http://h/2", "events": [], "secret_ref": ""},
            ],
            event="b",
            payload={},
            transport=lambda url, body, headers: calls.append(url) or 200,
        )
        assert [r.webhook_url for r in result] == ["http://h/2"]
        assert isinstance(result[0], Delivery)

    def test_dispatch_never_raises(self) -> None:
        def boom(url: str, body: str, headers: dict[str, str]) -> int:
            raise OSError("down")

        result = dispatch(
            [{"url": "http://h", "events": [], "secret_ref": ""}],
            event="x",
            payload={},
            transport=boom,
        )
        assert result[0].error is not None
