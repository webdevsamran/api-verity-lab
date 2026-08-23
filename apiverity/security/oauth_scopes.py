"""OAuth scope coverage analysis.

Maps operations to the OAuth scopes they require and reports coverage gaps:
scopes declared in schemes but never used, operations requiring undeclared
scopes, and per-scope operation inventories.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from apiverity.core.model import Service


@dataclass
class ScopeCoverage:
    """Coverage report for OAuth scopes across a contract."""

    declared_scopes: set[str] = field(default_factory=set)
    used_scopes: dict[str, list[str]] = field(default_factory=dict)  # scope -> op keys
    undeclared_used: set[str] = field(default_factory=set)
    unused_declared: set[str] = field(default_factory=set)

    def summary(self) -> dict[str, object]:
        return {
            "declared": sorted(self.declared_scopes),
            "used": {k: sorted(v) for k, v in sorted(self.used_scopes.items())},
            "undeclared_but_used": sorted(self.undeclared_used),
            "declared_but_unused": sorted(self.unused_declared),
        }


def _declared_scopes(service: Service) -> set[str]:
    scopes: set[str] = set()
    for scheme in service.security_schemes.values():
        flow_scopes = getattr(scheme, "scopes", None)
        if isinstance(flow_scopes, (list, tuple)):
            scopes.update(str(s) for s in flow_scopes)
        elif isinstance(flow_scopes, dict):
            scopes.update(flow_scopes.keys())
    return scopes


def analyze_scope_coverage(service: Service) -> ScopeCoverage:
    declared = _declared_scopes(service)
    coverage = ScopeCoverage(declared_scopes=declared)

    requirements = list(service.global_security)
    for op in service.operations:
        reqs = op.security if op.security is not None else requirements
        for req in reqs or []:
            scheme = service.security_schemes.get(req.scheme_name)
            if scheme is None or scheme.type != "oauth2":
                continue
            for scope in req.scopes:
                coverage.used_scopes.setdefault(scope, []).append(op.key)
                if scope not in declared:
                    coverage.undeclared_used.add(scope)

    coverage.unused_declared = declared - set(coverage.used_scopes)
    return coverage
