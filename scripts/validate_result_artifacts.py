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
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "schemas" / "result-v1.schema.json"
FIXTURES = ROOT / "fixtures"

sys.path.insert(0, str(ROOT))

#: (label, argv). Each is a command a user runs and whose output a CI gate or
#: the frontend consumes, so each must satisfy the published schema.
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
