"""Regenerate the README's example blocks from real runs.

The README used to show hand-written CLI output. Every identifier in it was
wrong: it printed `CHG-OPERATION-REMOVED-1` where the code emits
`CHG-OPERATION_REMOVED-1` (change ids are built from `kind.value.upper()`, and
every ChangeKind value is snake_case, so a hyphen there is not producible), and
`DRIFT-FIELD` where the real literal is `DRIFT-MISSING-FIELD`. A reader who
copied a rule id out of the README and grepped for it found nothing.

So the examples are no longer written by hand. This script runs the real
commands against the bundled fixtures, captures stdout verbatim, and splices it
between markers in the README. `--check` re-runs the capture and fails if the
committed README differs, which is what stops it drifting again.

Everything runs against `fixtures/`, with the mock served in-process, so this
needs no network and no external service -- it can run in CI on every push.

    python scripts/capture_readme_examples.py            # rewrite the README
    python scripts/capture_readme_examples.py --check    # verify, exit 1 on drift
"""

from __future__ import annotations

import argparse
import contextlib
import io
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
FIXTURES = ROOT / "fixtures"

sys.path.insert(0, str(ROOT))

#: Each block is (marker name, shell command as shown to the reader, producer).
#: The command string is displayed after the `$` prompt; it is not what runs,
#: because running the CLI as a subprocess would need an installed console
#: script. The producer below performs the identical work in-process, and the
#: test suite asserts the two agree.
MARK_OPEN = "<!-- capture:{name} -->"
MARK_CLOSE = "<!-- /capture:{name} -->"


def _run_diff() -> str:
    from apiverity.cli.commands.common import _emit
    from apiverity.diff.engine import diff_services
    from apiverity.specs.loader import detect_and_load

    old, _, _ = detect_and_load(str(FIXTURES / "apis/versioned/v1.yaml"))
    new, _, _ = detect_and_load(str(FIXTURES / "apis/versioned/v2.yaml"))
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        _emit(
            {
                "tool": "apiverity",
                "command": "diff",
                "old_version": old.version,
                "new_version": new.version,
                "changes": diff_services(old, new),
            },
            False,
        )
    return buffer.getvalue()


def _run_breaking() -> str:
    from apiverity.cli.commands.common import _emit
    from apiverity.diff.engine import diff_services
    from apiverity.rules.breaking import evaluate_breaking
    from apiverity.specs.loader import detect_and_load

    old, _, _ = detect_and_load(str(FIXTURES / "apis/versioned/v1.yaml"))
    new, _, _ = detect_and_load(str(FIXTURES / "apis/versioned/v2.yaml"))
    changes = diff_services(old, new)
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        _emit(
            {
                "tool": "apiverity",
                "command": "breaking",
                "findings": evaluate_breaking(changes),
            },
            False,
        )
    return buffer.getvalue()


def _run_drift() -> str:
    """Drift, against the CRUD mock served in-process.

    The drift fixture declares a contract the CRUD mock deliberately does not
    satisfy, so this produces genuine findings without a network call -- the
    same arrangement `scripts/e2e.py` uses.
    """
    from apiverity.cli.commands.common import _emit
    from apiverity.mock import MockServer
    from apiverity.runtime.drift import detect_drift
    from apiverity.specs.loader import detect_and_load

    crud, _, _ = detect_and_load(str(FIXTURES / "apis/crud/openapi.yaml"))
    drift_spec, _, _ = detect_and_load(str(FIXTURES / "apis/drift/openapi.yaml"))
    with MockServer(crud, port=8099) as mock:
        report = detect_drift(drift_spec, mock.base_url)
    # The port is an implementation detail of this capture; show the address a
    # reader would actually use rather than the ephemeral fixture one.
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        _emit({"tool": "apiverity", "command": "drift", "findings": report.findings}, False)
    return buffer.getvalue().replace(mock.base_url, "http://localhost:8080")


BLOCKS = {
    "diff": ("apiverity diff v1.yaml v2.yaml", _run_diff),
    "breaking": ("apiverity breaking v1.yaml v2.yaml", _run_breaking),
    "drift": ("apiverity drift openapi.yaml --base-url http://localhost:8080", _run_drift),
}


#: Provenance keys `enrich()` appends to every payload. Real output, but
#: eight lines of `contract_hash` and `seed: None` after every example buries
#: the thing the example is about. They are dropped from the README block and
#: replaced by one line saying so -- trimmed openly, not silently omitted.
PROVENANCE_KEYS = (
    "tool_version",
    "result_schema_version",
    "contract_hash",
    "protocol_version",
    "target",
    "seed",
    "duration_ms",
    "redaction",
)


def _strip_provenance(output: str) -> str:
    kept = [
        line
        for line in output.splitlines()
        if not any(line.startswith(key + ":") for key in PROVENANCE_KEYS)
    ]
    return "\n".join(kept).rstrip()


def render(name: str) -> str:
    command, producer = BLOCKS[name]
    output = _strip_provenance(producer().rstrip("\n"))
    footer = "# ...followed by the provenance footer every artifact carries"
    return f"```console\n$ {command}\n{output}\n{footer}\n```"


def splice(text: str) -> str:
    for name in BLOCKS:
        open_mark = MARK_OPEN.format(name=name)
        close_mark = MARK_CLOSE.format(name=name)
        if open_mark not in text or close_mark not in text:
            raise SystemExit(
                f"README is missing the {open_mark} / {close_mark} markers. "
                "Add them around the example block before running this script."
            )
        pattern = re.compile(re.escape(open_mark) + r".*?" + re.escape(close_mark), re.S)
        text = pattern.sub(f"{open_mark}\n{render(name)}\n{close_mark}", text)
    return text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the committed README matches a real run; exit 1 if not",
    )
    args = parser.parse_args()

    current = README.read_text(encoding="utf-8")
    updated = splice(current)

    if args.check:
        if current == updated:
            print(f"ok     README examples match a real run ({len(BLOCKS)} blocks)")
            return 0
        print(
            "README examples no longer match what the code produces.\n"
            "Run: python scripts/capture_readme_examples.py",
            file=sys.stderr,
        )
        import difflib

        diff = difflib.unified_diff(
            current.splitlines(),
            updated.splitlines(),
            fromfile="README.md (committed)",
            tofile="README.md (real run)",
            lineterm="",
        )
        for line in list(diff)[:60]:
            print(line, file=sys.stderr)
        return 1

    README.write_text(updated, encoding="utf-8", newline="\n")
    print(f"wrote  README.md ({len(BLOCKS)} example blocks captured from real runs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
