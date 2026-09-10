"""The server the dashboard could not read.

Twenty-nine routes, and none of them reachable from a browser: no CORS headers
at all, so a dashboard on another origin got a console error and a blank page
rather than a server that said no. And three collections the server holds could
not be listed -- runs and approvals had no list route, and `Store.list_policies`
was written and called by nothing, so a policy could be fetched by name, which
only helps someone who already knows the name.

An approval queue nobody can list is an approval queue nobody works.

The CORS tests carry the weight here. Every route on this server is
authenticated, so getting the allowlist wrong is not a broken feature, it is an
open door -- and the two easy mistakes (a wildcard, and a missing `Vary`) both
produce a working dashboard.
"""

from __future__ import annotations

import pytest

from apiverity.server.api import create_app
from apiverity.server.store import Store

pytestmark = pytest.mark.integration

DASHBOARD = "http://localhost:5178"


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def store() -> Store:
    return Store(":memory:")


def _client(store: Store, **kwargs):
    app = create_app(store, **kwargs)
    app.config["TESTING"] = True
    return app.test_client()


def _org(client) -> tuple[int, str]:
    body = client.post("/v1/orgs", json={"name": "acme"}).get_json()
    return int(body["org_id"]), str(body["owner_token"])


# ------------------------------------------------------------- the listings


def test_runs_can_be_listed(store: Store) -> None:
    client = _client(store)
    _, token = _org(client)
    client.post(
        "/v1/runs",
        headers=_auth(token),
        json={"kind": "breaking", "status": "passed"},
    )
    response = client.get("/v1/runs", headers=_auth(token))
    assert response.status_code == 200
    runs = response.get_json()["runs"]
    assert len(runs) == 1
    assert runs[0]["kind"] == "breaking"


def test_a_run_listing_does_not_carry_every_result_payload(store: Store) -> None:
    """A hundred runs would otherwise mean a hundred full result documents.

    Megabytes of findings for a table that shows a status column. `get_run`
    returns the whole thing for the one run somebody opened.
    """
    client = _client(store)
    _, token = _org(client)
    client.post(
        "/v1/runs",
        headers=_auth(token),
        json={"kind": "breaking", "status": "passed", "result": {"findings": ["x"] * 50}},
    )
    listed = client.get("/v1/runs", headers=_auth(token)).get_json()["runs"][0]
    assert "result" not in listed
    assert "result_json" not in listed

    detail = client.get(f"/v1/runs/{listed['id']}", headers=_auth(token)).get_json()
    assert detail["result"]["findings"]


def test_approvals_can_be_listed_and_filtered(store: Store) -> None:
    client = _client(store)
    _, token = _org(client)
    for version in ("2.0.0", "3.0.0"):
        client.post(
            "/v1/approvals",
            headers=_auth(token),
            json={
                "contract_title": "Catalog",
                "from_version": "1.0.0",
                "to_version": version,
                "justification": "agreed with both consumers",
            },
        )
    listed = client.get("/v1/approvals", headers=_auth(token)).get_json()["approvals"]
    assert len(listed) == 2

    approval = listed[0]
    client.post(
        f"/v1/approvals/{approval['id']}/decision",
        headers=_auth(token),
        json={"decision": "approved"},
    )
    pending = client.get("/v1/approvals?status=pending", headers=_auth(token)).get_json()
    assert len(pending["approvals"]) == 1


def test_policies_can_be_listed(store: Store) -> None:
    """`Store.list_policies` existed and nothing called it."""
    client = _client(store)
    _, token = _org(client)
    client.put(
        "/v1/policies/naming",
        headers=_auth(token),
        json={"content": "rules: []"},
    )
    listed = client.get("/v1/policies", headers=_auth(token)).get_json()["policies"]
    assert [p["name"] for p in listed] == ["naming"]


def test_a_listing_still_needs_a_token(store: Store) -> None:
    client = _client(store)
    _org(client)
    for path in ("/v1/runs", "/v1/approvals", "/v1/policies"):
        assert client.get(path).status_code in (401, 403), path


def test_a_listing_is_scoped_to_the_callers_org(store: Store) -> None:
    """Two orgs in one database must not see each other's queue."""
    client = _client(store)
    _, first = _org(client)
    second_body = client.post("/v1/orgs", json={"name": "other"}).get_json()
    second = str(second_body["owner_token"])

    client.post("/v1/runs", headers=_auth(first), json={"kind": "breaking", "status": "passed"})
    assert len(client.get("/v1/runs", headers=_auth(first)).get_json()["runs"]) == 1
    assert client.get("/v1/runs", headers=_auth(second)).get_json()["runs"] == []


# ------------------------------------------------------------------- CORS


def test_no_cors_headers_without_an_allowlist(store: Store) -> None:
    """The default. A server that answers every origin by default is a server
    whose operator never chose to."""
    client = _client(store)
    _, token = _org(client)
    response = client.get("/v1/contracts", headers={**_auth(token), "Origin": DASHBOARD})
    assert "Access-Control-Allow-Origin" not in response.headers


def test_an_allowed_origin_is_answered(store: Store) -> None:
    client = _client(store, cors_origins=[DASHBOARD])
    _, token = _org(client)
    response = client.get("/v1/contracts", headers={**_auth(token), "Origin": DASHBOARD})
    assert response.headers["Access-Control-Allow-Origin"] == DASHBOARD
    assert response.headers["Access-Control-Allow-Credentials"] == "true"
    assert "authorization" in response.headers["Access-Control-Allow-Headers"]


def test_an_origin_that_was_not_named_gets_nothing(store: Store) -> None:
    client = _client(store, cors_origins=[DASHBOARD])
    _, token = _org(client)
    response = client.get("/v1/contracts", headers={**_auth(token), "Origin": "https://evil.test"})
    assert "Access-Control-Allow-Origin" not in response.headers


def test_the_response_varies_on_origin(store: Store) -> None:
    """Without it, a cache that saw one allowed origin's response would serve
    it to every other origin -- an allowlist turned into a wildcard, one
    deployment at a time."""
    client = _client(store, cors_origins=[DASHBOARD])
    _, token = _org(client)
    response = client.get("/v1/contracts", headers={**_auth(token), "Origin": DASHBOARD})
    assert "Origin" in response.headers.get("Vary", "")


def test_a_wildcard_origin_is_refused_outright(store: Store) -> None:
    """`Access-Control-Allow-Origin: *` cannot carry credentials, and every
    route here is authenticated. It is also the exact configuration this
    project's own `SEC-CORS-WILDCARD` rule objects to in other people's
    contracts."""
    with pytest.raises(ValueError) as caught:
        create_app(store, cors_origins=["*"])
    assert "*" in str(caught.value)


def test_a_trailing_slash_does_not_defeat_the_allowlist(store: Store) -> None:
    """A browser sends an origin without one; an operator writes one anyway."""
    client = _client(store, cors_origins=[f"{DASHBOARD}/"])
    _, token = _org(client)
    response = client.get("/v1/contracts", headers={**_auth(token), "Origin": DASHBOARD})
    assert response.headers["Access-Control-Allow-Origin"] == DASHBOARD


def test_cors_headers_are_present_on_a_refusal_too(store: Store) -> None:
    """Otherwise the browser hides the 401 behind a CORS error, and the reader
    is told the server is unreachable when it is only saying no."""
    client = _client(store, cors_origins=[DASHBOARD])
    _org(client)
    response = client.get("/v1/contracts", headers={"Origin": DASHBOARD})
    assert response.status_code in (401, 403)
    assert response.headers["Access-Control-Allow-Origin"] == DASHBOARD
