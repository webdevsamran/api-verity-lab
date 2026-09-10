"""Severity profiles: three names instead of sixty-nine overrides.

The catalogue has sixty-nine rules and a severity for each. A team that wants
to be stricter than the default has, until now, had one route: write out an
override per rule. Nobody does that. They either accept the defaults or turn
the gate off, and the second is the outcome this whole tool exists to avoid.

So the profiles are deliberately few, and each one is a sentence a team can
agree to:

``strict``
    Anything the catalogue thinks *might* break a consumer blocks the release.
    For a contract treated as a hard commitment.

``balanced``
    The catalogue as shipped: definite breakage blocks, everything else
    reports. Named so a team can say which one they are on -- an unnamed
    default is a decision nobody made.

``advisory``
    Nothing blocks. For adopting the gate on an API that already has history,
    where a red first run gets the gate removed rather than fixed.

A profile sets **both** halves, severities and the failing threshold, because
either alone leaves one of the three names meaning nothing. `advisory` with
severities untouched is exactly `fail_on: never`; `strict` with the threshold
untouched is exactly `fail_on: warn`. Together they are three distinct
positions, and the second-order combinations still work: `advisory` with
`fail_on: warn` set explicitly means "we want to see warnings block, but we do
not yet want the catalogue's error list".

What a profile does *not* touch
-------------------------------
Only the breaking-change catalogue. Findings from the security lint, MCP
conformance, drift and the loader are not in `CATALOG` and are unaffected. A
profile that claimed to set "everything" while reaching two thirds of the rule
ids would be the worst kind of setting: one that is believed.
"""

from __future__ import annotations

from apiverity.core.model import Severity
from apiverity.rules.breaking import CATALOG

#: Profile name -> the failing threshold it implies.
_FAIL_ON = {
    "strict": "error",
    "balanced": "error",
    "advisory": "never",
}

#: Profile name -> one line, used by `apiverity rules --profiles` and by the
#: generated documentation, so the two cannot disagree.
DESCRIPTIONS = {
    "strict": (
        "Anything that might break a consumer blocks: every WARN in the catalogue "
        "is raised to ERROR."
    ),
    "balanced": ("The catalogue as shipped. Definite breakage blocks; everything else reports."),
    "advisory": ("Nothing blocks. Every finding is still reported, at its catalogue severity."),
}

PROFILES = tuple(DESCRIPTIONS)

DEFAULT_PROFILE = "balanced"


class UnknownProfileError(ValueError):
    """A profile name no profile provides."""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(
            f"unknown severity profile {name!r}; known profiles: {', '.join(PROFILES)}"
        )


def severity_overrides(name: str) -> dict[str, str]:
    """The overrides a profile implies, as rule id -> severity.

    Computed from the catalogue rather than written out, so a rule added
    tomorrow is covered by every profile the moment it exists. A hand-listed
    profile would silently omit it, and a profile that quietly does not cover a
    rule is worse than no profile: it is believed.
    """
    if name not in DESCRIPTIONS:
        raise UnknownProfileError(name)
    if name != "strict":
        # `balanced` and `advisory` both keep the catalogue's own severities.
        # `advisory` differs in the threshold, not in what each finding *is*:
        # rewriting every ERROR to WARN would make the artifact disagree with
        # the catalogue about the severity of the same change, and an artifact
        # is read long after the run that produced it.
        return {}
    return {
        rule_id: Severity.ERROR.value
        for rule_id, spec in CATALOG.items()
        if spec.severity is Severity.WARN
    }


def fail_on(name: str) -> str:
    """The failing threshold a profile implies."""
    if name not in _FAIL_ON:
        raise UnknownProfileError(name)
    return _FAIL_ON[name]


def active_severity(rule_id: str, catalog_severity: str, overrides: dict[str, str]) -> str:
    """What this rule's severity will actually be, given the overrides in force.

    Separate from `BreakingEngine.severity_for` because that needs an engine,
    and `apiverity rules` is a listing rather than a run.
    """
    return overrides.get(rule_id, catalog_severity)


def summary() -> list[tuple[str, str, str, int]]:
    """`(name, threshold, description, rules_raised)`, for docs and `rules`."""
    return [
        (name, _FAIL_ON[name], DESCRIPTIONS[name], len(severity_overrides(name)))
        for name in PROFILES
    ]


__all__ = [
    "DEFAULT_PROFILE",
    "DESCRIPTIONS",
    "PROFILES",
    "UnknownProfileError",
    "active_severity",
    "fail_on",
    "severity_overrides",
    "summary",
]
