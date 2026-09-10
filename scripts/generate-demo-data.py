"""Generate real frontend demo data by running bundled fixtures through apiverity."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from apiverity.cli.main import main as cli_main
from apiverity.mock import MockServer
from apiverity.specs.loader import detect_and_load

ROOT = Path(__file__).parents[1]
FIX = ROOT / "fixtures"
OUT = ROOT / "web" / "public" / "demo-data.json"


def cli_json(argv):
    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = cli_main(argv)
    assert code in (0, 1), f"{argv} -> {code}"  # 1 = findings present (expected)
    return json.loads(buf.getvalue())


def main() -> None:
    from apiverity.diff.engine import diff_services
    from apiverity.rules.breaking import evaluate_breaking

    v1, v2 = FIX / "apis/versioned/v1.yaml", FIX / "apis/versioned/v2.yaml"
    old, _, _ = detect_and_load(str(v1))
    new, _, _ = detect_and_load(str(v2))
    changes = diff_services(old, new)
    findings = evaluate_breaking(changes)

    crud = FIX / "apis/crud/openapi.yaml"
    service, _, _ = detect_and_load(str(crud))
    drift_service, _, _ = detect_and_load(str(FIX / "apis/drift/openapi.yaml"))

    from apiverity.coverage import measure_coverage
    from apiverity.fuzz.runner import build_cases, run_cases
    from apiverity.runtime.drift import detect_drift

    with MockServer(service, port=8095) as mock:
        base = mock.base_url
        cases = build_cases(service, seed=42)
        results = run_cases(service, base, cases)
        drift = detect_drift(drift_service, base)

    from apiverity.performance.engine import measure

    perf = measure(service, base, iterations=15)

    exercised = {r.operation_key for r in results}
    statuses: dict[str, set[int]] = {}
    for r in results:
        if r.actual_status:
            statuses.setdefault(r.operation_key, set()).add(r.actual_status)
    coverage = measure_coverage(
        service, exercised_operations=exercised, statuses_by_operation=statuses
    )

    from apiverity.stateful.engine import WorkflowEngine, load_workflow_manifest

    wf = load_workflow_manifest(str(FIX / "workflows/crud-lifecycle.yaml"))
    with MockServer(service, port=8096) as mock:
        wf_result = WorkflowEngine(wf, mock.base_url).run()

    from apiverity.rules.breaking import CATALOG

    rules_catalog = [
        {"rule_id": rid, "severity": spec.severity.value, "description": spec.description}
        for rid, spec in sorted(CATALOG.items())
    ]

    contract_tree = [
        {
            "key": op.key,
            "method": op.method,
            "path": op.path,
            "summary": op.summary,
            "deprecated": op.deprecated,
            "parameters": [p.name for p in op.parameters],
            "responses": [r.status for r in op.responses],
        }
        for op in service.operations
    ]

    # --- semver verdict ---------------------------------------------------
    from apiverity.rules.semver import SemverPolicy

    semver_findings = SemverPolicy(old.version, new.version).evaluate(findings, changes)
    verdict = {
        "old_version": old.version,
        "new_version": new.version,
        "required_bump": "major"
        if any(f.severity.value == "ERROR" for f in findings)
        else ("minor" if any(f.severity.value == "WARN" for f in findings) else "patch"),
        "compliant": not semver_findings,
        "findings": [f.model_dump() for f in semver_findings],
    }

    # --- changelog ----------------------------------------------------------
    from apiverity.rules.changelog import generate_changelog

    changelog_md = generate_changelog(service.title, old.version, new.version, changes, findings)

    # --- failure minimizer ----------------------------------------------------
    from apiverity.fuzz.minimize import minimize_failures

    with MockServer(service, port=8097) as mock:
        minimized = minimize_failures(service, mock.base_url, results, cases, max_minimize=5)

    # --- replay plan (dry-run only, localhost allowlist) -------------------------
    from apiverity.fuzz.corpus import export_corpus
    from apiverity.traffic.replay import ReplayEntry, replay_corpus

    corpus_path = OUT.parent / "demo-corpus.json"
    export_corpus(cases, str(corpus_path))
    # `url_path`, not `path`. `TestCase` renamed the field and this line kept
    # the old name, so the generator has raised AttributeError on every run
    # since -- and because nothing runs it in CI, the committed
    # web/public/demo-data.json simply stopped being updated. Six pages that
    # read sections written after that point have shown "Loading..." forever.
    replay_entries = [
        ReplayEntry(
            method=c.method, path=c.url_path, query=c.query, headers=dict(c.headers), body=None
        )
        for c in cases
        if c.method == "GET"
    ]
    # A target nothing listens on, with an allowlist that contains only it.
    # The run is dry: the point is the plan, and a plan that reached a live
    # server would not be one.
    replay_report = replay_corpus(
        replay_entries,
        "http://127.0.0.1:9/",
        allowed_hosts=["http://127.0.0.1:9"],
        dry_run=True,
    )
    replay_section = {
        "manifest": {
            "target": "http://127.0.0.1:9/",
            "corpus": "demo-corpus.json",
            "entries": len(replay_entries),
            "rate_per_second": 10.0,
            "safety_class": "dev",
            "destructive_methods_allowed": False,
        },
        "dry_run": replay_report.model_dump(),
    }

    # --- self-hosted org snapshot (real server store, in-memory) -----------------
    from apiverity.server import Store

    store = Store(":memory:")
    org_id = store.create_org("acme-demo")
    store.add_user(org_id, "alice", "owner", display_name="Alice Chen", token="unused")
    store.add_user(org_id, "bob", "member", display_name="Bob Diaz", token="unused")
    store.add_user(org_id, "svc-ci", "member", kind="service_account", token="unused")
    cid1 = store.publish_contract(
        org_id, "Catalog", "1.0.0", "openapi", {"openapi": "3.1.0"}, "alice"
    )
    cid2 = store.publish_contract(
        org_id, "Catalog", "2.0.0", "openapi", {"openapi": "3.1.0"}, "alice"
    )
    store.register_environment(org_id, "dev", "http://127.0.0.1:8095", "dev", owner="platform")
    store.register_environment(
        org_id, "staging", "https://staging.internal", "staging", owner="platform"
    )
    store.set_policy(
        org_id, "breaking", "max_breaking=0" + chr(10) + "require_approval_on_breaking=true"
    )
    aid = store.request_approval(
        org_id, "Catalog", "1.0.0", "2.0.0", "remove legacy sort param", "bob"
    )
    store.decide_approval(aid, "approved", "alice")
    rid = store.record_run(
        org_id,
        "verification",
        "svc-ci",
        status="passed",
        verification_for="Catalog@2.0.0",
        environment="staging",
    )
    store.record_run(org_id, "load", "svc-ci", status="running", environment="staging")
    store.audit_append(org_id, "alice", "contract.published", "Catalog@1.0.0")
    store.audit_append(org_id, "alice", "contract.published", "Catalog@2.0.0")
    store.audit_append(org_id, "alice", "approval.decided", f"approval#{aid}")
    store.audit_append(org_id, "svc-ci", "run.completed", f"run#{rid}")
    store.register_webhook(
        org_id,
        "https://hooks.internal/verity",
        "wh-ref",
        ["breaking_change", "verification.failed"],
    )
    org_section = {
        "org": {"id": org_id, "name": "acme-demo"},
        "users": store.list_users(org_id),
        "contracts": store.list_contracts(org_id),
        "environments": store.list_environments(org_id),
        "policies": [
            {
                "name": "breaking",
                "content": "max_breaking=0" + chr(10) + "require_approval_on_breaking=true",
            }
        ],
        "approvals": [store.get_approval(aid)],
        "runs": [
            {
                "id": rid,
                "kind": "verification",
                "status": "passed",
                "requested_by": "svc-ci",
                "verification_for": "Catalog@2.0.0",
                "environment": "staging",
            },
            {
                "id": rid + 1,
                "kind": "load",
                "status": "running",
                "requested_by": "svc-ci",
                "verification_for": None,
                "environment": "staging",
            },
        ],
        "audit_events": store.audit_list(org_id),
        "webhooks": store.list_webhooks(org_id),
        "chain_valid": store.audit_verify_chain(org_id),
    }
    del cid1, cid2

    # --- API catalog index -----------------------------------------------------
    # ----------------------------------------------------------- blast radius
    #
    # "severity: ERROR" and "this breaks checkout-service and mobile-v3" are
    # the same fact and not the same message, and only the second one gets a
    # release held. The registry ships `complete: false`, so the radius adds
    # information and softens nothing -- and `DELETE /users/{id}` lands in
    # `unclaimed_operations`, which is the gap an incomplete registry exists
    # to make visible rather than hide.
    from apiverity.rules.consumers import blast_radius, load_registry

    registry = load_registry(str(FIX / "consumers/registry.yaml"))
    blast_section = blast_radius(findings, registry)
    # Posix, because the value is a path this generator read on whichever
    # machine ran it, and a backslash in committed demo data makes the file
    # differ by platform.
    blast_section["registry"] = "fixtures/consumers/registry.yaml"
    errors: dict[str, int] = {}
    for finding in findings:
        if finding.severity.value == "ERROR" and finding.operation_key:
            errors[finding.operation_key] = errors.get(finding.operation_key, 0) + 1
    blast_section["errors_by_operation"] = dict(sorted(errors.items()))

    # ---------------------------------------------------------------- agents
    #
    # A fleet, not a screenshot. Three mock MCP servers with deliberately
    # different postures are started here and really probed, so the fleet view
    # renders findings this run produced rather than a hand-written sample:
    # one that matches its manifest, one that has drifted, and one serving a
    # tool nobody declared. Every number on that page came off a socket.
    from apiverity.mock.mcp_server import McpMockServer
    from apiverity.rules.budget import Budget, Limit
    from apiverity.rules.budget import evaluate as evaluate_budget
    from apiverity.runtime.mcp_drift import detect_mcp_drift
    from apiverity.security.mcp_poisoning import scan_mcp_manifest
    from apiverity.specs.mcp.manifest import load_manifest

    declared_payload = json.loads((FIX / "mcp/tools_v1.json").read_text(encoding="utf-8"))
    declared_tools = declared_payload["tools"]
    declared_service, _ = load_manifest(declared_payload, label="orders-mcp")

    served_v2 = json.loads((FIX / "mcp/tools_v2.json").read_text(encoding="utf-8"))["tools"]
    with_extra = [
        *declared_tools,
        {
            "name": "export_all_orders",
            "description": "Exports every order for the tenant.",
            "inputSchema": {"type": "object", "properties": {}},
        },
    ]

    fleet = []
    for name, served in (
        ("orders-mcp", declared_tools),
        ("orders-mcp-canary", served_v2),
        ("partner-mcp", with_extra),
    ):
        with McpMockServer(served) as server:
            report = detect_mcp_drift(declared_service, server.endpoint)
        fleet.append(
            {
                "name": name,
                "endpoint": report.target,
                "tools_declared": report.tools_declared,
                "tools_served": report.tools_served,
                "protocol_revision": report.observation.get("protocol_revision"),
                "era": report.observation.get("era"),
                "auth": report.auth_posture,
                "findings": [f.model_dump() for f in report.findings],
                "duration_ms": report.duration_ms,
            }
        )

    poisoned_payload = json.loads((FIX / "mcp/tools_poisoned.json").read_text(encoding="utf-8"))
    poisoned_service, _ = load_manifest(poisoned_payload, label="tools_poisoned")
    poisoning_findings = [f.model_dump() for f in scan_mcp_manifest(poisoned_service)]

    budget = Budget(
        version=1,
        window="1m",
        limits=[
            Limit(operation_key="tool cancel_order", max_calls=0, window="1m"),
            Limit(operation_key="tool search_orders", max_calls=3, window="1m"),
            Limit(operation_key="tool list_regions", max_calls=50, window="1m"),
        ],
        source="demo budget (in-memory)",
    )
    # A burst that straddles a clock minute: two and three in tumbling
    # buckets, five in the sliding window the checker actually uses.
    burst_start = datetime(2026, 3, 1, 12, 0, 50, tzinfo=UTC)
    budget_calls = [
        {
            "operation_key": "tool search_orders",
            "at": (burst_start + timedelta(seconds=10 * n)).isoformat(),
        }
        for n in range(5)
    ] + [
        {"operation_key": "tool cancel_order", "at": burst_start.isoformat()},
        {"operation_key": "tool undeclared_helper", "at": burst_start.isoformat()},
    ]
    budget_findings = [
        f.model_dump()
        for f in evaluate_budget(
            budget, budget_calls, declared_operations={op.key for op in declared_service.operations}
        )
    ]

    agents_section = {
        "fleet": fleet,
        "poisoning": {
            "manifest": "fixtures/mcp/tools_poisoned.json",
            "tools": len(poisoned_service.operations),
            "findings": poisoning_findings,
        },
        "budget": {
            "window": budget.window,
            "limits": [
                {
                    "operation_key": lim.operation_key,
                    "max_calls": lim.max_calls,
                    "window": lim.window,
                }
                for lim in budget.limits
            ],
            "calls_observed": len(budget_calls),
            "findings": budget_findings,
        },
    }

    catalog_section = {
        "services": [
            {
                "title": "Catalog Service",
                "protocol": "openapi",
                "lifecycle": "stable",
                "owner": "platform-team",
                "product": "Storefront",
                "versions": ["1.0.0", "2.0.0"],
                "environments": ["dev", "staging"],
            },
            {
                "title": "Drift Demo API",
                "protocol": "openapi",
                "lifecycle": "beta",
                "owner": "integrations",
                "product": "Storefront",
                "versions": ["0.3.0"],
                "environments": ["dev"],
            },
        ],
    }

    payload = {
        "meta": {
            "tool": "apiverity",
            "generated_from": "fixtures/apis (crud, versioned v1->v2, drift)"
            " + self-hosted server store snapshot",
            "label": "EXAMPLE RUN — generated locally from bundled fixture APIs",
        },
        "diff": {
            "old_version": old.version,
            "new_version": new.version,
            "changes": [c.model_dump() for c in changes],
        },
        "breaking": {"findings": [f.model_dump() for f in findings]},
        "test": {
            "total": len(results),
            "passed": sum(1 for r in results if r.status == "pass"),
            "failed": sum(1 for r in results if r.status != "pass"),
            "results": [r.model_dump() for r in results],
        },
        "drift": {"findings": [f.model_dump() for f in drift.findings]},
        "performance": {"operations": json.loads(perf.model_dump_json())["operations"]},
        "coverage": {
            "overall_percent": coverage.overall_percent(),
            "operations": json.loads(coverage.model_dump_json())["operations"],
        },
        "rules": {"count": len(rules_catalog), "catalog": rules_catalog},
        "workflow": {
            "name": wf.name,
            "description": wf.description,
            "result": json.loads(wf_result.model_dump_json()),
        },
        "contract": {
            "title": service.title,
            "version": service.version,
            "operations": contract_tree,
        },
        "semver": verdict,
        "changelog": {"markdown": changelog_md},
        "minimizer": {
            "attempted": len(minimized),
            "results": [r.model_dump() for r in minimized],
        },
        "replay": replay_section,
        "org": org_section,
        "catalog": catalog_section,
        "agents": agents_section,
        "blast": blast_section,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
