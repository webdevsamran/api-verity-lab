"""Validate real emitted artifacts against `schemas/result-v1.schema.json`.

The CI step named *"Validate bundled result artifacts against
schemas/result-v1"* did not do that. Its body was:

    schema = json.loads(pathlib.Path("schemas/result-v1.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    print("result-v1 schema is valid")

`check_schema` checks that the schema *document* is a well-formed JSON Schema.
It never loaded an artifact. So the step was green, required, and
branch-protected while proving nothing about the thing it was named for -- and
a schema change that broke every emitted artifact would have sailed through it.

This runs the real commands against the bundled fixtures, captures each
`--json` payload, and validates it against the schema. A payload that omits a
required field, or contradicts a declared type, fails the build.

    python scripts/validate_result_artifacts.py
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "schemas" / "result-v1.schema.json"
FIXTURES = ROOT / "fixtures"

sys.path.insert(0, str(ROOT))

#: (label, argv). Each is a command a user runs and whose output a CI gate or
#: the frontend consumes, so each must satisfy the published schema.
#: Commands that write files need somewhere to write them. A scratch
#: directory, not the repository: this script runs in CI on a clean tree and
#: must leave one.
_SCRATCH = Path(tempfile.mkdtemp(prefix="apiverity-artifacts-"))


def _notify_artifact() -> Path:
    """A minimal findings artifact for `notify` to route.

    Written rather than produced by running `breaking` first, because this
    script checks artifact *shapes* and chaining one command's output into
    another's input would make a failure here ambiguous about which command
    caused it.
    """
    directory = _SCRATCH / "notify"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "findings.json"
    path.write_text(
        json.dumps(
            {
                "new_spec": "openapi.yaml",
                "findings": [
                    {
                        "rule_id": "BRK-RESP-FIELD-REMOVED",
                        "severity": "ERROR",
                        "operation_key": "GET /users",
                        "message": "a response field was removed",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    owners = directory / ".github"
    owners.mkdir(parents=True, exist_ok=True)
    (owners / "CODEOWNERS").write_text("openapi.yaml @platform\n", encoding="utf-8")
    return path


def _notify_routes() -> Path:
    directory = _SCRATCH / "notify"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "routes.yaml"
    path.write_text("routes:\n  '@platform': https://hooks.invalid/x\n", encoding="utf-8")
    return path


def _sweep_artifact() -> Path:
    """Where `main` puts a sweep of the fixture tree, for `digest` to slice.

    Produced from a real run rather than checked in, the way the evidence
    pack's input is: a committed sweep would go stale against the fixtures it
    describes, and a digest of a stale sweep would validate cleanly while
    describing a repository that no longer exists.
    """
    directory = _SCRATCH / "digest"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / "sweep.json"


def _monitor_state() -> Path:
    """A state file path for `monitor`, deliberately not created.

    The first run against a missing state file is the baseline run, which is
    the shape every other command's artifact check has: one invocation, from
    nothing, with no prior run to depend on.
    """
    directory = _SCRATCH / "monitor"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / "state.json"


def _audit_db() -> Path:
    """A server database with a few audit entries in it.

    Built here rather than fixtured, because the entries are hash-chained: a
    checked-in database would have to be regenerated whenever the chain's
    basis string changed, and a stale one would fail as "tampering".
    """
    from apiverity.server.store import Store

    path = _SCRATCH / "audit" / "server.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    store = Store(str(path))
    org = store.create_org("artifacts")
    for index in range(3):
        store.audit_append(org, "ci", "policy.updated", f"policy-{index}", {"index": index})
    store.close()
    return path


COMMANDS: list[tuple[str, list[str]]] = [
    (
        "diff",
        [
            "diff",
            str(FIXTURES / "apis/versioned/v1.yaml"),
            str(FIXTURES / "apis/versioned/v2.yaml"),
            "--json",
        ],
    ),
    (
        "breaking",
        [
            "breaking",
            str(FIXTURES / "apis/versioned/v1.yaml"),
            str(FIXTURES / "apis/versioned/v2.yaml"),
            "--json",
        ],
    ),
    (
        "validate",
        ["validate", str(FIXTURES / "apis/versioned/v1.yaml"), "--json"],
    ),
    # `validate` is the only command that writes the constrained `protocol`
    # field, so pointing it at a single OpenAPI fixture tested exactly one of
    # the enum's values. AsyncAPI shipped, emitted `"protocol": "asyncapi"`,
    # and violated result-v1 on the happy path without failing anything. One
    # non-OpenAPI protocol here is what turns that into a red build.
    (
        "validate (asyncapi)",
        ["validate", str(FIXTURES / "asyncapi/events-v1.yaml"), "--json"],
    ),
    # MCP goes through the same emit path; the artifact must satisfy the same
    # published schema, including the `protocol` enum that `validate` writes.
    (
        "validate (mcp)",
        ["validate", str(FIXTURES / "mcp/tools_v1.json"), "--json"],
    ),
    # SOAP is the seventh format and the one whose artifacts nobody would have
    # looked at by hand, which is the whole reason it is here rather than
    # assumed. `fault:<name>` response statuses go through this path too.
    (
        "validate (wsdl)",
        ["validate", str(FIXTURES / "wsdl/orders-v1.wsdl"), "--json"],
    ),
    (
        "breaking (wsdl)",
        [
            "breaking",
            str(FIXTURES / "wsdl/orders-v1.wsdl"),
            str(FIXTURES / "wsdl/orders-v2.wsdl"),
            "--json",
        ],
    ),
    (
        "breaking (mcp)",
        [
            "breaking",
            str(FIXTURES / "mcp/tools_v1.json"),
            str(FIXTURES / "mcp/tools_v2.json"),
            "--json",
        ],
    ),
    (
        "coverage",
        ["coverage", str(FIXTURES / "apis/versioned/v1.yaml"), "--json"],
    ),
    ("config", ["config", "show", "--path", str(ROOT / ".apiverity.yaml"), "--json"]),
    ("rules", ["rules", "--json"]),
    # `explain` writes a `command` value, and that field is enum-constrained.
    # A new command that emits an artifact has to be added to the schema, and
    # this is the step that says so.
    ("explain", ["explain", "BRK-OP-REMOVED", "--json"]),
    (
        "changelog",
        [
            "changelog",
            str(FIXTURES / "apis/versioned/v1.yaml"),
            str(FIXTURES / "apis/versioned/v2.yaml"),
            "--json",
        ],
    ),
    ("plugins", ["plugins", "--json"]),
    # `mcp-lock` writes a file, so these two run in order against a scratch
    # path: write the baseline, then check the same manifest against it. Both
    # emit artifacts and both name a `command` the enum has to allow.
    (
        "mcp-lock write",
        [
            "mcp-lock",
            "write",
            str(FIXTURES / "mcp/tools_v1.json"),
            "--lock",
            str(_SCRATCH / "mcp.lock"),
            "--force",
            "--json",
        ],
    ),
    (
        "mcp-lock check",
        [
            "mcp-lock",
            "check",
            str(FIXTURES / "mcp/tools_v1.json"),
            "--lock",
            str(_SCRATCH / "mcp.lock"),
            "--json",
        ],
    ),
    # Reads the artifact `main()` wrote from a real `validate` run, so the
    # evidence pack is assembled from output this script itself produced
    # rather than from a fixture somebody typed.
    # The command whose artifact shape varies most, and the one that was never
    # here. Every drift mode nested its findings under `report`, outside the
    # top-level `findings` array this schema constrains, so the contract did
    # not apply to the command that needed it most.
    (
        "drift (corpus)",
        [
            "drift",
            str(FIXTURES / "apis/crud/openapi.yaml"),
            "--corpus",
            str(FIXTURES / "traffic/crud.har"),
            "--json",
        ],
    ),
    (
        "evidence",
        [
            "evidence",
            str(_SCRATCH / "record.json"),
            "-o",
            str(_SCRATCH / "pack"),
            "--as-of",
            "2026-01-01T00:00:00Z",
            "--json",
        ],
    ),
    # `audit` writes a document meant to leave the building, and then reads it
    # back with nothing but itself. Both halves emit an artifact, and neither
    # was covered by anything until the command existed.
    (
        "audit export",
        [
            "audit",
            "export",
            "--db",
            str(_audit_db()),
            "--org-id",
            "1",
            "-o",
            str(_SCRATCH / "audit" / "export.json"),
            "--json",
        ],
    ),
    (
        "audit verify",
        ["audit", "verify", str(_SCRATCH / "audit" / "export.json"), "--json"],
    ),
    # `--sdk` adds a top-level key of its own (`sdk_conventions`), so the
    # artifact it produces is a different shape from a plain `breaking` run and
    # is checked as one.
    (
        "breaking (--sdk)",
        [
            "breaking",
            str(FIXTURES / "apis/sdk/v1.yaml"),
            str(FIXTURES / "apis/sdk/v2.yaml"),
            "--sdk",
            "--json",
        ],
    ),
    # `agent-setup` writes files rather than reading a contract. Run dry, so
    # this check never installs anything into the checkout it runs in.
    (
        "agent-setup",
        ["agent-setup", str(_SCRATCH / "agent-setup"), "--json"],
    ),
    # `graph` walks a tree rather than loading one contract, and emits a shape
    # no other command does.
    (
        "graph",
        ["graph", str(FIXTURES / "apis/graph"), "--mermaid", "--json"],
    ),
    # `digest` reads a sweep rather than a contract, so `run_json` is called
    # for it at import time the way the evidence pack's seed artifact is.
    (
        "digest",
        ["digest", str(_sweep_artifact()), "--json"],
    ),
    # `monitor` wraps another command and emits an artifact of its own, so its
    # `command` value and enriched envelope are checked here like any other.
    # The inner command reads a corpus rather than a socket: this script must
    # not need a network.
    (
        "monitor",
        [
            "monitor",
            "--state",
            str(_monitor_state()),
            "--json",
            "--",
            "drift",
            str(FIXTURES / "apis/drift/openapi.yaml"),
            "--corpus",
            str(FIXTURES / "traffic/users-march.har"),
        ],
    ),
    (
        "notify",
        [
            "notify",
            str(_notify_artifact()),
            "--routes",
            str(_notify_routes()),
            "--root",
            str(_SCRATCH / "notify"),
            "--json",
        ],
    ),
]


def run_json(argv: list[str]) -> tuple[int, str]:
    """Run the CLI in-process and capture stdout.

    In-process rather than as a subprocess so this needs no installed console
    script and reports a real traceback when something breaks.
    """
    from apiverity.cli.main import main as cli_main

    buffer = io.StringIO()
    code = 0
    try:
        with contextlib.redirect_stdout(buffer):
            code = cli_main(argv) or 0
    except SystemExit as exc:  # argparse and explicit exits
        code = exc.code if isinstance(exc.code, int) else 1
    return code, buffer.getvalue()


def main() -> int:
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        print("jsonschema is required: pip install jsonschema", file=sys.stderr)
        return 1

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    # Still worth doing -- a malformed schema would make every check below
    # vacuously pass, which is how the original step went wrong.
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)

    failures: list[str] = []
    validated = 0

    # `evidence` consumes an artifact rather than a contract, so one is made
    # here from a real run instead of being checked in.
    seed_code, seed_raw = run_json(["validate", str(FIXTURES / "apis/versioned/v1.yaml"), "--json"])
    if seed_code not in (0, 1) or not seed_raw.strip():
        print("error: could not produce an artifact for the evidence pack", file=sys.stderr)
        return 1
    (_SCRATCH / "record.json").write_text(seed_raw, encoding="utf-8")

    # Same reason, for `digest`: it consumes a sweep artifact, not a contract.
    sweep_code, sweep_raw = run_json(["sweep", str(FIXTURES), "--json"])
    if sweep_code not in (0, 1) or not sweep_raw.strip():
        print("error: could not produce a sweep artifact for `digest`", file=sys.stderr)
        return 1
    _sweep_artifact().write_text(sweep_raw, encoding="utf-8")

    for label, argv in COMMANDS:
        code, raw = run_json(argv)
        # Findings-bearing commands exit non-zero by contract; that is not a
        # failure of the artifact. Only a crash is.
        if code not in (0, 1):
            failures.append(f"{label}: exited {code}\n{raw[:400]}")
            continue
        if not raw.strip():
            failures.append(f"{label}: produced no output")
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            failures.append(f"{label}: --json output is not JSON: {exc}")
            continue

        errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.path))
        if errors:
            detail = "; ".join(
                f"{'/'.join(str(p) for p in e.path) or '<root>'}: {e.message}" for e in errors[:5]
            )
            failures.append(f"{label}: {len(errors)} schema violation(s) -- {detail}")
            continue

        validated += 1

    if failures:
        print("result-v1 validation FAILED:", file=sys.stderr)
        for failure in failures:
            print("  " + failure, file=sys.stderr)
        return 1

    print(f"ok     {validated} emitted artifacts validate against result-v1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
