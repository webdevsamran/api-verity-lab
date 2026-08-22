"""Built-in plugin registrations for every entry-point group (§25).

Each attribute referenced from pyproject entry points is a zero-arg
factory so ``PluginRegistry.instances()`` works uniformly.
"""
from __future__ import annotations

from typing import Any


def core_rules() -> dict[str, Any]:
    """The built-in breaking-rules catalog."""
    from apiverity.rules.breaking import CATALOG

    return dict(CATALOG)


def security_checks() -> Any:
    """The built-in defensive security check runner."""
    from apiverity.security import run_security_checks

    return run_security_checks


def schema_case_generator() -> Any:
    """The built-in deterministic schema-driven case generator."""
    from apiverity.fuzz.runner import build_cases

    return build_cases


def report_exporters() -> dict[str, Any]:
    """Built-in report renderers keyed by format name."""
    from apiverity.reports.renderers import RENDERERS

    return dict(RENDERERS)


def httpx_transport() -> Any:
    """The built-in HTTP transport (httpx client factory)."""
    import httpx

    def make_client(**kwargs: Any) -> httpx.Client:
        kwargs.setdefault("follow_redirects", False)
        return httpx.Client(**kwargs)

    return make_client