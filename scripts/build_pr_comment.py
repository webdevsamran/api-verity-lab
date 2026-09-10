"""Render one pull-request comment from a directory of `result-v1` artifacts.

Used by `action.yml`. A gate that only blocks gets switched off, so the comment
leads with the non-breaking route to the same change and treats the objection
as the evidence for it.

Several contracts can change in one pull request, and posting a comment per
contract is the same mistake as posting one per push. They are merged into a
single body here, ordered worst-first, so the reviewer reads one thing.

    python scripts/build_pr_comment.py <artifacts-dir> [output-file]

Writes the comment to `output-file` (default stdout) in UTF-8, explicitly:
`print` on a Windows runner encodes with the console code page, and a contract
titled outside cp1252 exited 4 that way once already.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apiverity.reports.renderers import PR_MARKER, pr_comment

#: Worst verdict wins the heading. A pull request with one blocked contract and
#: five clear ones is blocked.
_RANK = {"blocked": 2, "review": 1, "clear": 0}


def _load(artifacts: Path) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for path in sorted(artifacts.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            # Same rule as `count_findings.py`: a malformed artifact is a tool
            # failure, and a comment that quietly omits it would report a
            # cleaner pull request than the run established.
            raise SystemExit(f"{path}: unreadable result artifact ({exc})") from exc
        if isinstance(payload, dict):
            payloads.append(payload)
    return payloads


def build(artifacts: Path) -> str:
    """One comment body for every artifact in the directory."""
    payloads = _load(artifacts)
    if not payloads:
        # Distinguishable from "everything passed", which is what a gate that
        # examined nothing must never claim.
        return (
            f"{PR_MARKER}\n## apiverity\n\n"
            "No contract artifacts were produced by this run, so nothing was compared."
        )

    if len(payloads) == 1:
        return pr_comment(payloads[0])

    from apiverity.reports.renderers import _findings, _pr_verdict

    ranked = sorted(
        payloads,
        key=lambda p: (-_RANK[_pr_verdict(_findings(p))], str(p.get("new_spec", ""))),
    )
    parts = [pr_comment(ranked[0])]
    for payload in ranked[1:]:
        # The marker belongs to the comment, not to each section: a workflow
        # searching for two of them finds neither reliably.
        body = pr_comment(payload).replace(PR_MARKER + "\n", "", 1)
        parts.append(body)
    return "\n\n---\n\n".join(parts)


def main(argv: list[str]) -> int:
    if not 2 <= len(argv) <= 3:
        raise SystemExit(f"usage: {argv[0]} <artifacts-dir> [output-file]")
    body = build(Path(argv[1]))
    if len(argv) == 3:
        Path(argv[2]).write_text(body, encoding="utf-8")
    else:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        sys.stdout.write(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
