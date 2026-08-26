"""Authentication and RBAC for the self-hosted server.

- Local token auth (hashed at rest) for development/self-hosted use.
- OIDC/SAML abstraction: implement :class:`IdentityProvider` and register it;
  the server verifies bearer tokens through the provider when configured.
- Role permission matrix: owner > admin > member > viewer.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol


class Role(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


_ROLE_RANK = {Role.OWNER: 4, Role.ADMIN: 3, Role.MEMBER: 2, Role.VIEWER: 1}

#: Actions each role may perform; a caller needs rank >= the required rank.
ACTION_MIN_ROLE: dict[str, Role] = {
    "read": Role.VIEWER,
    "publish_contract": Role.MEMBER,
    "record_run": Role.MEMBER,
    "register_environment": Role.ADMIN,
    "set_policy": Role.ADMIN,
    "request_approval": Role.MEMBER,
    "decide_approval": Role.ADMIN,
    "manage_users": Role.ADMIN,
    "create_org": Role.OWNER,
    "register_webhook": Role.ADMIN,
    "view_audit": Role.ADMIN,
}


@dataclass(frozen=True)
class Identity:
    subject: str
    org_id: int
    role: Role


def authorize(identity: Identity, action: str) -> bool:
    required = ACTION_MIN_ROLE.get(action)
    if required is None:
        return False
    return _ROLE_RANK[identity.role] >= _ROLE_RANK[required]


class IdentityProvider(Protocol):
    """External identity verification hook (OIDC/SAML adapters implement this)."""

    def verify(self, token: str) -> tuple[str, dict[str, Any]] | None:
        """Return (subject, claims) if the token is valid, else None."""
        ...


class LocalTokenProvider:
    """Dev/self-hosted provider backed by hashed tokens in the store."""

    def __init__(self, store: Any) -> None:
        self.store = store

    def verify(self, token: str) -> tuple[str, dict[str, Any]] | None:
        user = self.store.resolve_token(token)
        if not user:
            return None
        return user["subject"], {"org_id": user["org_id"], "role": user["role"]}


def authenticate(
    providers: list[IdentityProvider], token: str, org_id: int | None = None
) -> Identity | None:
    """Try each provider in order; build an Identity from verified claims."""
    for provider in providers:
        result = provider.verify(token)
        if result is None:
            continue
        subject, claims = result
        resolved_org = claims.get("org_id", org_id)
        if resolved_org is None:
            return None
        return Identity(
            subject=subject,
            org_id=int(resolved_org),
            role=Role(str(claims.get("role", "viewer"))),
        )
    return None
