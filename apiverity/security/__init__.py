"""Defensive security contract checks (static, declarative).

These checks analyze the *contract* for missing/inconsistent security
declarations and unsafe defaults. They do NOT generate exploit payloads
or perform offensive testing — see SECURITY.md.
"""

from apiverity.security.checks import run_security_checks

__all__ = ["run_security_checks"]
