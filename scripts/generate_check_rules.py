"""Render docs/check-rules.md from the merged check catalogue.

Generated for the same reason `docs/rule-catalog.md` is: a hand-written list of
rule ids drifts, and the version that drifts is the one people configure
`--severity-override` from. One document rather than one per family, because
two documents with two generators drift from each other as well as from the
code. Run after editing a catalogue; `--check` fails when the committed file
is stale.
"""

from __future__ import annotations

import pathlib
import sys

# `scripts/` so `page_meta` resolves, the repository root so `apiverity`
# does. Running this as a script puts the first one on the path; loading
# it by file location -- which is how the tests load it -- puts neither.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from page_meta import front_matter

from apiverity.rules.check_catalog import catalog

SECURITY_CATALOG = catalog()

NL = chr(10)

_HEADER = """# Check rules

Every rule this tool emits that is not a breaking-change rule. Most are static
checks over a normalized contract, run by `apiverity validate`; the few that
need a live service say so in their own row.

Each is addressable: `apiverity explain SEC-APIKEY-IN-QUERY` prints what it
means, what to ship instead, and the exact `--severity-override` to change it.

This file is generated from the catalogues under `apiverity/rules/` and
`apiverity/security/`. A test fails when a check emits an id no catalogue
carries, and when a catalogue carries an id nothing emits -- the first is a
rule that cannot be explained, the second is a rule that is published and
dead.

These rules are **not** covered by the severity profiles in
[the rule catalogue](rule-catalog.md#severity-profiles), which act on the
breaking-change catalogue only. Use `--severity-override` or the config's
`severity_overrides` for these.

"""

#: Prose for a family section, where the family name alone is not enough.
_FAMILY_NOTES: dict[str, str] = {
    "The gate's escape hatch": (
        "The suppressions file, talking about itself. An entry that is not justified "
        "and bounded does not suppress -- it fails closed, the finding it named stays "
        "in the run, and `SUPPRESSION-INCOMPLETE` says which field is missing. A gate "
        "that could be quietened by an unsigned one-line entry is a gate that is "
        "already off."
    ),
    "Project configuration": (
        "`.apiverity.yaml`, checked by `apiverity config validate` and on every run "
        "that reads it. An ERROR here stops the run: a setting nobody reads is a "
        "setting the reader believes is active."
    ),
}

#: Group title -> the prefixes that belong to it, in the order they are shown.
#: Ordered from the rules about who may call, through what they may send, to
#: how it travels -- which is the order a reviewer reads a contract in.
#:
#: This claims the rules whose *prefix* says more than their family does: the
#: security family is 27 rules and five distinct jobs. Everything it does not
#: claim is sectioned by `CheckRuleSpec.family`, which is what that field is
#: for -- it had no reader at all until this, so two SEC rules added after the
#: table was written sat under a heading called "Other".
_GROUPS: list[tuple[str, tuple[str, ...], str]] = [
    (
        "Authentication",
        ("SEC-AUTH-", "SEC-SCHEME-", "SEC-NO-AUTH-", "SEC-UNAUTH-"),
        "What the document says about who may call an operation. Three of these are "
        "INFO because they record a fact rather than a fault: an explicit `security: []`, "
        "a format with nowhere to declare authentication, and a format this tool does "
        "not read it from. The last one matters most -- a clean security report from an "
        "adapter that never looked is not a clean bill of health.",
    ),
    (
        "Authorization scope",
        ("SEC-SCOPE-",),
        "Whether the scopes an operation requires narrow anything.",
    ),
    (
        "Credentials",
        (
            "SEC-APIKEY-",
            "SEC-BASIC-",
            "SEC-SECRET-",
            "SEC-RESPONSE-CREDENTIAL",
            "SEC-SENSITIVE-",
        ),
        "Where credentials are carried, and where they end up. A finding here never "
        "records the value -- the kind, the pointer and the length are enough to triage, "
        "and an artifact that quoted the secret would be a second copy of it.",
    ),
    (
        "Resource consumption",
        ("SEC-ARRAY-", "SEC-COLLECTION-", "SEC-RATE-LIMIT-", "SEC-ABUSE-"),
        "Limits the contract does not declare. Unbounded *strings* are deliberately not "
        "checked: most strings should have no `maxLength`, and a check that fires "
        "hundreds of times per contract gets switched off, taking the useful ones with "
        "it.",
    ),
    (
        "Shape and transport",
        ("SEC-ADDL-", "SEC-CORS-", "SEC-HTTPS-"),
        "",
    ),
    (
        "Behaviour",
        ("SEMANTIC-",),
        "Behaviour that changed while the contract stayed valid. Every case here is "
        "schema-legal -- an optional field that stopped being populated, an enum value "
        "that stopped appearing, a null rate that jumped -- which is exactly why no other "
        "check reports it. None is a defect on its own, so each finding carries the sample "
        "sizes behind it and the comparison declines to speak when they are too small.",
    ),
    (
        "Lifecycle",
        ("LIFECYCLE-",),
        "Deprecation with a date attached, or without one. `deprecated: true` is the "
        "whole of what OpenAPI says about retiring an operation -- no date, no migration "
        "target, no obligation -- so a contract can be deprecating something for six "
        "years and look identical on the day it is switched off. Dates and header shapes "
        "are checked against [RFC 9745](https://www.rfc-editor.org/rfc/rfc9745.html) "
        "(`Deprecation`, Standards Track, March 2025) and "
        "[RFC 8594](https://www.rfc-editor.org/rfc/rfc8594.html) (`Sunset`, "
        "Informational, May 2019), which use different date formats -- which is itself "
        "one of the checks.",
    ),
]


def _cell(value: str) -> str:
    return value.replace("|", chr(92) + "|").replace(NL, " ")


def render() -> str:
    remaining = dict(sorted(SECURITY_CATALOG.items()))
    out = [front_matter("check-rules.md") + _HEADER]
    for title, prefixes, note in _GROUPS:
        rows = [
            spec
            for rule_id, spec in list(remaining.items())
            if rule_id.startswith(prefixes) and remaining.pop(rule_id, None) is not None
        ]
        if not rows:
            continue
        out.append(f"## {title}{NL}")
        if note:
            out.append(f"{note}{NL}")
        out.append("| Rule | Severity | Produced by | Fires when | Instead |")
        out.append("|---|---|---|---|---|")
        for spec in rows:
            out.append(
                f"| `{spec.rule_id}` | {spec.severity.value} | `{spec.produced_by}` "
                f"| {_cell(spec.description)} | {_cell(spec.instead)} |"
            )
        out.append("")
    # Whatever the prefix table did not claim, sectioned by its declared
    # family. Never silently dropped: a rule with no section is a rule this
    # document would omit while claiming to be the whole list.
    for family in sorted({spec.family for spec in remaining.values()}):
        rows = [spec for spec in remaining.values() if spec.family == family]
        out.append(f"## {family}{NL}")
        note = _FAMILY_NOTES.get(family)
        if note:
            out.append(f"{note}{NL}")
        out.append("| Rule | Severity | Produced by | Fires when | Instead |")
        out.append("|---|---|---|---|---|")
        for spec in rows:
            out.append(
                f"| `{spec.rule_id}` | {spec.severity.value} | `{spec.produced_by}` "
                f"| {_cell(spec.description)} | {_cell(spec.instead)} |"
            )
        out.append("")
    out.append(f"_{len(SECURITY_CATALOG)} check rules._{NL}")
    return NL.join(out)


def main() -> int:
    target = pathlib.Path(__file__).resolve().parents[1] / "docs" / "check-rules.md"
    rendered = render()
    previous = target.read_text(encoding="utf-8") if target.is_file() else None
    if previous == rendered:
        print(f"ok     {target.name} ({len(SECURITY_CATALOG)} rules)")
        return 0
    if "--check" in sys.argv:
        print(
            f"error: docs/{target.name} is stale; run scripts/generate_check_rules.py",
            file=sys.stderr,
        )
        return 1
    target.write_text(rendered, encoding="utf-8", newline=NL)
    print(f"wrote  {target.name} ({len(SECURITY_CATALOG)} rules)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
