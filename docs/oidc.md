# Authenticating against your identity provider

```python
from apiverity.server.api import create_app
from apiverity.server.auth import LocalTokenProvider
from apiverity.server.oidc import OidcConfig, OidcProvider

oidc = OidcProvider(OidcConfig(
    issuer="https://login.example.com",
    audience="apiverity",
    role_claim="groups",
    role_map={"platform-admins": "admin", "developers": "member"},
    org_id=1,
))

app = create_app(store, providers=[oidc, LocalTokenProvider(store)])
```

`IdentityProvider` has been a `Protocol` with one implementation — a lookup in
the server's own token table — and a docstring saying "OIDC/SAML adapters
implement this". None did, so a team with an identity provider had an
abstraction and no way to use it.

Both providers can run at once. That is what migrating from local tokens to an
issuer looks like: add the OIDC provider, move people over, remove the local
one.

Needs the extra: `pip install api-verity-lab[oidc]`.

## The four checks

Skip any one and this is a base64 decoder.

**The signature**, against a key from the issuer's JWKS endpoint selected by the
token's `kid`. A token with no `kid`, or an unknown one, is rejected rather than
tried against every key — trying them all is how a rotated-out key stays valid.

**`iss`**. A correctly signed token from another issuer is a correctly signed
token from somebody else.

**`aud`**. An access token minted for another service is not an access token
for this one. Accepting it is the confused-deputy problem in its original form,
which is why `audience` has no default and construction fails without it.

**`exp`**, with no leeway by default. A token that expired is a token that
expired; a grace period is a decision somebody should make deliberately
(`leeway=60`). A token with *no* `exp` is refused: that is a password with
worse ergonomics.

`alg: none` is rejected before anything else, along with any algorithm outside
the allow-list. The JWT specification permits an unsigned token, and a library
that honours it will verify one. The default algorithms are asymmetric only —
with HMAC the verification key is the signing key, so anybody who can read the
server's configuration can mint tokens.

## Roles are mapped, never defaulted

An identity provider does not know what `admin` means here, so `role_map` is
required and a subject whose claim matches nothing gets **no identity at all**.

Not `viewer`. A default role means anybody the issuer will mint a token for can
read every contract in the org — which is a much larger set of people than the
ones you meant to invite.

Where roles live differs by issuer (`roles`, `groups`,
`https://example.com/roles`) and none of them is wrong, so `role_claim` is
configurable. A subject in several mapped groups gets the highest of them.

## Key rotation

The key set is cached for five minutes — a fetch per request would make the
issuer a dependency of every call, and caching forever would mean a rotated key
keeps working until a restart.

A `kid` that is not in the cache triggers one forced refetch before the token is
rejected. A key rotated since the cache was filled is the common case, and
failing on it would make every rotation an outage.

A discovery document pointing `jwks_uri` at a host outside the issuer is
**refused**. Following it silently is how a token gets verified against a key
nobody here chose. Set `jwks_uri` explicitly if that is deliberate.

## Signature checking is not implemented here

It calls PyJWT. A hand-rolled RSA verification in an authentication path is the
last place to be clever, and a wrong one fails open.

The library is asked for the signature and nothing else — `iss`, `aud` and `exp`
are checked in this module against its own configuration. Two places checking
`aud` with two notions of what it should be is how one of them ends up not
checking.

## SAML

Not implemented. SAML is XML signature verification, which is a larger and much
sharper problem than this module, and a half-done one would be worse than none.

`IdentityProvider` is still the seam, and this module is the worked example of
implementing it.
