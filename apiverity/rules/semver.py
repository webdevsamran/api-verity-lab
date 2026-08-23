"""Semantic-versioning policy checks.

Compares the contract's declared version transition against the severity
of detected changes:

- breaking changes (ERROR findings) require a MAJOR bump
- risky changes (WARN) require at least a MINOR bump (configurable)
- any material change with an unchanged version is flagged
- version decreases are always flagged
"""

from __future__ import annotations

from packaging.version import InvalidVersion, Version

from apiverity.core.model import Change, Finding, Severity


def _parse(version: str) -> Version | None:
    try:
        return Version(version)
    except InvalidVersion:
        return None


class SemverPolicy:
    """Evaluates a version transition against detected change severity."""

    def __init__(
        self,
        old_version: str,
        new_version: str,
        *,
        require_minor_for_warnings: bool = False,
    ) -> None:
        self.old_version = old_version
        self.new_version = new_version
        self.require_minor_for_warnings = require_minor_for_warnings
        self._old = _parse(old_version)
        self._new = _parse(new_version)

    def evaluate(self, findings: list[Finding], changes: list[Change]) -> list[Finding]:
        out: list[Finding] = []
        has_breaking = any(f.severity == Severity.ERROR for f in findings)
        has_risky = any(f.severity == Severity.WARN for f in findings)
        has_material = bool(findings) or bool(changes)

        if self._old is None or self._new is None:
            out.append(
                Finding(
                    rule_id="SEMVER-UNPARSEABLE",
                    severity=Severity.WARN,
                    message=(
                        f"cannot parse versions '{self.old_version}' -> "
                        f"'{self.new_version}' for semver policy"
                    ),
                )
            )
            return out

        if self._new < self._old:
            out.append(
                Finding(
                    rule_id="SEMVER-DECREASE",
                    severity=Severity.ERROR,
                    message=(
                        f"version decreased '{self.old_version}' -> '{self.new_version}'; "
                        "published versions must never decrease"
                    ),
                )
            )
            return out

        major_bump = self._new.major > self._old.major
        minor_bump = self._new.minor > self._old.minor
        any_bump = self._new > self._old

        if has_breaking and not major_bump:
            out.append(
                Finding(
                    rule_id="SEMVER-MAJOR-REQUIRED",
                    severity=Severity.ERROR,
                    message=(
                        "breaking changes detected but version only moved "
                        f"'{self.old_version}' -> '{self.new_version}'; "
                        "a MAJOR bump is required"
                    ),
                )
            )
        elif self.require_minor_for_warnings and has_risky and not (minor_bump or major_bump):
            out.append(
                Finding(
                    rule_id="SEMVER-MINOR-REQUIRED",
                    severity=Severity.WARN,
                    message=(
                        "risky (WARN) changes detected without a MINOR bump "
                        f"('{self.old_version}' -> '{self.new_version}')"
                    ),
                )
            )
        elif has_material and not any_bump:
            out.append(
                Finding(
                    rule_id="SEMVER-NO-BUMP",
                    severity=Severity.WARN,
                    message=(
                        "material contract changes detected but the version "
                        f"stayed at '{self.new_version}'"
                    ),
                )
            )

        return out
