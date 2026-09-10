"""The kill-switch procedure, exercised rather than described.

Auditors of agent-era systems ask for three things by name: activity logs,
permission reviews, and a kill-switch procedure. A paragraph saying "revoke the
tokens" satisfies none of them -- it is an outage, it takes down the very runs
that tell you whether it is safe to restart, and it leaves no record of who
decided.

What is tested here is mostly the *shape of the authority*, because that is the
part a design gets wrong quietly:

- anyone can stop; only an admin can restart;
- a freeze without a reason is refused;
- denying an approval still works while frozen, because refusing a denial
  during an incident freezes the wrong direction;
- and nothing lifts on a timer.

Plus the honest half: a set of tests asserting what a freeze does **not** stop,
so the claim in the docs cannot quietly become larger than the code.
"""

from __future__ import annotations

import contextlib
import io
import json
from typing import Any

import pytest

from apiverity.cli.main import main
from apiverity.server import Store
from apiverity.server.api import create_app
from apiverity.server.decision import compute_can_i_deploy
from apiverity.server.freeze import FROZEN, LIFTED, FreezeState

pytestmark = pytest.mark.integration


@pytest.fixture()
def store() -> Store:
    return Store(":memory:")


@pytest.fixture()
def client(store: Store):
    app = create_app(store)
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _org(client) -> str:
    body = client.post("/v1/orgs", json={"name": "acme"}).get_json()
    return str(body["owner_token"])


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _member(client, owner: str, role: str) -> str:
    token = f"vlk-{role}-token"
    client.post(
        "/v1/orgs/1/users",
        headers=_auth(owner),
        json={"subject": f"a-{role}", "role": role, "token": token},
    )
    return token


def _run(argv: list[str]) -> tuple[int, dict[str, Any]]:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(io.StringIO()):
        code = main(argv)
    text = buffer.getvalue()
    return code, (json.loads(text) if text.strip().startswith("{") else {})


# --------------------------------------------------------------- the switch


def test_an_org_starts_unfrozen(store: Store) -> None:
    store.create_org("acme")
    assert store.freeze_state(1) == FreezeState(active=False)


def test_freezing_stops_can_i_deploy_whatever_the_verifications_say(store: Store) -> None:
    org = store.create_org("acme")
    store.freeze(org, "sam", "tool poisoning suspected")
    decision = compute_can_i_deploy(
        store, org, {"provider": "orders", "provider_version": "1.0.0", "environment": "prod"}
    )
    assert decision["deployable"] is False
    assert "frozen" in decision["reason"]
    assert decision["freeze"]["reason"] == "tool poisoning suspected"


def test_the_freeze_is_the_reason_not_a_lookup_failure(store: Store) -> None:
    """Checked before the contract lookup on purpose. During an incident,
    "has never been published" sends somebody to debug the wrong thing."""
    org = store.create_org("acme")
    store.freeze(org, "sam", "incident 4412")
    decision = compute_can_i_deploy(
        store, org, {"provider": "never-published", "provider_version": "9", "environment": "prod"}
    )
    assert "never been published" not in decision["reason"]


def test_lifting_restores_the_ordinary_answer(store: Store) -> None:
    org = store.create_org("acme")
    store.freeze(org, "sam", "incident 4412")
    store.lift_freeze(org, "admin", "contained")
    decision = compute_can_i_deploy(
        store, org, {"provider": "orders", "provider_version": "1.0.0", "environment": "prod"}
    )
    assert "frozen" not in decision["reason"]


def test_freezing_twice_is_not_an_error(store: Store) -> None:
    """Somebody reaching for this is mid-incident and may well hit it twice,
    or twice from two terminals. A 409 there reads as "it did not work"."""
    org = store.create_org("acme")
    first = store.freeze(org, "sam", "incident 4412")
    second = store.freeze(org, "kim", "incident 4412 again")
    assert second.active
    assert second.since == first.since
    assert second.actor == "sam"


def test_lifting_an_unfrozen_org_is_not_an_error(store: Store) -> None:
    org = store.create_org("acme")
    assert store.lift_freeze(org, "admin", "nothing to do").active is False


def test_one_org_freezing_does_not_freeze_another(store: Store) -> None:
    a = store.create_org("acme")
    b = store.create_org("beta")
    store.freeze(a, "sam", "incident")
    assert store.freeze_state(a).active
    assert not store.freeze_state(b).active


# ------------------------------------------------------------ the record


def test_both_transitions_land_in_the_audit_chain(store: Store) -> None:
    """The procedure is evidenced rather than asserted."""
    org = store.create_org("acme")
    store.freeze(org, "sam", "tool poisoning suspected")
    store.lift_freeze(org, "admin", "contained")
    actions = [e["action"] for e in store.audit_list(org)]
    assert FROZEN in actions
    assert LIFTED in actions
    assert store.audit_verify_chain(org)


def test_the_reason_is_in_the_audit_payload(store: Store) -> None:
    org = store.create_org("acme")
    store.freeze(org, "sam", "tool poisoning suspected")
    entry = next(e for e in store.audit_list(org) if e["action"] == FROZEN)
    assert "tool poisoning suspected" in entry["payload_json"]


def test_the_history_survives_the_lift(store: Store) -> None:
    """A boolean column on `orgs` would have thrown this away, and an incident
    review needs what was stopped, by whom, why, and when it was released."""
    org = store.create_org("acme")
    store.freeze(org, "sam", "first")
    store.lift_freeze(org, "admin", "contained")
    store.freeze(org, "kim", "second")
    history = store.freeze_history(org)
    assert [h["reason"] for h in history] == ["second", "first"]
    assert history[1]["lifted_by"] == "admin"
    assert history[1]["lift_reason"] == "contained"


# ------------------------------------------------------- the authority shape


def test_any_member_can_stop_but_only_an_admin_can_restart(client) -> None:
    """An emergency in which only an administrator can pull the switch, and
    the administrator is asleep, is the emergency."""
    owner = _org(client)
    member = _member(client, owner, "member")

    assert (
        client.post("/v1/freeze", headers=_auth(member), json={"reason": "incident"}).status_code
        == 201
    )
    assert client.delete(
        "/v1/freeze", headers=_auth(member), json={"reason": "oops"}
    ).status_code in (
        401,
        403,
    )
    assert client.get("/v1/freeze", headers=_auth(member)).get_json()["frozen"] is True
    assert (
        client.delete("/v1/freeze", headers=_auth(owner), json={"reason": "ok"}).status_code == 200
    )


def test_a_freeze_without_a_reason_is_refused(client) -> None:
    """An unexplained freeze is an outage whose cause nobody can find, at the
    moment everybody is looking for it."""
    token = _org(client)
    response = client.post("/v1/freeze", headers=_auth(token), json={})
    assert response.status_code == 400
    assert "reason" in response.get_json()["error"]


def test_an_anonymous_caller_cannot_touch_the_switch(client) -> None:
    _org(client)
    assert client.post("/v1/freeze", json={"reason": "x"}).status_code in (401, 403)
    assert client.delete("/v1/freeze").status_code in (401, 403)


# ------------------------------------------------------- what it does NOT stop


def test_an_approval_can_still_be_denied_while_frozen(client, store: Store) -> None:
    """Refusing a denial during an incident freezes the wrong direction."""
    token = _org(client)
    approval = client.post(
        "/v1/approvals",
        headers=_auth(token),
        json={
            "contract_title": "orders",
            "from_version": "1.0.0",
            "to_version": "2.0.0",
            "justification": "the field is unused",
        },
    ).get_json()
    client.post("/v1/freeze", headers=_auth(token), json={"reason": "incident"})

    granted = client.post(
        f"/v1/approvals/{approval['approval_id']}/decision",
        headers=_auth(token),
        json={"decision": "approved"},
    )
    assert granted.status_code == 409
    assert "frozen" in granted.get_json()["error"]

    denied = client.post(
        f"/v1/approvals/{approval['approval_id']}/decision",
        headers=_auth(token),
        json={"decision": "rejected"},
    )
    assert denied.status_code == 200


def test_reading_and_publishing_still_work_while_frozen(client) -> None:
    """Taking those down with the releases would leave an operator frozen and
    blind."""
    token = _org(client)
    client.post("/v1/freeze", headers=_auth(token), json={"reason": "incident"})
    assert client.get("/v1/contracts", headers=_auth(token)).status_code == 200
    published = client.post(
        "/v1/contracts",
        headers=_auth(token),
        json={"title": "orders", "version": "1.0.0", "protocol": "openapi", "spec": {}},
    )
    assert published.status_code in (200, 201)


def test_the_state_carries_what_it_does_and_does_not_block(client) -> None:
    """A caller reading `deployable: false` is mid-incident and is not going to
    go and find the documentation page."""
    token = _org(client)
    state = client.post("/v1/freeze", headers=_auth(token), json={"reason": "incident"}).get_json()
    assert any("can-i-deploy" in line for line in state["blocks"])
    assert any("job queue" in line for line in state["does_not_block"])
    assert any("credentials" in line for line in state["does_not_block"])


# ------------------------------------------------------------------ review_by


def test_a_past_review_date_reports_overdue_without_lifting(store: Store) -> None:
    """A kill switch that releases itself fires exactly when nobody is
    watching, so `review_by` is advisory and nothing acts on it."""
    org = store.create_org("acme")
    store.freeze(org, "sam", "incident", review_by="2000-01-01T00:00:00+00:00")
    state = store.freeze_state(org)
    assert state.active is True
    assert state.overdue is True


def test_a_future_review_date_is_not_overdue(store: Store) -> None:
    org = store.create_org("acme")
    store.freeze(org, "sam", "incident", review_by="2999-01-01T00:00:00+00:00")
    assert store.freeze_state(org).overdue is False


# -------------------------------------------------------------------- the CLI


def test_the_cli_needs_a_server(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APIVERITY_SERVER", raising=False)
    code, _payload = _run(["--no-config", "freeze", "status", "--json"])
    assert code == 2


def test_the_cli_needs_a_reason_to_freeze(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIVERITY_SERVER", "http://127.0.0.1:9")
    code, _payload = _run(["--no-config", "freeze", "on", "--json"])
    assert code == 2


def test_an_unreachable_server_is_exit_3_so_a_gate_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A kill switch a network partition disables is not a kill switch."""
    monkeypatch.setenv("APIVERITY_SERVER", "http://127.0.0.1:9")
    code, _payload = _run(["--no-config", "freeze", "status", "--json"])
    assert code == 3
