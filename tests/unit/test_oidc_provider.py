"""A real identity provider, and the four checks that make it one.

`IdentityProvider` has been a `Protocol` with one implementation — a lookup in
the server's own token table — and a docstring saying "OIDC/SAML adapters
implement this". None did.

Most of this file is about rejection. A token verifier that accepts is easy;
the value is entirely in what it refuses, and every refusal below is a way a
real deployment gets compromised.
"""

from __future__ import annotations

import json
import time
from typing import Any

import pytest

jwt = pytest.importorskip("jwt", reason="the oidc extra is a dev dependency; see pyproject.toml")
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402

from apiverity.server.auth import Role, authenticate  # noqa: E402
from apiverity.server.oidc import OidcConfig, OidcError, OidcProvider  # noqa: E402

_ISSUER = "https://issuer.example.test"
_AUDIENCE = "apiverity"


@pytest.fixture(scope="module")
def keypair() -> tuple[Any, dict[str, Any]]:
    """One RSA key, and its public half as a JWK."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    jwk["kid"] = "key-1"
    jwk["alg"] = "RS256"
    return key, jwk


def _token(
    key: Any, claims: dict[str, Any], *, kid: str | None = "key-1", alg: str = "RS256"
) -> str:
    headers = {"kid": kid} if kid else {}
    return jwt.encode(claims, key, algorithm=alg, headers=headers)


def _claims(**overrides: Any) -> dict[str, Any]:
    base = {
        "iss": _ISSUER,
        "aud": _AUDIENCE,
        "sub": "ada@example.test",
        "exp": int(time.time()) + 300,
        "roles": ["platform-admins"],
    }
    base.update(overrides)
    return base


def _provider(jwk: dict[str, Any], **config: Any) -> OidcProvider:
    settings = {
        "issuer": _ISSUER,
        "audience": _AUDIENCE,
        "role_map": {"platform-admins": "admin", "developers": "member"},
        "org_id": 1,
    }
    settings.update(config)
    return OidcProvider(
        OidcConfig(**settings),
        fetch=lambda url: (
            {"jwks_uri": f"{_ISSUER}/jwks"} if "openid-configuration" in url else {"keys": [jwk]}
        ),
    )


# ------------------------------------------------------------ it accepts one


def test_a_valid_token_verifies(keypair: tuple[Any, dict[str, Any]]) -> None:
    key, jwk = keypair
    result = _provider(jwk).verify(_token(key, _claims()))
    assert result is not None
    subject, claims = result
    assert subject == "ada@example.test"
    assert claims == {"org_id": 1, "role": "admin", "iss": _ISSUER}


def test_it_plugs_into_the_server_s_provider_list(keypair: tuple[Any, dict[str, Any]]) -> None:
    """The point of the abstraction: registered the same way the local
    provider is, and able to run beside it — which is what migrating from
    local tokens to an issuer looks like."""
    key, jwk = keypair
    identity = authenticate([_provider(jwk)], _token(key, _claims()))
    assert identity is not None
    assert identity.role is Role.ADMIN
    assert identity.org_id == 1


# --------------------------------------------------------- what it refuses


def test_an_unsigned_token_is_refused(keypair: tuple[Any, dict[str, Any]]) -> None:
    """The specification permits `alg: none`, and a library that honours it
    will happily verify one."""
    _, jwk = keypair
    unsigned = jwt.encode(_claims(), key=None, algorithm="none", headers={"kid": "key-1"})
    assert _provider(jwk).verify(unsigned) is None


def test_an_algorithm_outside_the_allow_list_is_refused(
    keypair: tuple[Any, dict[str, Any]],
) -> None:
    _, jwk = keypair
    hmac_token = jwt.encode(
        _claims(), "a-shared-secret", algorithm="HS256", headers={"kid": "key-1"}
    )
    assert _provider(jwk).verify(hmac_token) is None


def test_a_token_from_another_issuer_is_refused(keypair: tuple[Any, dict[str, Any]]) -> None:
    """A correctly signed token from another issuer is a correctly signed
    token from somebody else."""
    key, jwk = keypair
    assert _provider(jwk).verify(_token(key, _claims(iss="https://elsewhere.test"))) is None


def test_a_token_for_another_audience_is_refused(keypair: tuple[Any, dict[str, Any]]) -> None:
    """An access token minted for another service is not one for this service.
    Accepting it is the confused-deputy problem in its original form."""
    key, jwk = keypair
    assert _provider(jwk).verify(_token(key, _claims(aud="some-other-service"))) is None


def test_an_audience_list_is_read_correctly(keypair: tuple[Any, dict[str, Any]]) -> None:
    key, jwk = keypair
    assert _provider(jwk).verify(_token(key, _claims(aud=["other", _AUDIENCE]))) is not None
    assert _provider(jwk).verify(_token(key, _claims(aud=["other", "third"]))) is None


def test_an_expired_token_is_refused(keypair: tuple[Any, dict[str, Any]]) -> None:
    key, jwk = keypair
    assert _provider(jwk).verify(_token(key, _claims(exp=int(time.time()) - 1))) is None


def test_a_token_with_no_expiry_is_refused(keypair: tuple[Any, dict[str, Any]]) -> None:
    """A token that never expires is a password with worse ergonomics."""
    key, jwk = keypair
    claims = _claims()
    del claims["exp"]
    assert _provider(jwk).verify(_token(key, claims)) is None


def test_a_token_not_yet_valid_is_refused(keypair: tuple[Any, dict[str, Any]]) -> None:
    key, jwk = keypair
    assert _provider(jwk).verify(_token(key, _claims(nbf=int(time.time()) + 600))) is None


def test_leeway_is_zero_by_default_and_configurable(keypair: tuple[Any, dict[str, Any]]) -> None:
    key, jwk = keypair
    just_expired = _token(key, _claims(exp=int(time.time()) - 5))
    assert _provider(jwk).verify(just_expired) is None
    assert _provider(jwk, leeway=60).verify(just_expired) is not None


def test_a_token_signed_by_an_unknown_key_is_refused(keypair: tuple[Any, dict[str, Any]]) -> None:
    _, jwk = keypair
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    assert _provider(jwk).verify(_token(other, _claims())) is None


def test_a_token_with_no_kid_is_refused(keypair: tuple[Any, dict[str, Any]]) -> None:
    """Without a `kid` the only way to check is to try every key, and trying
    every key is how a rotated-out key stays valid."""
    key, jwk = keypair
    assert _provider(jwk).verify(_token(key, _claims(), kid=None)) is None


def test_a_token_with_an_unknown_kid_is_refused(keypair: tuple[Any, dict[str, Any]]) -> None:
    key, jwk = keypair
    assert _provider(jwk).verify(_token(key, _claims(), kid="key-does-not-exist")) is None


def test_rubbish_is_refused_without_raising(keypair: tuple[Any, dict[str, Any]]) -> None:
    """One provider in a list: a token this one does not recognise may belong
    to the next, so a rejection is `None` rather than an exception."""
    _, jwk = keypair
    provider = _provider(jwk)
    for value in ["", "not-a-jwt", "a.b", "a.b.c", "!!!.???.***"]:
        assert provider.verify(value) is None


# ------------------------------------------------------------------- roles


def test_an_unmapped_subject_gets_no_identity_at_all(
    keypair: tuple[Any, dict[str, Any]],
) -> None:
    """Not `viewer`. A default role means anybody the issuer will mint a token
    for can read every contract in the org."""
    key, jwk = keypair
    assert _provider(jwk).verify(_token(key, _claims(roles=["some-other-group"]))) is None
    assert _provider(jwk).verify(_token(key, _claims(roles=[]))) is None


def test_the_highest_matching_role_wins(keypair: tuple[Any, dict[str, Any]]) -> None:
    key, jwk = keypair
    result = _provider(jwk).verify(_token(key, _claims(roles=["developers", "platform-admins"])))
    assert result is not None and result[1]["role"] == "admin"


def test_a_string_claim_works_as_well_as_a_list(keypair: tuple[Any, dict[str, Any]]) -> None:
    key, jwk = keypair
    result = _provider(jwk).verify(_token(key, _claims(roles="developers")))
    assert result is not None and result[1]["role"] == "member"


def test_the_role_claim_name_is_configurable(keypair: tuple[Any, dict[str, Any]]) -> None:
    """Issuers disagree about where roles live, and none of them is wrong."""
    key, jwk = keypair
    provider = _provider(jwk, role_claim="https://example.test/roles")
    claims = _claims()
    del claims["roles"]
    claims["https://example.test/roles"] = ["developers"]
    result = provider.verify(_token(key, claims))
    assert result is not None and result[1]["role"] == "member"


def test_the_org_can_come_from_a_claim(keypair: tuple[Any, dict[str, Any]]) -> None:
    key, jwk = keypair
    provider = _provider(jwk, org_id=None, org_claim="org")
    result = provider.verify(_token(key, _claims(org=7)))
    assert result is not None and result[1]["org_id"] == 7


def test_a_missing_org_claim_is_refused(keypair: tuple[Any, dict[str, Any]]) -> None:
    key, jwk = keypair
    provider = _provider(jwk, org_id=None, org_claim="org")
    assert provider.verify(_token(key, _claims())) is None


# ------------------------------------------------------------ configuration


@pytest.mark.parametrize(
    ("settings", "message"),
    [
        ({"issuer": ""}, "issuer"),
        ({"audience": ""}, "confused-deputy"),
        ({"role_map": {}}, "role_map"),
        ({"role_map": {"g": "superuser"}}, "roles that do not exist"),
        ({"algorithms": ("none",)}, "absence of one"),
        ({"org_id": None}, "org_id"),
    ],
)
def test_a_configuration_that_cannot_be_safe_is_refused(
    settings: dict[str, Any], message: str
) -> None:
    """At construction, not at the first request. A provider that cannot
    decide is a configuration problem, not a token this one declines."""
    base = {
        "issuer": _ISSUER,
        "audience": _AUDIENCE,
        "role_map": {"g": "member"},
        "org_id": 1,
    }
    base.update(settings)
    with pytest.raises(OidcError, match=message):
        OidcConfig(**base)


def test_default_algorithms_are_asymmetric_only() -> None:
    """With an HMAC algorithm the verification key is the signing key, so
    anybody who can read the configuration can mint tokens."""
    from apiverity.server.oidc import DEFAULT_ALGORITHMS

    assert not any(a.startswith("HS") for a in DEFAULT_ALGORITHMS)


# ------------------------------------------------------------- key handling


def test_a_jwks_uri_outside_the_issuer_is_refused(keypair: tuple[Any, dict[str, Any]]) -> None:
    """Following it silently is how a token gets verified against a key
    nobody here chose."""
    _, jwk = keypair
    provider = OidcProvider(
        OidcConfig(issuer=_ISSUER, audience=_AUDIENCE, role_map={"g": "member"}, org_id=1),
        fetch=lambda url: (
            {"jwks_uri": "https://somewhere-else.test/jwks"}
            if "openid-configuration" in url
            else {"keys": [jwk]}
        ),
    )
    with pytest.raises(OidcError, match="not under the configured issuer"):
        provider.jwks()


def test_an_explicit_jwks_uri_skips_discovery(keypair: tuple[Any, dict[str, Any]]) -> None:
    _, jwk = keypair
    seen: list[str] = []

    def fetch(url: str) -> dict[str, Any]:
        seen.append(url)
        return {"keys": [jwk]}

    provider = OidcProvider(
        OidcConfig(
            issuer=_ISSUER,
            audience=_AUDIENCE,
            role_map={"g": "member"},
            org_id=1,
            jwks_uri="https://anywhere.test/keys",
        ),
        fetch=fetch,
    )
    provider.jwks()
    assert seen == ["https://anywhere.test/keys"]


def test_the_key_set_is_cached_but_not_forever(keypair: tuple[Any, dict[str, Any]]) -> None:
    """Cached, because a fetch per request makes the issuer a dependency of
    every call. Not forever, because a rotated key has to stop working without
    a restart."""
    from apiverity.server.oidc import JWKS_TTL_SECONDS

    _, jwk = keypair
    fetches: list[str] = []
    clock = [1000.0]

    def fetch(url: str) -> dict[str, Any]:
        fetches.append(url)
        return {"keys": [jwk]}

    provider = OidcProvider(
        OidcConfig(
            issuer=_ISSUER,
            audience=_AUDIENCE,
            role_map={"g": "member"},
            org_id=1,
            jwks_uri=f"{_ISSUER}/jwks",
        ),
        fetch=fetch,
        now=lambda: clock[0],
    )
    provider.jwks()
    provider.jwks()
    assert len(fetches) == 1

    clock[0] += JWKS_TTL_SECONDS + 1
    provider.jwks()
    assert len(fetches) == 2


def test_a_rotated_key_is_picked_up_without_a_restart(
    keypair: tuple[Any, dict[str, Any]],
) -> None:
    """A key that rotated since the cache was filled is the common case, and
    failing on it would make every rotation an outage."""
    key, jwk = keypair
    rotated = dict(jwk)
    rotated["kid"] = "key-2"
    served = [[jwk]]

    provider = OidcProvider(
        OidcConfig(
            issuer=_ISSUER,
            audience=_AUDIENCE,
            role_map={"platform-admins": "admin"},
            org_id=1,
            jwks_uri=f"{_ISSUER}/jwks",
        ),
        fetch=lambda url: {"keys": served[0]},
    )
    provider.jwks()  # caches key-1 only
    served[0] = [rotated]
    assert provider.verify(_token(key, _claims(), kid="key-2")) is not None


def test_a_key_set_with_no_kid_is_a_configuration_error(
    keypair: tuple[Any, dict[str, Any]],
) -> None:
    _, jwk = keypair
    bare = {k: v for k, v in jwk.items() if k != "kid"}
    provider = OidcProvider(
        OidcConfig(
            issuer=_ISSUER,
            audience=_AUDIENCE,
            role_map={"g": "member"},
            org_id=1,
            jwks_uri=f"{_ISSUER}/jwks",
        ),
        fetch=lambda url: {"keys": [bare]},
    )
    with pytest.raises(OidcError, match="no keys with a `kid`"):
        provider.jwks()
