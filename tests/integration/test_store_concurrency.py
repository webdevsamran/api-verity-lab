"""One SQLite connection, every request thread, and nothing serialising it.

`Store` opened its connection with `check_same_thread=False` and shared it
across every thread the WSGI server runs, with no lock. That is not a
theoretical hazard, and it did not stay theoretical for long: the first client
to make concurrent requests -- the dashboard, fetching eight collections at
once -- got intermittent `401`s for a valid token, because two threads
executing on one connection interleaved and the token lookup came back empty.

The 401 is the *visible* symptom, and it is the lucky one. The same race
returns one query's rows to another query's caller, which no log records and no
test notices: an org listing another org's contracts looks exactly like an org
that has those contracts.

These tests hammer the store from many threads at once. They cannot prove the
race is gone -- concurrency tests never can -- but the unserialised version
fails them reliably, which is the most a test of this shape can offer.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from apiverity.server.api import create_app
from apiverity.server.store import Store

pytestmark = pytest.mark.integration

THREADS = 12
ROUNDS = 25


@pytest.fixture()
def store() -> Store:
    return Store(":memory:")


def test_a_valid_token_is_never_refused_under_load(store: Store) -> None:
    """The symptom that surfaced it."""
    app = create_app(store)
    app.config["TESTING"] = True
    client = app.test_client()
    org = client.post("/v1/orgs", json={"name": "acme"}).get_json()
    auth = {"Authorization": f"Bearer {org['owner_token']}"}

    paths = [
        f"/v1/orgs/{org['org_id']}/users",
        "/v1/contracts",
        "/v1/environments",
        "/v1/policies",
        "/v1/approvals",
        "/v1/runs",
        "/v1/audit",
        "/v1/webhooks",
    ]

    statuses: list[int] = []
    lock = threading.Lock()

    def call(path: str) -> None:
        response = client.get(path, headers=auth)
        with lock:
            statuses.append(response.status_code)

    with ThreadPoolExecutor(max_workers=THREADS) as pool:
        for _ in range(ROUNDS):
            list(pool.map(call, paths))

    refused = [s for s in statuses if s in (401, 403)]
    assert refused == [], f"{len(refused)} of {len(statuses)} requests refused a valid token"


def test_concurrent_reads_return_their_own_rows(store: Store) -> None:
    """The invisible symptom: one query answered with another's result set.

    Two orgs, each with a distinguishable set of contracts, read at the same
    time. A read that comes back with the other org's rows is the failure the
    401 was only a hint of.
    """
    first = store.create_org("first")
    second = store.create_org("second")
    for index in range(5):
        store.publish_contract(first, f"first-{index}", "1.0.0", "openapi", {}, "tester")
    for index in range(3):
        store.publish_contract(second, f"second-{index}", "1.0.0", "openapi", {}, "tester")

    wrong: list[str] = []
    lock = threading.Lock()

    def read(org_id: int, prefix: str, expected: int) -> None:
        rows = store.list_contracts(org_id)
        titles = [r["title"] for r in rows]
        if len(rows) != expected or any(not t.startswith(prefix) for t in titles):
            with lock:
                wrong.append(f"org {org_id} saw {titles}")

    with ThreadPoolExecutor(max_workers=THREADS) as pool:
        futures = []
        for _ in range(ROUNDS):
            futures.append(pool.submit(read, first, "first-", 5))
            futures.append(pool.submit(read, second, "second-", 3))
        for future in futures:
            future.result()

    assert wrong == [], wrong[:5]


def test_concurrent_writes_all_land(store: Store) -> None:
    """An insert whose statement interleaved with another's is a lost write."""
    org = store.create_org("acme")

    def write(index: int) -> None:
        store.audit_append(org, "tester", "thing.happened", f"target-{index}")

    total = THREADS * ROUNDS
    with ThreadPoolExecutor(max_workers=THREADS) as pool:
        list(pool.map(write, range(total)))

    events = store.audit_list(org, limit=total + 10)
    assert len(events) == total


def test_the_hash_chain_survives_concurrent_appends(store: Store) -> None:
    """The audit log's whole value is that it can be verified afterwards.

    A chain built from interleaved reads of the previous hash is a chain that
    fails verification -- and a tamper-evident log that cries tamper on its own
    writes is worse than no log, because the next person switches the check off.
    """
    org = store.create_org("acme")

    def write(index: int) -> None:
        store.audit_append(org, "tester", "thing.happened", f"target-{index}")

    with ThreadPoolExecutor(max_workers=THREADS) as pool:
        list(pool.map(write, range(THREADS * ROUNDS)))

    assert store.audit_verify_chain(org) is True


def test_an_in_memory_store_is_still_one_database(store: Store) -> None:
    """The reason this is a lock rather than a thread-local connection.

    A `:memory:` database lives inside its connection, so a per-thread
    connection would hand each thread a different empty database -- which is
    worse than the bug it fixes, and is how the entire test suite is
    configured.
    """
    org = store.create_org("acme")
    seen: list[int] = []
    lock = threading.Lock()

    def read() -> None:
        with lock:
            seen.append(len(store.list_contracts(org)))

    store.publish_contract(org, "Catalog", "1.0.0", "openapi", {}, "tester")
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: read(), range(8)))

    assert set(seen) == {1}
