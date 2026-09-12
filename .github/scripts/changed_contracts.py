"""Which of the changed files the contract gate can actually check.

The gate collects every changed `.yaml`/`.yml`/`.json` under a small list of
directories and hands each one to `apiverity validate`. Those directories hold
two kinds of file: standalone contracts, and the `$ref` fragments those
contracts point at -- `shared/error.yaml`, `schemas/order.yaml`, and the rest.

A fragment has no `openapi:` key and no `type Query`, so nothing detects it as
a contract and `validate` exits 2 with "not an API contract". The gate read
that as a failing contract and blocked the merge over a file that was never
meant to be validated on its own, and is already validated through the document
that references it.

Filtering them out quietly would be the wrong fix -- a gate that drops what it
cannot read is exactly the shape this repository keeps finding and removing --
so every skip is printed, with the reason, to stderr where the job log keeps
it. A file that fails to load for any other reason is **not** skipped: it is
passed through to the gate, which is where it should fail loudly.

    python .github/scripts/changed_contracts.py path [path ...]

Contracts go to stdout, one per line, for the shell to iterate.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from apiverity.specs.loader import detect_and_load


def is_contract(path: str) -> tuple[bool, str]:
    """Whether `path` is a contract, and why not when it is not.

    Detection is the loader's own, rather than a second guess at it here: a
    filter that decides what a contract looks like by its own rules is a filter
    that disagrees with the tool the moment a format is added.
    """
    try:
        detect_and_load(path)
    except Exception as exc:
        message = str(exc)
        if "not an API contract" in message or "recognized format" in message:
            return (
                False,
                "not a standalone contract; it is checked through the document that $refs it",
            )
        # Anything else -- unreadable, malformed, a format that failed to parse
        # -- is a real problem and belongs in front of the gate, not hidden by
        # this script.
        return True, ""
    return True, ""


def main(argv: list[str]) -> int:
    for path in argv:
        if not Path(path).is_file():
            continue
        keep, reason = is_contract(path)
        if keep:
            print(path)
        else:
            print(f"skipped {path}: {reason}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
