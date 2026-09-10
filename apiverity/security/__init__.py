"""Defensive security contract checks (static, declarative).

These checks analyze the *contract* for missing/inconsistent security
declarations and unsafe defaults. They do NOT generate exploit payloads
or perform offensive testing — see SECURITY.md.
"""

from apiverity.security.checks import run_security_checks
from apiverity.security.hardening import run_hardening_checks
from apiverity.security.oauth_scopes import analyze_scope_coverage

__all__ = ["analyze_scope_coverage", "run_hardening_checks", "run_security_checks"]
