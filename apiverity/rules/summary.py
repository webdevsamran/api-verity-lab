"""Plain-English summaries: what changed, who it affects, what to do.

`changelog` renders every change, grouped by operation. That is the right thing
for a release note and the wrong thing for a pull request description, where
the reader wants three sentences and a decision.

Deterministic templates, no model call. A summary that a language model writes
is a summary nobody can diff, nobody can test, and nobody can run in CI without
a network egress conversation — and the structured diff already contains
everything the sentences need. The templates are dull on purpose: this is
release-note prose, and prose that surprises the reader is a defect.

The shape is always the same three parts, because a reader skimming twenty pull
requests learns the shape once:

    <one line: is this safe to merge>
    <what changed, grouped by kind and counted>
    <what to do about it>
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from apiverity.core.model import Change, Finding, Severity

#: Rule id prefix -> how to describe that family to someone who is not holding
#: the rule catalogue. Ordered longest-first so the more specific prefix wins.
_PHRASES: tuple[tuple[str, str], ...] = (
    ("BRK-MCP-TOOL-DESCRIPTION", "tool descriptions changed, which is what an agent routes on"),
    ("BRK-MCP-OUTPUT-SCHEMA", "a tool's declared result shape changed"),
    ("BRK-MCP-TOOL-RENAME", "a tool may have been renamed"),
    ("BRK-MCP-MANIFEST-TRUNCATED", "the manifest was only partially captured"),
    ("BRK-MCP-", "tool safety annotations changed"),
    ("BRK-OP-REMOVED", "operations were removed"),
    ("BRK-RPC-REMOVED", "operations were removed"),
    ("BRK-OP-ADDED", "operations were added"),
    ("BRK-RPC-ADDED", "operations were added"),
    ("BRK-PARAM-ADDED-REQUIRED", "new required parameters were added"),
    ("BRK-PARAM-REQUIRED", "optional parameters became required"),
    ("BRK-PARAM-REMOVED", "parameters were removed"),
    ("BRK-PARAM-TYPE", "parameter types changed"),
    ("BRK-REQ-FIELD-BECAME-REQUIRED", "request fields became required"),
    ("BRK-REQ-FIELD-REMOVED", "request fields were removed"),
    ("BRK-REQ-BODY-REQUIRED", "a request body became required"),
    ("BRK-RESP-FIELD-REMOVED", "response fields were removed"),
    ("BRK-RESP-FIELD-OPTIONALIZED", "response fields are no longer guaranteed"),
    ("BRK-RESP-STATUS-REMOVED", "declared response statuses were removed"),
    ("BRK-CONSTRAINT-TIGHTENED", "constraints were tightened, so previously valid input now fails"),
    ("BRK-ENUM-NARROWED-REQUEST", "accepted enum values were removed"),
    ("BRK-ENUM-NARROWED-RESPONSE", "returned enum values were removed"),
    ("BRK-SECURITY-", "authentication requirements changed"),
    ("BRK-DEPRECATION-ADDED", "operations were deprecated"),
    ("BRK-MEDIA-TYPE", "media types changed"),
    ("SEMVER-", "the version bump does not match the changes"),
)


@dataclass
class Summary:
    """A rendered summary and the parts it was built from."""

    verdict: str
    what_changed: list[str] = field(default_factory=list)
    what_to_do: list[str] = field(default_factory=list)
    errors: int = 0
    warnings: int = 0
    change_count: int = 0

    def as_markdown(self) -> str:
        lines = [self.verdict, ""]
        if self.what_changed:
            lines.append("**What changed**")
            lines.append("")
            lines.extend(f"- {item}" for item in self.what_changed)
            lines.append("")
        if self.what_to_do:
            lines.append("**What to do**")
            lines.append("")
            lines.extend(f"- {item}" for item in self.what_to_do)
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    def as_dict(self) -> dict[str, object]:
        return {
            "verdict": self.verdict,
            "what_changed": self.what_changed,
            "what_to_do": self.what_to_do,
            "errors": self.errors,
            "warnings": self.warnings,
            "change_count": self.change_count,
        }


def _phrase_for(rule_id: str) -> str:
    for prefix, phrase in _PHRASES:
        if rule_id.startswith(prefix):
            return phrase
    # No invented phrasing for a rule this table does not know. The id is
    # accurate and the reader can look it up with `apiverity explain`.
    return f"{rule_id} fired"


def _sentence_case(text: str) -> str:
    """Upper-case the first character only.

    `str.capitalize()` lower-cases the rest, which turned the fallback phrase
    "BRK-SOMETHING-NEW fired" into "Brk-something-new fired" -- destroying the
    rule id the next sentence tells the reader to look up.
    """
    return text[:1].upper() + text[1:]


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    return singular if count == 1 else (plural or f"{singular}s")


def summarize(
    changes: list[Change],
    findings: list[Finding],
    *,
    old_version: str | None = None,
    new_version: str | None = None,
    suggested_version: str | None = None,
    consumers: list[str] | None = None,
) -> Summary:
    """Build the summary from the structured diff. No model, no network."""
    errors = [f for f in findings if f.severity is Severity.ERROR]
    warnings = [f for f in findings if f.severity is Severity.WARN]

    versions = ""
    if old_version and new_version and old_version != new_version:
        versions = f" ({old_version} → {new_version})"

    if errors:
        verdict = (
            f"**This change is breaking.**{versions} "
            f"{len(errors)} {_plural(len(errors), 'finding')} at ERROR "
            f"across {len(changes)} {_plural(len(changes), 'change')}."
        )
    elif warnings:
        verdict = (
            f"**This change is risky but not breaking.**{versions} "
            f"{len(warnings)} {_plural(len(warnings), 'finding')} at WARN "
            f"across {len(changes)} {_plural(len(changes), 'change')}."
        )
    elif changes:
        verdict = (
            f"**This change is backward compatible.**{versions} "
            f"{len(changes)} {_plural(len(changes), 'change')}, no breaking findings."
        )
    else:
        verdict = f"**No contract changes.**{versions}"

    # Grouped and counted, because twenty findings of one kind is one sentence,
    # not twenty.
    counts = Counter(_phrase_for(f.rule_id) for f in errors + warnings)
    what_changed = [
        f"{_sentence_case(phrase)} ({count})" if count > 1 else _sentence_case(phrase)
        for phrase, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]

    what_to_do: list[str] = []
    if errors:
        if suggested_version:
            what_to_do.append(f"Release this as **{suggested_version}**, not a patch.")
        else:
            what_to_do.append("Release this behind a major version bump.")
        what_to_do.append(
            "Or make it additive: deprecate with a sunset date instead of removing, "
            "and add optional fields instead of changing required ones."
        )
    if consumers:
        named = ", ".join(sorted(consumers)[:5])
        what_to_do.append(f"Registered consumers affected: {named}.")
    if warnings and not errors:
        what_to_do.append(
            "Nothing blocks release. Check the WARN findings if any consumer reads "
            "the fields involved."
        )
    if errors or warnings:
        what_to_do.append(
            "Run `apiverity explain <rule-id>` for the reasoning behind any finding, and what "
            "to ship instead."
        )

    return Summary(
        verdict=verdict,
        what_changed=what_changed,
        what_to_do=what_to_do,
        errors=len(errors),
        warnings=len(warnings),
        change_count=len(changes),
    )


__all__ = ["Summary", "summarize"]
