"""A real OIDC provider: JWTs verified against the issuer's own keys.

`IdentityProvider` has been a `Protocol` with one implementation --
`LocalTokenProvider`, which looks a token up in the server's own table. The
docstring said "OIDC/SAML adapters implement this" and none did, so a team with
an identity provider had an abstraction and no way to use it.

## What verification means here, and what it refuses to skip

Four things, and skipping any one of them turns this into a base64 decoder:

1. **The signature**, against a key fetched from the issuer's JWKS endpoint and
   selected by the token's `kid`. A token whose `kid` is not in the key set is
   rejected rather than tried against every key -- trying them all is how a
   rotated-out key stays valid.
2. **`iss`**, against the issuer configured here. A correctly signed token from
   a different issuer is a correctly signed token from somebody else.
3. **`aud`**, against the audience configured here. An access token minted for
   another service is not an access token for this one, and accepting it is the
   confused-deputy problem in its original form.
4. **`exp`**, with no grace period by default. A token that expired is a token
   that expired.

`alg: none` is rejected before anything else, along with any algorithm not in
the configured allow-list. That check exists because the JWT specification
permits an unsigned token and a library that honours it will happily verify
one.

## Claims to roles, by configuration rather than convention

An identity provider does not know what `admin` means here. The mapping from a
claim to a :class:`Role` is configured, the claim it reads is configured, and a
subject whose claim matches nothing gets **no identity at all** rather than a
default role. A default of `viewer` sounds harmless and means anybody the
issuer will mint a token for can read every contract in the org.

## What this is not

A SAML implementation. SAML is XML signature verification, and doing that
safely is a larger and much sharper problem than this module; a half-done one
would be worse than none. `IdentityProvider` is still the seam, and this module
is the worked example of implementing it.
"""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass, field
from typing import Any

#: Algorithms accepted by default. Asymmetric only: with an HMAC algorithm the
#: verification key is the signing key, so anybody who can read the server's
#: configuration can mint tokens.
DEFAULT_ALGORITHMS = ("RS256", "RS384", "RS512", "ES256", "ES384", "PS256")

#: How long a fetched key set is reused. Long enough not to fetch per request,
#: short enough that a rotated key is picked up without a restart.
JWKS_TTL_SECONDS = 300


class OidcError(Exception):
    """A configuration this will not run under."""


def _b64(segment: str) -> bytes:
    padding = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + padding)


def decode_segment(segment: str) -> dict[str, Any]:
    value = json.loads(_b64(segment))
    if not isinstance(value, dict):
        raise ValueError("segment is not a JSON object")
    return value


@dataclass
class OidcConfig:
    """Everything this provider needs, and nothing it can guess."""

    issuer: str
    audience: str
    #: The claim carrying the caller's role or group. `roles`, `groups`,
    #: `https://example.com/roles` -- issuers disagree and none of them is
    #: wrong.
    role_claim: str = "roles"
    #: Claim value -> role here. An identity provider does not know what
    #: `admin` means in this application.
    role_map: dict[str, str] = field(default_factory=dict)
    #: The org every verified subject belongs to. A server serving one
    #: organisation names it; one serving several reads it from a claim.
    org_id: int | None = None
    org_claim: str | None = None
    algorithms: tuple[str, ...] = DEFAULT_ALGORITHMS
    #: Seconds of clock skew tolerated on `exp` and `nbf`. Zero by default:
    #: a token that expired is a token that expired, and a grace period is a
    #: decision somebody should make deliberately.
    leeway: int = 0
    jwks_uri: str | None = None

    def __post_init__(self) -> None:
        if not self.issuer:
            raise OidcError("an OIDC provider needs an issuer")
        if not self.audience:
            raise OidcError(
                "an OIDC provider needs an audience. Without it a token minted for "
                "another service verifies here, which is the confused-deputy problem"
            )
        if not self.role_map:
            raise OidcError(
                "an OIDC provider needs a role_map. Defaulting an unmapped subject to "
                "`viewer` would let anybody the issuer mints a token for read every "
                "contract in the org"
            )
        unknown = set(self.role_map.values()) - {"owner", "admin", "member", "viewer"}
        if unknown:
            raise OidcError(f"role_map names roles that do not exist: {sorted(unknown)}")
        if "none" in {a.lower() for a in self.algorithms}:
            raise OidcError("`alg: none` is not an algorithm; it is the absence of one")
        if self.org_id is None and not self.org_claim:
            raise OidcError("set either org_id (one organisation) or org_claim (several)")


@dataclass
class _Keys:
    keys: dict[str, Any]
    fetched_at: float


class OidcProvider:
    """Verifies an OIDC access token and maps its claims to an `Identity`.

    Implements the `IdentityProvider` protocol, so it is registered the same
    way `LocalTokenProvider` is and the two can run side by side -- which is
    what a migration from local tokens to an issuer looks like.
    """

    def __init__(self, config: OidcConfig, *, fetch: Any = None, now: Any = None) -> None:
        self.config = config
        self._fetch = fetch or self._default_fetch
        self._now = now or time.time
        self._keys: _Keys | None = None

    # -- key material ----------------------------------------------------

    @staticmethod
    def _default_fetch(url: str) -> dict[str, Any]:
        import httpx

        response = httpx.get(url, timeout=10.0)
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict):
            raise OidcError(f"{url} did not return a JSON object")
        return body

    def _discovery_url(self) -> str:
        return self.config.issuer.rstrip("/") + "/.well-known/openid-configuration"

    def jwks(self, *, force: bool = False) -> dict[str, Any]:
        """The issuer's key set, cached briefly.

        Cached because a fetch per request makes the identity provider a
        dependency of every call; briefly, because a key rotated at the issuer
        has to stop working here without a restart.
        """
        now = self._now()
        if not force and self._keys and now - self._keys.fetched_at < JWKS_TTL_SECONDS:
            return self._keys.keys

        uri = self.config.jwks_uri
        if not uri:
            document = self._fetch(self._discovery_url())
            uri = str(document.get("jwks_uri") or "")
            if not uri:
                raise OidcError(f"{self._discovery_url()} declares no jwks_uri")
            # Checked, not assumed: a discovery document that points the key
            # set at another host is either a misconfiguration or somebody
            # else's idea, and following it silently is how a token gets
            # verified against a key nobody here chose.
            if not uri.startswith(self.config.issuer.rstrip("/")):
                raise OidcError(
                    f"the discovery document points jwks_uri at '{uri}', which is not "
                    f"under the configured issuer '{self.config.issuer}'. Set jwks_uri "
                    "explicitly if that is deliberate"
                )
        keys = {str(k.get("kid")): k for k in (self._fetch(uri).get("keys") or []) if k.get("kid")}
        if not keys:
            raise OidcError(f"{uri} returned no keys with a `kid`")
        self._keys = _Keys(keys=keys, fetched_at=now)
        return keys

    # -- verification ----------------------------------------------------

    def verify(self, token: str) -> tuple[str, dict[str, Any]] | None:
        """`(subject, claims)` when the token is valid here, else `None`.

        Returns `None` rather than raising for every rejection, because this is
        one provider in a list and a token it does not recognise may belong to
        the next one. A *configuration* problem still raises: that is not a
        token this provider declines, it is a provider that cannot decide.
        """
        try:
            header_segment, payload_segment, _ = token.split(".")
            header = decode_segment(header_segment)
            claims = decode_segment(payload_segment)
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
            return None

        algorithm = str(header.get("alg") or "")
        if algorithm.lower() == "none" or algorithm not in self.config.algorithms:
            # First, and before any parsing that might be read as acceptance.
            # The specification permits an unsigned token and a library that
            # honours it will verify one.
            return None

        if not self._signature_ok(token, header):
            return None

        if str(claims.get("iss") or "") != self.config.issuer:
            # A correctly signed token from another issuer is a correctly
            # signed token from somebody else.
            return None
        if not self._audience_ok(claims):
            return None

        now = self._now()
        expiry = claims.get("exp")
        if not isinstance(expiry, (int, float)) or now > float(expiry) + self.config.leeway:
            return None
        not_before = claims.get("nbf")
        if isinstance(not_before, (int, float)) and now < float(not_before) - self.config.leeway:
            return None

        subject = str(claims.get("sub") or "")
        if not subject:
            return None

        role = self._role_for(claims)
        if role is None:
            # No default. A default of `viewer` means anybody the issuer will
            # mint a token for can read every contract in the org.
            return None

        org = self.config.org_id
        if org is None:
            raw = claims.get(str(self.config.org_claim))
            try:
                org = int(raw)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return None

        return subject, {"org_id": org, "role": role, "iss": claims.get("iss")}

    def _audience_ok(self, claims: dict[str, Any]) -> bool:
        audience = claims.get("aud")
        if isinstance(audience, str):
            return audience == self.config.audience
        if isinstance(audience, list):
            return self.config.audience in [str(a) for a in audience]
        return False

    def _role_for(self, claims: dict[str, Any]) -> str | None:
        raw = claims.get(self.config.role_claim)
        values = [str(raw)] if isinstance(raw, str) else [str(v) for v in (raw or [])]
        # The highest role any of the subject's claim values maps to. A user in
        # both `developers` and `platform-admins` gets the second.
        rank = {"viewer": 1, "member": 2, "admin": 3, "owner": 4}
        mapped = [self.config.role_map[v] for v in values if v in self.config.role_map]
        return max(mapped, key=lambda r: rank[r]) if mapped else None

    def _signature_ok(self, token: str, header: dict[str, Any]) -> bool:
        kid = str(header.get("kid") or "")
        if not kid:
            # Without a `kid` the only way to check is to try every key, and
            # trying every key is how a rotated-out key stays valid.
            return False
        try:
            keys = self.jwks()
        except OidcError:
            raise
        except Exception:
            return False
        key = keys.get(kid)
        if key is None:
            # One retry with a forced fetch: a key that rotated since the cache
            # was filled is the common case, and failing on it would make every
            # rotation an outage.
            try:
                key = self.jwks(force=True).get(kid)
            except Exception:
                return False
        if key is None:
            return False
        return self._check_signature(token, key, str(header.get("alg")))

    @staticmethod
    def _check_signature(token: str, key: dict[str, Any], algorithm: str) -> bool:
        """Verify with `pyjwt` if it is installed.

        Not reimplemented here. A hand-rolled RSA verification in an
        authentication path is the last place to be clever, and a wrong one
        fails open.
        """
        try:
            import jwt
            from jwt import PyJWKClient  # noqa: F401  (import proves the version has it)
            from jwt.algorithms import RSAAlgorithm
        except ImportError as exc:  # pragma: no cover - depends on the extra
            raise OidcError(
                "OIDC verification needs PyJWT: pip install api-verity-lab[oidc]. "
                "Signature checking is not reimplemented here on purpose"
            ) from exc

        public_key: Any
        try:
            if key.get("kty") == "RSA":
                public_key = RSAAlgorithm.from_jwk(json.dumps(key))
            else:
                from jwt.algorithms import ECAlgorithm

                public_key = ECAlgorithm.from_jwk(json.dumps(key))
            jwt.decode(
                token,
                public_key,
                algorithms=[algorithm],
                # The claims are checked above, against this module's own
                # configuration, so the library is asked for the signature and
                # nothing else. Two places checking `aud` with two notions of
                # what it should be is how one of them ends up not checking.
                options={"verify_aud": False, "verify_exp": False, "verify_iss": False},
            )
        except Exception:
            return False
        return True


__all__ = [
    "DEFAULT_ALGORITHMS",
    "JWKS_TTL_SECONDS",
    "OidcConfig",
    "OidcError",
    "OidcProvider",
    "decode_segment",
]
