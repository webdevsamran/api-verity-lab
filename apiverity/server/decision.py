"""Deploy-decision and auth fallback helpers for the self-hosted API.

Extracted from ``api.py`` so can-i-deploy reasoning and authentication error
handling can be exercised without standing up a Flask app.
"""

from __future__ import annotations

import json
from typing import Any

from apiverity.server.auth import Identity, IdentityProvider
from apiverity.server.store import Store


def authenticate_safe(providers: list[IdentityProvider], token: str) -> Identity | None:
    from apiverity.server.auth import authenticate

    if not token:
        return None
    try:
        return authenticate(providers, token)
    except Exception:
        return None


def compute_can_i_deploy(store: Store, org_id: int, body: dict[str, Any]) -> dict[str, Any]:
    """Pact-broker-style decision from verifications recorded in runs.

    Body: provider, provider_version, consumer, consumer_version(optional),
    environment. A provider version is deployable to an environment when a
    successful verification run exists for the latest consumer contract
    published against it targeting that environment.
    """
    provider = body["provider"]
    version = body["provider_version"]
    environment = body.get("environment", "")
    contracts = store.list_contracts(org_id, title=provider)
    target = next((c for c in contracts if c["version"] == version), None)
    if target is None:
        return {"deployable": False, "reason": f"{provider}@{version} has never been published"}

    verifications = []
    for run in _all_runs(store, org_id):
        if (
            run.get("verification_for") == f"{provider}@{version}"
            and run.get("environment") == environment
            and run.get("status") == "passed"
        ):
            verifications.append(run)
    if not verifications:
        return {
            "deployable": False,
            "reason": f"no passed verification of {provider}@{version} against {environment!r}",
        }
    return {
        "deployable": True,
        "reason": f"{len(verifications)} passed verification(s) recorded",
        "verified_by": sorted({v["requested_by"] for v in verifications}),
    }


def _all_runs(store: Store, org_id: int) -> list[dict[str, Any]]:
    rows = store.conn.execute("SELECT * FROM runs WHERE org_id = ?", (org_id,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["result"] = json.loads(d["result_json"]) if d.pop("result_json") else None
        out.append(d)
    return out
