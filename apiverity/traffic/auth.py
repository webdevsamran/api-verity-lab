"""Credentials by reference, resolved at request time and never written down.

A profile names *where* a credential lives -- an environment variable, or a
file on disk -- and never holds one. `resolve_headers` reads the environment at
the moment a request is built, so a result bundle records `token_env:
STAGING_TOKEN` and nothing that could be replayed by whoever finds the bundle.

Every command that takes `--base-url` takes `--auth-profiles FILE
--auth-profile NAME`. Until it did, this module was reachable from nothing, and
the two things below had gone unnoticed for exactly that reason.

## `resolve_verify` named the wrong httpx parameter

It returned `(cert_file, key_file)` and its docstring called that "httpx
`verify` material". `verify` is the *server* certificate setting -- typed
`ssl.SSLContext | str | bool` -- and a *client* certificate goes in `cert`.

httpx does not reject the tuple at construction; it stores it, so
`Client(verify=(cert, key))._transport._pool._ssl_context` is a `tuple`. The
client certificate is never presented, and the connection fails later somewhere
that says nothing about mTLS. The function is `resolve_client_cert` now and
returns what `cert=` takes.

## The redaction redacted references and printed references

`redacted_summary` is documented as "references only, no secret values", and it
blanked `password_env` and `key_file` while printing `token_env`, `key_env`,
`username_env` and `cert_file`. Those are all the same kind of thing: the name
of an environment variable, or a path. Redacting the name of the variable
holding a password while printing the name of the one holding a bearer token
protects nothing and costs the reader the one fact the summary exists to give
them -- which variable to set.

Nothing here is a secret, so nothing here is redacted, and
`assert_no_secret_values` is the check that keeps that true: it fails if any
field's value equals the *contents* of the environment variable it names.
"""

from __future__ import annotations

import base64
import os
import re
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

#: A POSIX environment variable name. A profile field holds one of these, and
#: a value that is not one is a credential somebody pasted where a reference
#: goes -- an easy mistake, because the field is a string and a token is a
#: string.
_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class AuthKind(StrEnum):
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
    #: What the operator says this identity is allowed to do, for
    #: `test --authz`. `None` means unstated, which is not the same as holding
    #: none -- and only the second is a basis for a finding.
    scopes: list[str] | None = None

    def redacted_summary(self) -> dict[str, Any]:
        """Safe-to-persist view: every field, because every field is a reference.

        The name is kept for continuity -- artifacts carry a `redacted_summary`
        key -- and there is nothing left in here to redact. See the module
        docstring for what this used to blank and why that was worse than
        printing it.
        """
        return {
            "name": self.name,
            "kind": self.kind.value,
            "token_env": self.token_env,
            "key_env": self.key_env,
            "header_name": self.header_name,
            "username_env": self.username_env,
            "password_env": self.password_env,
            "cert_file": self.cert_file,
            "key_file": self.key_file,
            "scopes": self.scopes,
        }

    def assert_no_secret_values(self) -> None:
        """Fail if a field holds a credential instead of naming where one is.

        `token_env: "eyJhbGciOi..."` is the mistake this format exists to make
        impossible, and it is an easy one: the field is a string and a token is
        a string. Called when a profile set is loaded, so the file is rejected
        before a run puts it in an artifact.
        """
        for field in ("token_env", "key_env", "username_env", "password_env"):
            name = getattr(self, field)
            if not name:
                continue
            if not _ENV_NAME.fullmatch(name):
                raise ValueError(
                    f"profile '{self.name}': `{field}` should name an environment "
                    f"variable and {name[:16]!r}... is not one. This format stores "
                    "references, so a result bundle never carries a credential -- "
                    "write the variable's name here and export the value."
                )


def resolve_headers(profile: AuthProfile) -> dict[str, str]:
    """Resolve a profile into request headers (secrets stay in memory)."""

    def env(name: str | None) -> str:
        if not name:
            raise ValueError(f"profile '{profile.name}': missing environment reference")
        value = os.environ.get(name)
        if not value:
            raise ValueError(f"profile '{profile.name}': environment variable '{name}' is not set")
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


def resolve_client_cert(profile: AuthProfile) -> tuple[str, str] | None:
    """The client certificate pair for httpx's ``cert=``, or None.

    Not ``verify=``, which is the *server* certificate setting. See the module
    docstring: httpx stores a tuple passed there without complaint and never
    presents the certificate.
    """
    if profile.kind != AuthKind.mtls:
        return None
    if not profile.cert_file or not profile.key_file:
        raise ValueError(f"profile '{profile.name}': cert_file and key_file are required")
    return (profile.cert_file, profile.key_file)


class AuthProfileSet(BaseModel):
    profiles: list[AuthProfile] = Field(default_factory=list)

    @classmethod
    def load(cls, path: str) -> AuthProfileSet:
        import yaml

        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        loaded = cls.model_validate(raw)
        for profile in loaded.profiles:
            profile.assert_no_secret_values()
        names = [p.name for p in loaded.profiles]
        duplicate = sorted({n for n in names if names.count(n) > 1})
        if duplicate:
            raise ValueError(f"{path}: two profiles are called {duplicate}")
        return loaded

    def get(self, name: str) -> AuthProfile:
        for p in self.profiles:
            if p.name == name:
                return p
        known = ", ".join(sorted(p.name for p in self.profiles)) or "none"
        raise KeyError(f"auth profile '{name}' not found (this file declares: {known})")


def material(profile: AuthProfile) -> tuple[dict[str, str], tuple[str, str] | None]:
    """Headers and client certificate, resolved together.

    One call because a caller needs both and getting one without the other is
    how an mTLS profile ends up sending an unauthenticated request.
    """
    return resolve_headers(profile), resolve_client_cert(profile)
