"""Building the server from its environment, in code rather than in a shell string.

`docker/entrypoint.sh` started the server from an inline `python -c` block. It
worked, and it was the only place that knew how to assemble the application --
so every new setting grew the string, none of it was tested, and a typo inside
it failed at container start with a traceback about a heredoc.

This is that logic as a module. The entrypoint calls it; so can anybody running
the server without Docker.

## Partial configuration fails loudly

The setting that matters most here is identity. A server configured with an
issuer and no audience, or an issuer and no role map, must **not** start with
local-token authentication and a warning nobody reads: a server that was meant
to use the company's identity provider and quietly did not is the worst
available outcome, and it looks exactly like a working one.

So any `VERITY_OIDC_*` variable being set commits the server to a complete OIDC
configuration, and an incomplete one is a startup failure naming what is
missing.
"""

from __future__ import annotations

import json
import os
from typing import Any

#: Every variable this reads. Published so `tests/unit/test_helm_chart.py` can
#: hold the chart against it, and so a reader has one list rather than a grep.
ENVIRONMENT = {
    "VERITY_DB": "SQLite path (default /data/verity.db)",
    "VERITY_PORT": "listen port (default 8090)",
    "VERITY_CORS_ORIGINS": "comma-separated browser origins; empty means none",
    "VERITY_OIDC_ISSUER": "the identity provider's issuer URL",
    "VERITY_OIDC_AUDIENCE": "the audience this server accepts",
    "VERITY_OIDC_ROLE_CLAIM": "the claim carrying roles or groups (default `roles`)",
    "VERITY_OIDC_ROLE_MAP": "`group=role,group=role`, or JSON",
    "VERITY_OIDC_ORG_ID": "the org every verified subject belongs to",
    "VERITY_OIDC_ORG_CLAIM": "the claim carrying the org, for a multi-org server",
    "VERITY_OIDC_JWKS_URI": "the key set URL, when discovery should be skipped",
    "VERITY_OIDC_LEEWAY": "seconds of clock skew tolerated on exp/nbf (default 0)",
    "VERITY_LOCAL_TOKENS": "`0` to disable local token auth once OIDC is in place",
}


class LaunchError(Exception):
    """A configuration the server will not start under."""


def _role_map(raw: str) -> dict[str, str]:
    """`admins=admin,devs=member`, or the same thing as JSON."""
    raw = raw.strip()
    if not raw:
        return {}
    if raw.startswith("{"):
        try:
            parsed = json.loads(raw)
        except ValueError as exc:
            raise LaunchError(f"VERITY_OIDC_ROLE_MAP is not valid JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise LaunchError("VERITY_OIDC_ROLE_MAP as JSON must be an object")
        return {str(k): str(v) for k, v in parsed.items()}

    out: dict[str, str] = {}
    for pair in raw.split(","):
        if not pair.strip():
            continue
        group, sep, role = pair.partition("=")
        if not sep:
            raise LaunchError(
                f"VERITY_OIDC_ROLE_MAP entry '{pair.strip()}' is not `group=role`. "
                "Use `platform-admins=admin,developers=member`, or JSON"
            )
        out[group.strip()] = role.strip()
    return out


def oidc_provider(env: dict[str, str] | None = None) -> Any | None:
    """An `OidcProvider` from the environment, or None when none is configured.

    Any `VERITY_OIDC_*` variable commits the server to a complete configuration.
    Starting with a half-configured issuer and falling back to local tokens is
    the failure this refuses: it looks identical to success.
    """
    source: dict[str, str] = dict(os.environ) if env is None else env
    present = {k: v for k, v in source.items() if k.startswith("VERITY_OIDC_") and v.strip()}
    if not present:
        return None

    issuer = present.get("VERITY_OIDC_ISSUER", "")
    if not issuer:
        raise LaunchError(
            f"{sorted(present)} are set without VERITY_OIDC_ISSUER. Configure the "
            "identity provider completely or not at all -- a server that half-configures "
            "one and falls back to local tokens looks exactly like a working one"
        )

    from apiverity.server.oidc import OidcConfig, OidcProvider

    org_raw = present.get("VERITY_OIDC_ORG_ID", "")
    try:
        org_id = int(org_raw) if org_raw else None
    except ValueError as exc:
        raise LaunchError(f"VERITY_OIDC_ORG_ID is not a number: {org_raw!r}") from exc

    try:
        leeway = int(present.get("VERITY_OIDC_LEEWAY", "0") or 0)
    except ValueError as exc:
        raise LaunchError("VERITY_OIDC_LEEWAY is not a number") from exc

    # `OidcConfig` raises on the rest -- a missing audience, an empty role map,
    # a role that does not exist. Those messages say why each matters, and
    # repeating the checks here would mean two places that could disagree.
    from apiverity.server.oidc import OidcError

    try:
        config = OidcConfig(
            issuer=issuer,
            audience=present.get("VERITY_OIDC_AUDIENCE", ""),
            role_claim=present.get("VERITY_OIDC_ROLE_CLAIM", "roles"),
            role_map=_role_map(present.get("VERITY_OIDC_ROLE_MAP", "")),
            org_id=org_id,
            org_claim=present.get("VERITY_OIDC_ORG_CLAIM") or None,
            leeway=leeway,
            jwks_uri=present.get("VERITY_OIDC_JWKS_URI") or None,
        )
    except OidcError as exc:
        raise LaunchError(str(exc)) from exc
    return OidcProvider(config)


def build_app(env: dict[str, str] | None = None, store: Any = None) -> Any:
    """The Flask application, configured from the environment."""
    from apiverity.server.api import create_app
    from apiverity.server.auth import LocalTokenProvider
    from apiverity.server.store import Store

    source: dict[str, str] = dict(os.environ) if env is None else env
    store = store or Store(source.get("VERITY_DB", "/data/verity.db"))

    # Origins default to none. A server that answers every origin by default is
    # a server whose operator never chose to.
    origins = [o.strip() for o in source.get("VERITY_CORS_ORIGINS", "").split(",") if o.strip()]

    providers: list[Any] = []
    external = oidc_provider(source)
    if external is not None:
        providers.append(external)
    if source.get("VERITY_LOCAL_TOKENS", "1").strip() not in ("0", "false", "no"):
        # Last, so an OIDC token is never matched against the local table
        # first, and kept by default so configuring OIDC does not lock out the
        # bootstrap token in the same breath.
        providers.append(LocalTokenProvider(store))
    if not providers:
        raise LaunchError(
            "no identity provider is configured: VERITY_LOCAL_TOKENS is off and no "
            "VERITY_OIDC_* variables are set. The server would authenticate nobody"
        )

    return create_app(store, cors_origins=origins or None, providers=providers)


def main() -> int:
    """Start the server. This is what the container entrypoint calls."""
    import sys

    try:
        app = build_app()
    except LaunchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    app.run(host="0.0.0.0", port=int(os.environ.get("VERITY_PORT", "8090")))
    return 0


__all__ = ["ENVIRONMENT", "LaunchError", "build_app", "main", "oidc_provider"]


if __name__ == "__main__":  # pragma: no cover - the container entrypoint
    raise SystemExit(main())
