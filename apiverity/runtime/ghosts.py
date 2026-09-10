"""Routes the contract says are gone, that the server still answers.

Every other check in this project asks whether the server does what the
contract says. This asks the opposite question: does the server still do
something the contract stopped saying?

A removed endpoint is removed from the document in one pull request and from
the deployment in another, and the second one is the one that gets forgotten.
Nothing fails: the docs are correct, the tests pass, the gate is green, and the
route keeps answering to anyone who remembers the URL. It is the shape of a
long tail of real incidents -- an old admin path, a v1 that was "retired", a
debug handler -- and almost nothing looks for it, because looking requires
comparing against something that is deliberately absent.

Where the candidates come from
------------------------------
Two sources, both evidence rather than guesswork. `--was old.yaml` supplies the
operations a previous version declared and this one does not. A HAR corpus
supplies paths that were really requested and that the contract does not match
-- `corpus_drift` already computes them as `unmatched_paths` and threw them
away.

Nothing is invented. This never enumerates likely paths, because a tool that
guesses URLs against a host is a scanner, and `SAFETY_MODEL.md` §1 is explicit
targets only.

Safe methods only
-----------------
A removed `DELETE /users/{id}` cannot be probed by sending a DELETE. The
candidate is reported as unprobed, with the method that would have been needed,
rather than being silently dropped -- an audit that quietly skips the
destructive half of its input is worse than one that says so.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field

from apiverity.core.model import Service
from apiverity.fuzz.generate import fill_path, generate_valid

#: Methods that read. Anything else is a write and is not sent.
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")

#: Statuses that mean the route really is gone. 404 is absent; 410 is
#: deliberately absent, which is better and worth distinguishing.
GONE_STATUSES = (404, 410)

#: The path exists and the method does not. Still evidence the route was never
#: withdrawn.
METHOD_MISMATCH = 405


@dataclass(frozen=True)
class Candidate:
    """A route worth asking about, and why we are asking."""

    method: str
    path: str
    #: "removed from <spec>" or "seen in <corpus>".
    source: str

    @property
    def key(self) -> str:
        return f"{self.method} {self.path}"


class GhostFinding(BaseModel):
    rule_id: str
    severity: str = "WARN"
    message: str
    operation_key: str | None = None
    status: int | None = None
    source: str | None = None


class GhostReport(BaseModel):
    target: str
    findings: list[GhostFinding] = Field(default_factory=list)
    candidates: int = 0
    probed: int = 0
    duration_ms: int = 0


def removed_operations(old: Service, new: Service) -> list[Candidate]:
    """Operations the previous contract declared and this one does not."""
    current = {op.key for op in new.operations}
    label = old.source_file or old.title
    return [
        Candidate(
            method=(op.method or "").upper(), path=op.path or "", source=f"removed from {label}"
        )
        for op in old.operations
        if op.method and op.path and op.key not in current
    ]


def unmatched_paths(paths: list[str], source: str) -> list[Candidate]:
    """Paths a corpus recorded that the contract does not declare.

    `corpus_drift` labels these `METHOD /path`; anything else is passed
    through as a GET, which is the only assumption made anywhere in here.
    """
    out: list[Candidate] = []
    for label in paths:
        method, _, path = label.partition(" ")
        if not path:
            method, path = "GET", label
        out.append(Candidate(method=method.upper(), path=path, source=f"seen in {source}"))
    return out


def _concrete(candidate: Candidate, old: Service | None) -> str:
    """A templated path with its parameters filled, deterministically."""
    if "{" not in candidate.path:
        return candidate.path
    operation = None
    if old is not None:
        operation = next(
            (op for op in old.operations if op.path == candidate.path and op.method), None
        )
    if operation is None:
        return candidate.path
    import random

    values = {
        p.name: generate_valid(p.schema_node, random.Random(0))
        for p in operation.parameters
        if p.location.value == "path"
    }
    return fill_path(candidate.path, values)


def audit(
    candidates: list[Candidate],
    base_url: str,
    *,
    old: Service | None = None,
    timeout: float = 10.0,
    #: Resolved credentials for this run: `headers` from an auth profile and
    #: any `--header`, `cert` a client certificate pair for mTLS. Neither is
    #: written to an artifact -- see apiverity/traffic/auth.py.
    headers: dict[str, str] | None = None,
    cert: Any = None,
    client: Any = None,
) -> GhostReport:
    """Ask a live service about routes its contract no longer declares."""
    started = time.monotonic()
    report = GhostReport(target=base_url, candidates=len(candidates))

    unsafe = [c for c in candidates if c.method not in SAFE_METHODS]
    for candidate in unsafe:
        report.findings.append(
            GhostFinding(
                rule_id="GHOST-NOT-PROBED",
                severity="INFO",
                operation_key=candidate.key,
                source=candidate.source,
                message=(
                    f"{candidate.key} was not probed: {candidate.method} is a write, and this "
                    "audit sends only safe methods. Check it by hand, or from a request log"
                ),
            )
        )

    probeable = [c for c in candidates if c.method in SAFE_METHODS]
    if not probeable:
        report.duration_ms = int((time.monotonic() - started) * 1000)
        return report

    owns_client = client is None
    http = client or httpx.Client(
        base_url=base_url,
        timeout=timeout,
        follow_redirects=False,
        headers=headers or None,
        cert=cert,
    )
    try:
        for candidate in probeable:
            path = _concrete(candidate, old)
            try:
                response = http.request(candidate.method, path)
            except httpx.HTTPError as exc:
                report.findings.append(
                    GhostFinding(
                        rule_id="GHOST-UNREACHABLE",
                        severity="INFO",
                        operation_key=candidate.key,
                        source=candidate.source,
                        message=(
                            f"{candidate.key} could not be probed ({exc}); this run establishes "
                            "nothing about whether it is still served"
                        ),
                    )
                )
                continue
            report.probed += 1
            status = response.status_code

            if status in GONE_STATUSES:
                report.findings.append(
                    GhostFinding(
                        rule_id="GHOST-GONE",
                        severity="INFO",
                        operation_key=candidate.key,
                        source=candidate.source,
                        status=status,
                        message=(
                            f"{candidate.key} returned {status}; the contract and the deployment "
                            "agree that it is gone"
                        ),
                    )
                )
            elif status == METHOD_MISMATCH:
                report.findings.append(
                    GhostFinding(
                        rule_id="GHOST-PATH-ALIVE",
                        severity="WARN",
                        operation_key=candidate.key,
                        source=candidate.source,
                        status=status,
                        message=(
                            f"{path} returned {status} for {candidate.method}: the method is "
                            "gone and the path is not. Something is still routed there"
                        ),
                    )
                )
            else:
                report.findings.append(
                    GhostFinding(
                        rule_id="GHOST-ROUTE",
                        severity="ERROR",
                        operation_key=candidate.key,
                        source=candidate.source,
                        status=status,
                        message=(
                            f"{candidate.key} answered {status} and no contract declares it "
                            f"({candidate.source}). It was removed from the document and not "
                            "from the deployment"
                        ),
                    )
                )
    finally:
        if owns_client:
            http.close()

    report.duration_ms = int((time.monotonic() - started) * 1000)
    return report


def target_host(base_url: str) -> str:
    return urlparse(base_url).hostname or ""


__all__ = [
    "GONE_STATUSES",
    "SAFE_METHODS",
    "Candidate",
    "GhostFinding",
    "GhostReport",
    "audit",
    "removed_operations",
    "unmatched_paths",
]
