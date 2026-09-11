"""Runtime drift detection: declared contract vs actual responses."""

from __future__ import annotations

import time
from typing import Any

import httpx
from pydantic import BaseModel, Field

from apiverity.core.model import Operation, Service
from apiverity.core.validation import validate_value
from apiverity.fuzz.generate import fill_path, generate_valid
from apiverity.security.leakage import scan_body, scan_headers


class DriftFinding(BaseModel):
    operation_key: str
    rule_id: str  # DRIFT-STATUS | DRIFT-CONTENT-TYPE | DRIFT-SCHEMA |
    # DRIFT-MISSING-FIELD | DRIFT-UNDECLARED-FIELD | DRIFT-HEADER |
    # DRIFT-UNREACHABLE | DRIFT-RESPONSE-CREDENTIAL
    severity: str = "WARN"
    message: str


class DriftReport(BaseModel):
    target: str
    findings: list[DriftFinding] = Field(default_factory=list)
    operations_checked: int = 0
    duration_ms: int = 0


def _leaks(response: httpx.Response) -> list[Any]:
    """Credential-shaped content in a live response, headers included.

    Parsing the body is best-effort: a body that is not JSON is scanned as
    text, because a token echoed into an HTML error page is still a token.
    """
    from apiverity.security.leakage import Leak, scan_text

    leaks: list[Leak] = list(scan_headers(response.headers))
    try:
        leaks.extend(scan_body(response.json()))
    except ValueError:
        leaks.extend(scan_text(response.text[:200_000], "/"))
    seen: dict[tuple[str, str], Leak] = {}
    for leak in leaks:
        seen.setdefault((leak.kind, leak.pointer), leak)
    return sorted(seen.values(), key=lambda leak: (leak.pointer, leak.kind))


def _classified_paths(schema: Any, prefix: str = "", depth: int = 0) -> set[str]:
    """Dotted paths the contract annotates with `x-data-classification`."""
    if schema is None or depth > 12:
        return set()
    out: set[str] = set()
    if getattr(schema, "data_classification", None):
        out.add(prefix)
    for name, child in (getattr(schema, "properties", None) or {}).items():
        out |= _classified_paths(child, f"{prefix}.{name}" if prefix else str(name), depth + 1)
    items = getattr(schema, "items", None)
    if items is not None:
        # An array's annotation belongs to its member, and the observed path
        # carries an index -- so the declared path is recorded without one and
        # compared against the index stripped out.
        out |= _classified_paths(items, f"{prefix}[]" if prefix else "[]", depth + 1)
    return out


def _undeclared_pii(op: Operation, resp: Any) -> list[DriftFinding]:
    """Personal data at a path the contract does not classify."""
    import re as _re

    from apiverity.security import pii

    try:
        body = resp.json()
    except Exception:
        return []

    hits = pii.scan(body)
    if not hits:
        return []

    declared: set[str] = set()
    for response in op.responses:
        if response.status in (str(resp.status_code), "default"):
            for schema in response.content.values():
                declared |= _classified_paths(schema)

    out: list[DriftFinding] = []
    seen: set[tuple[str, str]] = set()
    for hit in hits:
        # `items[3].email` is declared at `items[].email`.
        generic = _re.sub(r"\[\d+\]", "[]", hit.pointer)
        if generic in declared or hit.pointer in declared:
            continue
        key = (hit.kind, generic)
        if key in seen:
            # One finding per kind per path. A list of two hundred customers
            # is one problem, not two hundred.
            continue
        seen.add(key)
        out.append(
            DriftFinding(
                operation_key=op.key,
                rule_id="DRIFT-RESPONSE-PII",
                severity="WARN",
                message=(
                    f"the response carries what looks like a {hit.kind} at "
                    f"{hit.pointer or '(root)'} ({hit.length} characters), and the contract "
                    "does not classify that field. The value is deliberately not reported "
                    "and does not reach the artifact"
                ),
            )
        )
    return out


def detect_drift(
    service: Service,
    base_url: str,
    *,
    timeout: float = 10.0,
    forbid_undeclared_fields: bool = True,
    #: Resolved credentials for this run: `headers` from an auth profile
    #: and any `--header`, `cert` a client certificate pair for mTLS.
    #: Neither is written to an artifact -- see apiverity/traffic/auth.py.
    headers: dict[str, str] | None = None,
    cert: Any = None,
) -> DriftReport:
    started = time.monotonic()
    report = DriftReport(target=base_url)
    with httpx.Client(
        base_url=base_url, timeout=timeout, headers=headers or None, cert=cert
    ) as client:
        for op in service.operations:
            if not op.method or not op.path:
                continue
            params = {
                p.name: generate_valid(p.schema_node, __import__("random").Random(0))
                for p in op.parameters
            }
            path = fill_path(op.path, dict(params))
            query = {p.name: params[p.name] for p in op.parameters if p.location.value == "query"}
            try:
                resp = client.request(op.method, path, params=query or None)
            except httpx.HTTPError as exc:
                report.findings.append(
                    DriftFinding(
                        operation_key=op.key,
                        rule_id="DRIFT-UNREACHABLE",
                        severity="ERROR",
                        message=f"request failed: {exc}",
                    )
                )
                continue
            report.operations_checked += 1

            # Before anything about the contract. A credential coming back to
            # a caller is worth reporting whether or not the response conformed
            # to what was declared -- and a conforming response is exactly
            # where nobody looks.
            report.findings.extend(
                DriftFinding(
                    operation_key=op.key,
                    rule_id="DRIFT-RESPONSE-CREDENTIAL",
                    severity="ERROR",
                    message=(
                        f"the response contains what looks like a {leak.kind} at {leak.pointer} "
                        f"({leak.length} characters). The value is deliberately not reported and "
                        "does not reach the artifact"
                    ),
                )
                for leak in _leaks(resp)
            )

            # Personal data the contract does not say is there. Returning an
            # email from `GET /users/{id}` is the endpoint working, and a check
            # that fired on that would produce hundreds of findings per
            # contract -- which is how the useful ones get switched off with
            # it. What is worth a person's attention is the *mismatch*: the
            # document declares `nickname: string`, the service returns an
            # address. Either the contract is wrong about what it returns or
            # the service is returning something it should not.
            report.findings.extend(_undeclared_pii(op, resp))

            declared = next((r for r in op.responses if r.status == str(resp.status_code)), None)
            if declared is None:
                report.findings.append(
                    DriftFinding(
                        operation_key=op.key,
                        rule_id="DRIFT-STATUS",
                        message=f"returned status {resp.status_code} which is not declared "
                        f"(declared: {[r.status for r in op.responses]})",
                    )
                )
                continue
            ctype = resp.headers.get("content-type", "").split(";")[0]
            if declared.content and ctype and ctype not in declared.content:
                report.findings.append(
                    DriftFinding(
                        operation_key=op.key,
                        rule_id="DRIFT-CONTENT-TYPE",
                        message=f"content type '{ctype}' not declared",
                    )
                )
            schema = declared.content.get(ctype) if declared.content else None
            if schema is not None and "json" in ctype:
                try:
                    body = resp.json()
                except ValueError:
                    report.findings.append(
                        DriftFinding(
                            operation_key=op.key,
                            rule_id="DRIFT-SCHEMA",
                            message="body is not valid JSON",
                        )
                    )
                    body = None
                if body is not None:
                    # The parameter was accepted and then ignored: callers
                    # passing forbid_undeclared_fields=False still got
                    # DRIFT-UNDECLARED-FIELD findings they had asked not to
                    # have.
                    for v in validate_value(
                        schema, body, forbid_undeclared_fields=forbid_undeclared_fields
                    ):
                        rule = (
                            "DRIFT-UNDECLARED-FIELD"
                            if "undeclared field" in v
                            else (
                                "DRIFT-MISSING-FIELD" if "missing required" in v else "DRIFT-SCHEMA"
                            )
                        )
                        report.findings.append(
                            DriftFinding(operation_key=op.key, rule_id=rule, message=v)
                        )
            for header in declared.headers:
                if header.lower() not in {h.lower() for h in resp.headers}:
                    report.findings.append(
                        DriftFinding(
                            operation_key=op.key,
                            rule_id="DRIFT-HEADER",
                            message=f"declared response header '{header}' missing",
                        )
                    )
    report.duration_ms = int((time.monotonic() - started) * 1000)
    return report
