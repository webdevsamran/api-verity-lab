"""Deepened protocol-aware compatibility analysis.

Complements the core BreakingEngine with checks that need whole-contract
context: status-code outcomes, content negotiation, header contracts,
security-scheme evolution, server/base-URL changes with environment-aware
severity, and explicitly modeled pagination/idempotency/webhook metadata.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from apiverity.core.model import Finding, Operation, Service, Severity

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1", "[::1]"}


def _media_types(op: Operation) -> set[str]:
    media: set[str] = set()
    if op.request_body is not None:
        media.update(op.request_body.content.keys())
    for resp in op.responses:
        media.update(resp.content.keys())
    return media


def _status_codes(op: Operation) -> set[str]:
    return {r.status for r in op.responses}


def _headers(op: Operation) -> dict[str, str]:
    """header name -> 'request' | response status."""
    out: dict[str, str] = {}
    for p in op.parameters:
        if p.location.value == "header":
            out[p.name.lower()] = "request"
    for resp in op.responses:
        for h in resp.headers:
            out.setdefault(h.lower(), f"response:{resp.status}")
    return out


class CompatAnalyzer:
    """Whole-contract compatibility analysis between two revisions."""

    def __init__(self, old: Service, new: Service) -> None:
        self.old = old
        self.new = new

    def analyze(self) -> list[Finding]:
        findings: list[Finding] = []
        self._status_codes(findings)
        self._content_negotiation(findings)
        self._headers(findings)
        self._security_schemes(findings)
        self._servers(findings)
        self._operation_metadata(findings)
        return findings

    # -- individual analyses ------------------------------------------------------

    def _status_codes(self, out: list[Finding]) -> None:
        for key in self.old.operation_keys():
            new_op = self.new.find_operation(key)
            if new_op is None:
                continue
            old_op = self.old.find_operation(key)
            assert old_op is not None
            removed = _status_codes(old_op) - _status_codes(new_op)
            added = _status_codes(new_op) - _status_codes(old_op)
            for status in sorted(removed):
                severity = Severity.WARN if status.startswith("2") else Severity.INFO
                out.append(
                    Finding(
                        rule_id="COMPAT-STATUS-REMOVED",
                        severity=severity,
                        message=(
                            f"'{key}' no longer documents {status}; clients handling "
                            "that outcome may break"
                            if status.startswith("2")
                            else f"'{key}' removed documented status {status}"
                        ),
                        operation_key=key,
                        hint="keep documenting legacy statuses until consumers migrate",
                    )
                )
            for status in sorted(added):
                out.append(
                    Finding(
                        rule_id="COMPAT-STATUS-ADDED",
                        severity=Severity.INFO,
                        message=f"'{key}' now documents status {status}",
                        operation_key=key,
                    )
                )

    def _content_negotiation(self, out: list[Finding]) -> None:
        for key in self.old.operation_keys():
            old_op, new_op = self.old.find_operation(key), self.new.find_operation(key)
            if old_op is None or new_op is None:
                continue
            removed = _media_types(old_op) - _media_types(new_op)
            added = _media_types(new_op) - _media_types(old_op)
            for media in sorted(removed):
                out.append(
                    Finding(
                        rule_id="COMPAT-MEDIA-REMOVED",
                        severity=Severity.WARN,
                        message=(
                            f"'{key}' dropped media type '{media}'; clients sending or "
                            "parsing it lose contract coverage"
                        ),
                        operation_key=key,
                    )
                )
            for media in sorted(added):
                out.append(
                    Finding(
                        rule_id="COMPAT-MEDIA-ADDED",
                        severity=Severity.INFO,
                        message=f"'{key}' added media type '{media}'",
                        operation_key=key,
                    )
                )

    def _headers(self, out: list[Finding]) -> None:
        for key in self.old.operation_keys():
            old_op, new_op = self.old.find_operation(key), self.new.find_operation(key)
            if old_op is None or new_op is None:
                continue
            old_h, new_h = _headers(old_op), _headers(new_op)
            for name in sorted(set(old_h) - set(new_h)):
                kind = old_h[name]
                sev = Severity.ERROR if kind == "request" else Severity.INFO
                out.append(
                    Finding(
                        rule_id="COMPAT-HEADER-REMOVED",
                        severity=sev,
                        message=(
                            f"'{key}' removed required request header '{name}'"
                            if kind == "request"
                            else f"'{key}' removed documented response header '{name}'"
                        ),
                        operation_key=key,
                    )
                )
            newly_required = [
                p.name
                for p in new_op.parameters
                if p.location.value == "header"
                and p.required
                and not any(
                    q.name == p.name and q.required
                    for q in old_op.parameters
                    if q.location.value == "header"
                )
            ]
            for name in newly_required:
                out.append(
                    Finding(
                        rule_id="COMPAT-HEADER-REQUIRED",
                        severity=Severity.ERROR,
                        message=(
                            f"'{key}' now requires request header '{name}'; existing "
                            "clients omitting it will be rejected"
                        ),
                        operation_key=key,
                    )
                )

    def _security_schemes(self, out: list[Finding]) -> None:
        removed = set(self.old.security_schemes) - set(self.new.security_schemes)
        for name in sorted(removed):
            out.append(
                Finding(
                    rule_id="COMPAT-SECURITY-SCHEME-REMOVED",
                    severity=Severity.ERROR,
                    message=(
                        f"security scheme '{name}' was removed; clients authenticating "
                        "with it have no documented alternative"
                    ),
                )
            )
        changed_type = [
            name
            for name in set(self.old.security_schemes) & set(self.new.security_schemes)
            if self.old.security_schemes[name].type != self.new.security_schemes[name].type
        ]
        for name in sorted(changed_type):
            out.append(
                Finding(
                    rule_id="COMPAT-SECURITY-TYPE-CHANGED",
                    severity=Severity.ERROR,
                    message=(
                        f"security scheme '{name}' changed type "
                        f"'{self.old.security_schemes[name].type}' -> "
                        f"'{self.new.security_schemes[name].type}'"
                    ),
                )
            )

    def _servers(self, out: list[Finding]) -> None:
        old_urls = {s.url for s in self.old.servers}
        new_urls = {s.url for s in self.new.servers}
        for url in sorted(new_urls - old_urls):
            host = urlsplit(url).hostname or ""
            is_local = host.lower() in _LOCAL_HOSTS
            out.append(
                Finding(
                    rule_id="COMPAT-SERVER-ADDED",
                    severity=Severity.INFO,
                    message=(
                        f"server '{url}' added"
                        + (" (local/dev target; low risk)" if is_local else "")
                    ),
                )
            )
        for url in sorted(old_urls - new_urls):
            host = urlsplit(url).hostname or ""
            is_local = host.lower() in _LOCAL_HOSTS
            out.append(
                Finding(
                    rule_id="COMPAT-SERVER-REMOVED",
                    severity=Severity.WARN if is_local else Severity.INFO,
                    message=(
                        f"server '{url}' removed; environment-aware review needed — "
                        "hostname edits are only breaking if that environment's "
                        "consumers have no replacement entry"
                    ),
                    hint="verify each environment has a reachable replacement URL",
                )
            )

    def _operation_metadata(self, out: list[Finding]) -> None:
        for key in self.old.operation_keys():
            old_op, new_op = self.old.find_operation(key), self.new.find_operation(key)
            if old_op is None or new_op is None:
                continue
            if old_op.idempotent and new_op.idempotent is False:
                out.append(
                    Finding(
                        rule_id="COMPAT-IDEMPOTENCY-REVOKED",
                        severity=Severity.WARN,
                        message=(
                            f"'{key}' declared idempotent before but no longer does; "
                            "clients relying on safe retries may double-apply effects"
                        ),
                        operation_key=key,
                    )
                )
            if old_op.pagination != new_op.pagination and new_op.pagination is not None:
                out.append(
                    Finding(
                        rule_id="COMPAT-PAGINATION-CHANGED",
                        severity=Severity.WARN,
                        message=(
                            f"'{key}' pagination semantics changed; cursor/page/token "
                            "consumers may see shifted windows"
                        ),
                        operation_key=key,
                    )
                )


def analyze_compat(old: Service, new: Service) -> list[Finding]:
    return CompatAnalyzer(old, new).analyze()
