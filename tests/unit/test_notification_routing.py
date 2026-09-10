"""Sending a finding to the people it is about.

A gate that posts everything to one #api-alerts channel produces a channel
that is muted within a month, and after that the gate is decorative. Both
things needed to route already existed and neither had ever been used to decide
where a message goes: CODEOWNERS says who owns the contract, and the consumer
registry says who calls the operation.

The two audiences are not the same people and do not want the same message. An
owner needs to know what they changed; a consumer needs to know what is about
to break for them. So the tests below are mostly about *who gets what* -- and
about the findings that reach nobody, because a routing layer that drops those
silently is worse than the shared channel it replaced.
"""

from __future__ import annotations

from typing import Any

import pytest

from apiverity.reports.routing import Route, load_routes, plan_notifications

OWNER_URL = "https://hooks.test/platform"
CONSUMER_URL = "https://hooks.test/checkout"


def _finding(
    rule_id: str, severity: str = "ERROR", operation: str = "GET /users"
) -> dict[str, Any]:
    return {
        "rule_id": rule_id,
        "severity": severity,
        "operation_key": operation,
        "message": f"{rule_id} happened",
    }


ROUTES = {
    "@platform": Route(team="@platform", url=OWNER_URL),
    "checkout": Route(team="checkout", url=CONSUMER_URL, kind="teams"),
}


def _plan(findings: list[dict[str, Any]], **kwargs: Any):
    defaults: dict[str, Any] = {
        "contract_path": "openapi.yaml",
        "owners": ("@platform",),
        "consumers_by_operation": {"GET /users": ["checkout-service"]},
        "teams_by_consumer": {"checkout-service": "checkout"},
    }
    defaults.update(kwargs)
    return plan_notifications(findings, ROUTES, **defaults)


# ------------------------------------------------------------------ routes


def test_a_bare_url_is_a_valid_route() -> None:
    """It is what someone types first, and refusing it would spend the
    feature's first five minutes on a schema."""
    routes = load_routes({"backend": "https://hooks.test/backend"})
    assert routes["backend"].url == "https://hooks.test/backend"
    assert routes["backend"].kind == "slack"


def test_the_long_form_carries_the_destination_kind() -> None:
    routes = load_routes({"backend": {"url": "https://x.test", "kind": "TEAMS"}})
    assert routes["backend"].kind == "teams"


def test_a_route_with_no_url_is_refused() -> None:
    with pytest.raises(ValueError, match="url"):
        load_routes({"backend": {"kind": "slack"}})


# ------------------------------------------------------- who gets what


def test_the_owner_gets_every_gating_finding() -> None:
    plan = _plan([_finding("BRK-A"), _finding("BRK-B", "WARN")])
    owner = next(m for m in plan.messages if m.audience == "owner")
    assert owner.team == "@platform"
    assert set(owner.rule_ids) == {"BRK-A", "BRK-B"}


def test_a_consumer_gets_only_what_breaks_them() -> None:
    """A warning is a conversation the owning team has with itself.

    Forwarding every one of them to five other teams is how a routing layer
    recreates the channel it replaced.
    """
    plan = _plan([_finding("BRK-A"), _finding("BRK-B", "WARN")])
    consumer = next(m for m in plan.messages if m.audience == "consumer")
    assert consumer.rule_ids == ("BRK-A",)


def test_a_consumer_hears_nothing_about_an_operation_they_do_not_call() -> None:
    plan = _plan([_finding("BRK-A", operation="GET /admin")])
    assert [m.audience for m in plan.messages] == ["owner"]


def test_info_findings_route_nowhere() -> None:
    """Nobody needs a channel message about a note."""
    plan = _plan([_finding("SEC-NOTE", "INFO")])
    assert plan.messages == []


def test_a_clean_run_sends_nothing() -> None:
    assert plan_notifications([], ROUTES).messages == []


# ------------------------------------------------ what could not be routed


def test_a_finding_nobody_owns_is_reported_not_dropped() -> None:
    """The one that ends up nowhere is the one worth naming."""
    plan = _plan([_finding("BRK-A", operation="GET /admin")], owners=())
    assert plan.messages == []
    assert [u["rule_id"] for u in plan.unrouted] == ["BRK-A"]
    assert "CODEOWNERS" in plan.unrouted[0]["reason"]


def test_a_team_with_no_route_is_named() -> None:
    """Distinct from a finding nobody owns: this one has an owner, and the
    configuration is what is missing."""
    plan = _plan([_finding("BRK-A")], owners=("@nobody",))
    assert "@nobody" in plan.unknown_teams


def test_an_unrouted_finding_says_which_kind_of_gap_it_is() -> None:
    plan = _plan([_finding("BRK-A", operation="GET /admin")], owners=("@nobody",))
    assert plan.unrouted
    assert "no route configured" in plan.unrouted[0]["reason"]


# ---------------------------------------------------------------- payloads


def test_slack_and_teams_get_the_shapes_they_accept() -> None:
    plan = _plan([_finding("BRK-A")])
    owner = next(m for m in plan.messages if m.audience == "owner")
    consumer = next(m for m in plan.messages if m.audience == "consumer")
    assert set(owner.payload()) == {"text"}
    assert set(consumer.payload()) == {"title", "text"}


def test_a_raw_destination_keeps_the_fields_separate() -> None:
    """For a consumer that is not Slack or Teams and wants to render its own."""
    routes = {"backend": Route(team="backend", url="https://x.test", kind="raw")}
    plan = plan_notifications([_finding("BRK-A")], routes, owners=("backend",))
    assert set(plan.messages[0].payload()) == {"subject", "body", "team"}


def test_a_long_finding_list_is_capped_in_the_message() -> None:
    """Forty bullet points in a chat message is a message nobody finishes."""
    plan = _plan([_finding(f"BRK-{i:03d}") for i in range(40)])
    owner = next(m for m in plan.messages if m.audience == "owner")
    assert "and 30 more" in owner.body
    # Capped in the text, complete in the metadata: a caller logging what was
    # sent should see all forty.
    assert len(owner.rule_ids) == 40


def test_the_owner_message_says_how_to_understand_a_rule() -> None:
    plan = _plan([_finding("BRK-A")])
    owner = next(m for m in plan.messages if m.audience == "owner")
    assert "apiverity explain" in owner.body


# ------------------------------------------------------------- the command


def test_the_command_sends_nothing_without_being_asked(tmp_path: Any) -> None:
    """A tool that posts to a team's channel as a side effect of being run has
    done something the person running it did not ask for."""
    import contextlib
    import io
    import json

    from apiverity.cli.main import main

    artifact = tmp_path / "breaking.json"
    artifact.write_text(
        json.dumps({"new_spec": "openapi.yaml", "findings": [_finding("BRK-A")]}),
        encoding="utf-8",
    )
    routes = tmp_path / "routes.yaml"
    routes.write_text(f"routes:\n  '@platform': {OWNER_URL}\n", encoding="utf-8")
    owners = tmp_path / ".github"
    owners.mkdir()
    (owners / "CODEOWNERS").write_text("openapi.yaml @platform\n", encoding="utf-8")

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = main(
            [
                "--no-config",
                "notify",
                str(artifact),
                "--routes",
                str(routes),
                "--root",
                str(tmp_path),
                "--json",
            ]
        )
    assert code == 0
    payload = json.loads(buffer.getvalue())
    assert payload["sent"] is False
    assert payload["owners"] == ["@platform"]
    assert [m["team"] for m in payload["messages"]] == ["@platform"]
    assert "delivered" not in payload


def test_the_command_refuses_an_artifact_with_no_findings_array(tmp_path: Any) -> None:
    """`report.findings` and a top-level `findings` are different shapes, and
    routing the wrong one would send an empty message to everybody."""
    import contextlib
    import io
    import json

    from apiverity.cli.main import main

    artifact = tmp_path / "x.json"
    artifact.write_text(json.dumps({"report": {"findings": []}}), encoding="utf-8")
    routes = tmp_path / "routes.yaml"
    routes.write_text("routes: {}\n", encoding="utf-8")

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
        code = main(["--no-config", "notify", str(artifact), "--routes", str(routes)])
    assert code == 2
    assert "findings" in buffer.getvalue()
