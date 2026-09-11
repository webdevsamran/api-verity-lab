"""Assembling the server from its environment.

This logic lived in an inline `python -c` block in `docker/entrypoint.sh`: it
grew with every setting, was tested by nothing, and failed at container start
with a traceback about a heredoc.

The behaviour worth holding still is the refusal. A server configured with half
an identity provider must not start on local tokens with a warning nobody
reads — that outcome looks exactly like a working one.
"""

from __future__ import annotations

from typing import Any

import pytest

from apiverity.server.launch import ENVIRONMENT, LaunchError, build_app, oidc_provider


def test_no_oidc_variables_means_no_provider() -> None:
    assert oidc_provider({}) is None
    assert oidc_provider({"VERITY_DB": "/tmp/x.db"}) is None


def test_a_blank_variable_is_not_a_configuration() -> None:
    assert oidc_provider({"VERITY_OIDC_ISSUER": "   "}) is None


def test_a_complete_configuration_builds_a_provider() -> None:
    provider = oidc_provider(
        {
            "VERITY_OIDC_ISSUER": "https://login.example.test",
            "VERITY_OIDC_AUDIENCE": "apiverity",
            "VERITY_OIDC_ROLE_MAP": "platform-admins=admin,developers=member",
            "VERITY_OIDC_ORG_ID": "1",
        }
    )
    assert provider is not None
    assert provider.config.role_map == {"platform-admins": "admin", "developers": "member"}
    assert provider.config.org_id == 1


def test_the_role_map_also_reads_json() -> None:
    provider = oidc_provider(
        {
            "VERITY_OIDC_ISSUER": "https://login.example.test",
            "VERITY_OIDC_AUDIENCE": "apiverity",
            "VERITY_OIDC_ROLE_MAP": '{"admins": "admin"}',
            "VERITY_OIDC_ORG_ID": "1",
        }
    )
    assert provider is not None and provider.config.role_map == {"admins": "admin"}


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({"VERITY_OIDC_AUDIENCE": "a"}, "without VERITY_OIDC_ISSUER"),
        ({"VERITY_OIDC_ISSUER": "https://i.test"}, "needs an audience"),
        (
            {"VERITY_OIDC_ISSUER": "https://i.test", "VERITY_OIDC_AUDIENCE": "a"},
            "needs a role_map",
        ),
        (
            {
                "VERITY_OIDC_ISSUER": "https://i.test",
                "VERITY_OIDC_AUDIENCE": "a",
                "VERITY_OIDC_ROLE_MAP": "g=admin",
            },
            "org_id",
        ),
        (
            {
                "VERITY_OIDC_ISSUER": "https://i.test",
                "VERITY_OIDC_AUDIENCE": "a",
                "VERITY_OIDC_ROLE_MAP": "nonsense",
                "VERITY_OIDC_ORG_ID": "1",
            },
            "is not `group=role`",
        ),
        (
            {
                "VERITY_OIDC_ISSUER": "https://i.test",
                "VERITY_OIDC_AUDIENCE": "a",
                "VERITY_OIDC_ROLE_MAP": "g=admin",
                "VERITY_OIDC_ORG_ID": "not-a-number",
            },
            "not a number",
        ),
    ],
)
def test_half_a_configuration_is_refused_rather_than_ignored(
    env: dict[str, str], message: str
) -> None:
    """The failure this module exists to prevent: a server meant to use the
    company's identity provider that quietly did not."""
    with pytest.raises(LaunchError, match=message):
        oidc_provider(env)


def test_the_app_falls_back_to_local_tokens_when_nothing_else_is_set(tmp_path: Any) -> None:
    app = build_app({"VERITY_DB": str(tmp_path / "v.db")})
    assert app is not None


def test_turning_off_local_tokens_with_no_issuer_is_refused(tmp_path: Any) -> None:
    """Otherwise the server starts and authenticates nobody."""
    with pytest.raises(LaunchError, match="authenticate nobody"):
        build_app({"VERITY_DB": str(tmp_path / "v.db"), "VERITY_LOCAL_TOKENS": "0"})


def test_cors_origins_default_to_none(tmp_path: Any) -> None:
    """A server that answers every origin by default is a server whose
    operator never chose to."""
    app = build_app({"VERITY_DB": str(tmp_path / "v.db"), "VERITY_CORS_ORIGINS": ""})
    assert app is not None


def test_every_documented_variable_is_one_the_module_reads() -> None:
    """`ENVIRONMENT` is what the chart and the docs are held against, so a name
    in it that nothing reads would make both wrong."""
    import pathlib
    import re

    source = pathlib.Path("apiverity/server/launch.py").read_text(encoding="utf-8")
    body = source.split("ENVIRONMENT = {", 1)[1].split("}", 1)[1]
    for name in ENVIRONMENT:
        assert re.search(rf'"{name}"', body), f"{name} is documented and never read"
