"""Auth profiles: environment-referenced credentials for test/replay runs.

Secret values are resolved from environment variables or file paths at
request time and are NEVER persisted in result bundles — only the
*reference* (env var name / file path) is stored.
"""
from __future__ import annotations

import base64
import os
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class AuthKind(str, Enum):
    bearer = "bearer"
    api_key = "api_key"
    basic = "basic"
    oauth_token = "oauth_token"
    mtls = "mtls"


class AuthProfile(BaseModel):
    """A credential *reference*, never a secret value."""

    name: str
    kind: AuthKind
    # bearer / oauth_token
    token_env: str | None = None
    # api_key
    key_env: str | None = None
    header_name: str = "X-Api-Key"
    # basic
    username_env: str | None = None
    password_env: str | None = None
    # mtls
    cert_file: str | None = None
    key_file: str | None = None

    def redacted_summary(self) -> dict[str, Any]:
        """Safe-to-persist view: references only, no secret values."""
        return {
            "name": self.name,
            "kind": self.kind.value,
            "token_env": self.token_env,
            "key_env": self.key_env,
            "header_name": self.header_name,
            "username_env": self.username_env,
            "password_env": "[REDACTED]" if self.password_env else None,
            "cert_file": self.cert_file,
            "key_file": "[REDACTED]" if self.key_file else None,
        }


def resolve_headers(profile: AuthProfile) -> dict[str, str]:
    """Resolve a profile into request headers (secrets stay in memory)."""
    def env(name: str | None) -> str:
        if not name:
            raise ValueError(f"profile '{profile.name}': missing environment reference")
        value = os.environ.get(name)
        if not value:
            raise ValueError(
                f"profile '{profile.name}': environment variable '{name}' is not set")
        return value

    if profile.kind in (AuthKind.bearer, AuthKind.oauth_token):
        return {"Authorization": f"Bearer {env(profile.token_env)}"}
    if profile.kind == AuthKind.api_key:
        return {profile.header_name: env(profile.key_env)}
    if profile.kind == AuthKind.basic:
        raw = f"{env(profile.username_env)}:{env(profile.password_env)}"
        encoded = base64.b64encode(raw.encode("utf-8")).decode("ascii")
        return {"Authorization": f"Basic {encoded}"}
    if profile.kind == AuthKind.mtls:
        # mTLS is applied at the transport layer, not via headers;
        # validate the referenced files exist so failures surface early.
        for path in (profile.cert_file, profile.key_file):
            if path and not Path(path).exists():
                raise ValueError(f"profile '{profile.name}': file not found: {path}")
        return {}
    raise ValueError(f"unsupported auth kind: {profile.kind}")


def resolve_verify(profile: AuthProfile) -> tuple[str, str] | bool:
    """Return httpx ``verify`` material for mTLS profiles."""
    if profile.kind != AuthKind.mtls:
        return True
    if not profile.cert_file or not profile.key_file:
        raise ValueError(f"profile '{profile.name}': cert_file and key_file are required")
    return (profile.cert_file, profile.key_file)


class AuthProfileSet(BaseModel):
    profiles: list[AuthProfile] = Field(default_factory=list)

    @classmethod
    def load(cls, path: str) -> "AuthProfileSet":
        import yaml

        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        return cls.model_validate(raw)

    def get(self, name: str) -> AuthProfile:
        for p in self.profiles:
            if p.name == name:
                return p
        raise KeyError(f"auth profile '{name}' not found")