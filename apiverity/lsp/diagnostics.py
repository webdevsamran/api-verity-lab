"""Findings, turned into LSP diagnostics.

The hard part is not the mapping — it is that an editor needs a **range**, and
a finding carries a single point. A diagnostic with a zero-width range renders
as a caret between two characters that the reader has to hunt for, so the range
is widened to the line's own text.

## Linting a buffer rather than a file

An LSP is asked about what is on screen, which is usually not what is on disk.
This project has one loader, and it reads a path — so the buffer is written to
a temporary file and that is loaded.

The temporary file goes **beside the document**, not into the system temp
directory, because a contract's `$ref: ./schemas/money.yaml` resolves relative
to the file holding it. Linting a copy somewhere else would report every
sibling reference as unresolvable, and the user would see a wall of errors
caused entirely by the linter.

It is dot-prefixed and removed in a `finally`, and
`tests/unit/test_language_server.py` checks both that the directory is left
clean and that a sibling `$ref` still resolves — the second is the test that
justifies the first decision.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

#: LSP DiagnosticSeverity. INFO maps to Information rather than Hint: a hint is
#: rendered as a faint underline some themes do not draw at all, and a finding
#: nobody can see is a finding nobody has.
SEVERITY = {"ERROR": 1, "WARN": 2, "INFO": 3}

SOURCE = "apiverity"

#: Where a rule id resolves on the docs site. Sent as `codeDescription.href`, so
#: the rule id in the editor's problem list is a link.
RULE_DOCS = "https://webdevsamran.github.io/api-verity-lab/rule-catalog/"

#: Extensions the server offers to check. A contract is recognised by content,
#: not by name, but an editor asks about every file it opens and running the
#: full loader over a `.py` on every keystroke would be rude.
EXTENSIONS = (".yaml", ".yml", ".json", ".graphql", ".gql", ".graphqls", ".proto", ".wsdl")


def lintable(path: str) -> bool:
    return Path(path).suffix.lower() in EXTENSIONS


def analyze(path: str, text: str) -> tuple[list[Any], str | None]:
    """`(findings, error)` for a buffer.

    `error` is set when the document could not be loaded at all — a YAML syntax
    error while somebody is mid-edit, most often. That is reported as one
    diagnostic rather than as an empty result: an empty result means "this is
    fine", and a file that will not parse is not fine.
    """
    from apiverity.security import run_security_checks
    from apiverity.specs.loader import detect_and_load

    target = Path(path)
    directory = target.parent if target.parent.exists() else Path.cwd()
    handle, staged = tempfile.mkstemp(
        prefix=".apiverity-lsp-", suffix=target.suffix or ".yaml", dir=str(directory)
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as file:
            file.write(text)
        try:
            service, findings, _ = detect_and_load(staged)
        except Exception as exc:  # every loader failure, named rather than raised
            return [], f"{type(exc).__name__}: {exc}"
        return list(findings) + list(run_security_checks(service)), None
    finally:
        # Removed on every path. A linter that litters the directory it is
        # linting is worse than one that does not run.
        Path(staged).unlink(missing_ok=True)


def _range(finding: Any, lines: list[str]) -> dict[str, Any]:
    """The span to underline.

    A finding carries one point. Zero-width ranges render as a caret the reader
    has to hunt for, so this covers from the finding's column to the end of that
    line's text.
    """
    location = getattr(finding, "location", None)
    raw_line = int(getattr(location, "line", 0) or 0)
    raw_column = int(getattr(location, "column", 0) or 0)

    # Findings are 1-based and use 0 for "the document as a whole"; LSP is
    # 0-based throughout. A whole-document finding lands on the first line,
    # which is the closest true thing an editor can show.
    line = max(0, raw_line - 1) if raw_line else 0
    line = min(line, max(0, len(lines) - 1))
    text = lines[line] if line < len(lines) else ""
    start = max(0, raw_column - 1) if raw_column else len(text) - len(text.lstrip())
    start = min(start, len(text))
    end = len(text) if len(text) > start else start + 1
    return {
        "start": {"line": line, "character": start},
        "end": {"line": line, "character": end},
    }


def to_diagnostic(finding: Any, lines: list[str], uri: str) -> dict[str, Any]:
    severity = str(getattr(getattr(finding, "severity", None), "value", "INFO"))
    message = str(getattr(finding, "message", ""))
    hint = getattr(finding, "hint", None)
    if hint:
        # The hint is the half that says what to do about it, and an editor
        # shows the message alone in the gutter.
        message = f"{message}\n\n{hint}"

    diagnostic: dict[str, Any] = {
        "range": _range(finding, lines),
        "severity": SEVERITY.get(severity, 3),
        "code": str(getattr(finding, "rule_id", "")),
        "codeDescription": {"href": RULE_DOCS + f"#{str(getattr(finding, 'rule_id', '')).lower()}"},
        "source": SOURCE,
        "message": message,
    }
    operation = getattr(finding, "operation_key", None)
    pointer = getattr(getattr(finding, "location", None), "pointer", None)
    if operation or pointer:
        diagnostic["data"] = {"operation": operation, "pointer": pointer}

    second = getattr(finding, "new_location", None)
    if second is not None and int(getattr(second, "line", None) or 0):
        # A finding naming two places -- the old and the new -- is unreadable
        # when the editor shows only one of them.
        diagnostic["relatedInformation"] = [
            {
                "location": {"uri": uri, "range": _range(_Point(second), lines)},
                "message": "the other location this finding names",
            }
        ]
    return diagnostic


class _Point:
    """Adapts a bare location to what `_range` reads."""

    def __init__(self, location: Any) -> None:
        self.location = location


def diagnostics(path: str, text: str, uri: str) -> list[dict[str, Any]]:
    """Everything to publish for one buffer."""
    lines = text.split("\n")
    findings, failure = analyze(path, text)
    if failure is not None:
        return [
            {
                "range": {
                    "start": {"line": 0, "character": 0},
                    "end": {"line": 0, "character": len(lines[0]) if lines else 1},
                },
                "severity": 1,
                "code": "PARSE",
                "source": SOURCE,
                "message": f"this document could not be read as a contract. {failure}",
            }
        ]
    return [to_diagnostic(finding, lines, uri) for finding in findings]


__all__ = [
    "EXTENSIONS",
    "RULE_DOCS",
    "SEVERITY",
    "SOURCE",
    "analyze",
    "diagnostics",
    "lintable",
    "to_diagnostic",
]
