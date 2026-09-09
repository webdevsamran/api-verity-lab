"""Semantic-versioning policy: validate a bump, and advise one.

Compares the contract's declared version transition against the severity
of detected changes:

- breaking changes (ERROR findings) require a MAJOR bump
- risky changes (WARN) require at least a MINOR bump (configurable)
- any material change with an unchanged version is flagged
- version decreases are always flagged

It also *advises*. The policy has always held every input needed to say what
the next version should be and only ever said whether the one you picked was
wrong -- which is the difference between a linter that tells you the rule you
broke and one that tells you what to write instead.

`suggest_bump` is deliberately separate from `evaluate` and returns the rule
ids that forced its answer, so a recommendation can be audited rather than
trusted.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from packaging.version import InvalidVersion, Version

from apiverity.core.model import Change, Finding, Severity


def _parse(version: str) -> Version | None:
    try:
        return Version(version)
    except InvalidVersion:
        return None


@dataclass(frozen=True)
class VersionAdvice:
    """What the next version should be, and what forced that answer."""

    #: "major" | "minor" | "patch" | "none"
    required_bump: str
    #: The version this implies, or None when the current one cannot be parsed.
    suggested_version: str | None
    #: Rule ids and finding severities behind the recommendation. A suggestion
    #: with nothing behind it is an opinion, not a verdict.
    reasons: list[str] = field(default_factory=list)
    #: True when the declared new version already satisfies the recommendation.
    satisfied: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "required_bump": self.required_bump,
            "suggested_version": self.suggested_version,
            "reasons": self.reasons,
            "satisfied": self.satisfied,
        }


def _bump(version: Version, kind: str) -> str:
    """Apply a bump to a parsed version.

    Pre-1.0 is not special-cased into "anything goes". SemVer says 0.x makes no
    stability promise, but a project that publishes 0.4.0 and breaks its
    consumers has still broken them, and this tool's job is to say so. The
    recommendation is the same shape at any version; what changes is only how
    seriously a consumer takes it.
    """
    if kind == "major":
        return f"{version.major + 1}.0.0"
    if kind == "minor":
        return f"{version.major}.{version.minor + 1}.0"
    if kind == "patch":
        return f"{version.major}.{version.minor}.{version.micro + 1}"
    return str(version)


def suggest_bump(
    current_version: str,
    findings: list[Finding],
    changes: list[Change],
    *,
    require_minor_for_warnings: bool = False,
    declared_new_version: str | None = None,
) -> VersionAdvice:
    """Recommend the next version from the changes that were actually found.

    `current_version` is the *old* contract's version -- the released one the
    recommendation moves away from.
    """
    breaking = sorted({f.rule_id for f in findings if f.severity is Severity.ERROR})
    risky = sorted({f.rule_id for f in findings if f.severity is Severity.WARN})

    if breaking:
        kind = "major"
        reasons = [f"{rule} (ERROR)" for rule in breaking]
    elif risky and require_minor_for_warnings:
        kind = "minor"
        reasons = [f"{rule} (WARN)" for rule in risky]
    elif changes or findings:
        # Something moved. Additive-only change is a minor under SemVer; a
        # change set with no findings at all is documentation-shaped, so patch.
        kind = "minor" if risky or _is_additive(changes) else "patch"
        reasons = (
            [f"{rule} (WARN)" for rule in risky]
            if risky
            else [f"{len(changes)} change(s) with no breaking finding"]
        )
    else:
        return VersionAdvice("none", current_version or None, [], satisfied=True)

    parsed = _parse(current_version)
    if parsed is None:
        # No fabricated version. The bump is still knowable from the findings;
        # the number it lands on is not.
        return VersionAdvice(
            kind, None, [*reasons, f"current version {current_version!r} is unparseable"]
        )

    suggested = _bump(parsed, kind)
    satisfied = False
    if declared_new_version is not None:
        declared = _parse(declared_new_version)
        if declared is not None:
            satisfied = _satisfies(parsed, declared, kind)
    return VersionAdvice(kind, suggested, reasons, satisfied=satisfied)


def _is_additive(changes: list[Change]) -> bool:
    """Whether anything was added, which SemVer makes a minor."""
    return any("_added" in change.kind.value for change in changes)


def _satisfies(old: Version, declared: Version, kind: str) -> bool:
    if kind == "major":
        return declared.major > old.major
    if kind == "minor":
        return declared.major > old.major or declared.minor > old.minor
    if kind == "patch":
        return declared > old
    return True


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
