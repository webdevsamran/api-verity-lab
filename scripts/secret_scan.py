"""Publication gate: fail if likely secrets appear in tracked files.

Scans the repository (excluding build/, dist/, web/node_modules, .git) for
high-confidence secret patterns: API keys, bearer tokens, AWS keys,
private keys, generic credential assignments. Exit 1 on any finding.
"""

from __future__ import annotations

import itertools
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", "node_modules", ".venv", "__pycache__", "build", "dist", "htmlcov"}
SKIP_SUFFIXES = {".lock", ".png", ".jpg", ".ico", ".woff2"}

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("aws-access-key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("private-key-block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("bearer-token", re.compile(r"Bearer\s+[A-Za-z0-9\-_.~+/]{32,}")),
    ("openai-style-key", re.compile(r"sk-[A-Za-z0-9]{20,}")),
    ("github-pat", re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}")),
    # Added after a planted-secret test walked a real-shaped Slack bot token
    # straight past the scanner: the original pattern list had no Slack, Google,
    # Stripe or npm rule at all, so those four classes were never checked.
    ("slack-token", re.compile(r"xox[baprs]-[0-9A-Za-z-]{10,}")),
    ("google-api-key", re.compile(r"AIza[0-9A-Za-z_\-]{35}")),
    ("stripe-live-key", re.compile(r"sk_live_[0-9A-Za-z]{16,}")),
    ("npm-token", re.compile(r"npm_[0-9A-Za-z]{36}")),
    (
        "credential-assignment",
        re.compile(
            r"""(?i)(api[_-]?key|secret|password|passwd|token)\s*[:=]\s*"""
            r"""["'][^"']{12,}["']"""
        ),
    ),
]

ALLOW_SUBSTRINGS = [
    "example",
    "placeholder",
    "your-api-key",
    "<key>",
    "dummy",
    "test-key",
    "xxxx",
    "redacted",
    "${",
    "{{",
]

#: Words that make up obviously-synthetic fixture credentials. A real token is
#: not spelled out of dictionary words.
_FILLER_WORDS = {
    "a",
    "acme",
    "alice",
    "an",
    "api",
    "auth",
    "bearer",
    "bob",
    "credential",
    "creds",
    "demo",
    "fake",
    "foo",
    "bar",
    "baz",
    "here",
    "key",
    "local",
    "mock",
    "my",
    "name",
    "owner",
    "pass",
    "password",
    "sample",
    "secret",
    "some",
    "stub",
    "test",
    "testing",
    "token",
    "user",
    "value",
    "admin",
}

_SEQUENTIAL_RUN = 6


#: A run must also make up this share of the value before the value is called
#: synthetic. Presence alone is not enough -- a planted-secret test showed a
#: real-shaped npm token (`npm_...WxYz0123456789`) being suppressed purely
#: because it ended in a decimal run. Requiring the run to dominate keeps
#: `sk-abcdefghijklmnop1234` (16 of 23 characters) synthetic while leaving that
#: token detected.
_SEQUENTIAL_SHARE = 0.4


def _longest_sequential_run(value: str) -> int:
    longest = run = 1
    for previous, current in itertools.pairwise(value):
        run = run + 1 if ord(current) - ord(previous) == 1 else 1
        longest = max(longest, run)
    return longest if value else 0


def _has_sequential_run(value: str) -> bool:
    """True if an ascending run dominates `value`.

    `sk-abcdefghijklmnop1234` is a fixture, but it is *high* entropy -- a
    sequential alphabet maximises character diversity, so it scores 4.44,
    above a real GitHub PAT at 4.14. Shannon entropy is the wrong instrument
    here, which measuring it is what showed. A dominant consecutive run is
    what actually marks a value synthetic.
    """
    if len(value) < _SEQUENTIAL_RUN:
        return False
    longest = _longest_sequential_run(value)
    return longest >= _SEQUENTIAL_RUN and longest >= _SEQUENTIAL_SHARE * len(value)


def _is_spelled_from_words(value: str) -> bool:
    """True if every alphabetic part is a filler word (`owner-token-123`)."""
    parts = [p for p in re.split(r"[-_. ]+", value) if p]
    alpha = [p for p in parts if p.isalpha()]
    if not alpha or len(alpha) < 2:
        return False
    return all(p.lower() in _FILLER_WORDS for p in alpha) and all(
        p.isalpha() or p.isdigit() for p in parts
    )


def looks_synthetic(snippet: str) -> bool:
    """Whether a matched snippet is a fixture rather than a live credential.

    Deliberately narrow. Both tests describe shapes a generated secret cannot
    have, so neither can hide a real key: an ascending run of six characters,
    or a value spelled entirely out of dictionary filler words.
    """
    quoted = re.findall(r"""["']([^"']{8,})["']""", snippet)
    for candidate in [*quoted, snippet]:
        if _has_sequential_run(candidate) or _is_spelled_from_words(candidate):
            return True
    return False


#: Marker that exempts a single line. Deliberately verbose so it cannot be
#: typed by accident and is trivial to grep for in review.
ALLOW_MARKER = "secret-scan: allow"


def main() -> int:
    findings: list[str] = []
    exempted = 0
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if path.suffix.lower() in SKIP_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        lines = text.splitlines()
        for name, pattern in PATTERNS:
            for match in pattern.finditer(text):
                snippet = match.group(0)
                low = snippet.lower()
                if any(a in low for a in ALLOW_SUBSTRINGS):
                    continue
                if looks_synthetic(snippet):
                    continue
                line_no = text.count(chr(10), 0, match.start()) + 1
                # Accept the marker on the matched line or either neighbour:
                # `ruff format` re-wrapped a call and moved a literal one line
                # away from its own marker, which would otherwise reopen a
                # finding for a purely cosmetic reformat.
                window = lines[max(0, line_no - 2) : line_no + 1]
                if any(ALLOW_MARKER in candidate for candidate in window):
                    # Deliberate, per line, and greppable. Used by the test that
                    # plants a real-shaped secret of every class to prove this
                    # scanner still detects them -- that file has to contain the
                    # very things the scanner looks for. Exempting `tests/`
                    # wholesale would have been the easy fix and would also hide
                    # a genuine key committed to a test.
                    exempted += 1
                    continue
                findings.append(f"{rel}:{line_no}: {name}")
    if findings:
        print("LIKELY SECRETS DETECTED — publication blocked:", file=sys.stderr)
        for f in findings:
            print(f"  {f}", file=sys.stderr)
        return 1
    suffix = f", {exempted} line(s) exempted by an explicit marker" if exempted else ""
    print(f"secret scan clean ({len(list(ROOT.rglob('*')))} paths considered{suffix})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
