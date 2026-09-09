"""Credentials in a response body, found without ever recording one.

Two different checks in this repository already look for secrets and neither
looks here. `scripts/secret_scan.py` reads the repository's own files;
`security/packs.py` reads a contract for secrets committed into examples. What
neither can see is a running service returning a credential to a caller — an
internal token echoed into an error message, an access key left in a debug
field, an authorization header reflected back. Those are the ones that matter,
because they are live.

The whole design constraint is that the finding must be useful without the
value. `docs/privacy.md` promises that response bodies do not reach an
artifact, `SAFETY_MODEL.md` §14 says credentials are never persisted into
results, and a scanner that reports `token=sk-live-...` to prove it found a
token has copied a live credential into a file, a log and a CI annotation. So a
finding carries the *kind* of secret, the JSON pointer it sits at, and how many
characters it was. Never the characters.

The patterns are the vendor-prefixed kinds, plus PEM blocks and JWTs, because
those are identifiable by shape rather than by entropy. Deliberately no generic
"looks random" rule: a base64 image thumbnail, a UUID, a content hash and a
session token are indistinguishable by entropy, and a check that fires on all
four is a check nobody keeps switched on.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from apiverity.core.model import Finding, Severity

#: (kind, pattern). Each matches a credential whose *shape* identifies it, so
#: a hit is a hit rather than a guess about randomness.
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("AWS access key id", re.compile(r"\b(?:AKIA|ASIA|AGPA|AIDA|AROA|ANPA)[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("Slack token", re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}\b")),
    ("Stripe secret key", re.compile(r"\b[sr]k_(?:live|test)_[A-Za-z0-9]{16,}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("OpenAI-style API key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}\b")),
    ("Anthropic API key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{24,}\b")),
    ("private key block", re.compile(r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----")),
    ("JSON Web Token", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]+")),
    ("Basic authorization header value", re.compile(r"(?i)\bBasic\s+[A-Za-z0-9+/]{16,}={0,2}")),
)

#: Response headers that should never come back to a client. `set-cookie` is
#: excluded on purpose: it is how sessions work.
_LEAKY_HEADERS = ("authorization", "proxy-authorization", "x-api-key", "x-auth-token")

#: How deep to walk a response body. A cycle cannot happen in parsed JSON, but
#: a deeply nested document should not turn a scan into a stack overflow.
_MAX_DEPTH = 24


@dataclass(frozen=True)
class Leak:
    """One credential-shaped value, described without being quoted."""

    kind: str
    pointer: str
    #: Character count. Enough to tell a truncated fingerprint from a whole
    #: key, and not enough to reconstruct either.
    length: int


def scan_text(text: str, pointer: str = "") -> list[Leak]:
    """Credential-shaped substrings in one string."""
    leaks: list[Leak] = []
    for kind, pattern in _PATTERNS:
        match = pattern.search(text)
        if match is not None:
            # One per kind per string. A body containing forty of the same key
            # is one problem, and forty findings would bury the other kinds.
            leaks.append(Leak(kind, pointer, len(match.group(0))))
    return leaks


def scan_body(body: Any, pointer: str = "", depth: int = 0) -> list[Leak]:
    """Walk a parsed JSON body, reporting the pointer each hit sits at."""
    if depth > _MAX_DEPTH:
        return []
    if isinstance(body, str):
        return scan_text(body, pointer or "/")
    if isinstance(body, dict):
        leaks: list[Leak] = []
        for key, value in body.items():
            token = str(key).replace("~", "~0").replace("/", "~1")
            leaks.extend(scan_body(value, f"{pointer}/{token}", depth + 1))
        return leaks
    if isinstance(body, list):
        leaks = []
        for index, value in enumerate(body):
            leaks.extend(scan_body(value, f"{pointer}/{index}", depth + 1))
        return leaks
    return []


def scan_headers(headers: dict[str, str] | Any) -> list[Leak]:
    """Response headers that hand a credential back to the caller."""
    leaks: list[Leak] = []
    try:
        items = list(headers.items())
    except AttributeError:  # pragma: no cover - defensive
        return leaks
    for name, value in items:
        lowered = str(name).lower()
        if lowered in _LEAKY_HEADERS and str(value).strip():
            leaks.append(Leak(f"{lowered} response header", f"header:{lowered}", len(str(value))))
        else:
            leaks.extend(
                Leak(leak.kind, f"header:{lowered}", leak.length)
                for leak in scan_text(str(value), f"header:{lowered}")
            )
    return leaks


def _unique(leaks: list[Leak]) -> list[Leak]:
    seen: dict[tuple[str, str], Leak] = {}
    for leak in leaks:
        seen.setdefault((leak.kind, leak.pointer), leak)
    return sorted(seen.values(), key=lambda leak: (leak.pointer, leak.kind))


def scan_response(
    body: Any = None,
    headers: dict[str, str] | Any = None,
    *,
    operation_key: str = "",
    source: str = "response",
) -> list[Finding]:
    """Findings for one response. The value is never part of one."""
    leaks = _unique(
        (scan_body(body) if body is not None else []) + (scan_headers(headers) if headers else [])
    )
    return [
        Finding(
            rule_id="SEC-RESPONSE-CREDENTIAL",
            severity=Severity.ERROR,
            operation_key=operation_key or None,
            message=(
                f"{source} contains what looks like a {leak.kind} at {leak.pointer} "
                f"({leak.length} characters). The value is deliberately not reported here or "
                "written to the artifact -- read it at the source, rotate it, and remove it "
                "from the response"
            ),
        )
        for leak in leaks
    ]


__all__ = ["Leak", "scan_body", "scan_headers", "scan_response", "scan_text"]
