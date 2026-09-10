"""Render docs/security-rules.md from `apiverity/security/catalog.py`.

Generated for the same reason `docs/rule-catalog.md` is: a hand-written list of
twenty-two rule ids drifts, and the version that drifts is the one people
configure `--severity-override` from. Run after editing the catalogue;
`--check` fails when the committed file is stale.
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from apiverity.security.catalog import SECURITY_CATALOG

NL = chr(10)

_HEADER = """# Security rules

Static checks over a normalized contract, run by `apiverity validate`. Every one
is addressable: `apiverity explain SEC-APIKEY-IN-QUERY` prints what it means,
what to ship instead, and the exact `--severity-override` to change it.

This file is generated from `apiverity/security/catalog.py`. A test fails when
a check emits an id the catalogue does not carry, and when the catalogue
carries an id nothing emits -- the first is a rule that cannot be explained,
the second is a rule that is published and dead.

These rules are **not** covered by the severity profiles in
[the rule catalogue](rule-catalog.md#severity-profiles), which act on the
breaking-change catalogue only. Use `--severity-override` or the config's
`severity_overrides` for these.

"""

#: Group title -> the prefixes that belong to it, in the order they are shown.
#: Ordered from the rules about who may call, through what they may send, to
#: how it travels -- which is the order a reviewer reads a contract in.
_GROUPS: list[tuple[str, tuple[str, ...], str]] = [
    (
        "Authentication",
        ("SEC-AUTH-", "SEC-SCHEME-", "SEC-NO-AUTH-"),
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
        ("SEC-ARRAY-", "SEC-COLLECTION-", "SEC-RATE-LIMIT-"),
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
]


def _cell(value: str) -> str:
    return value.replace("|", chr(92) + "|").replace(NL, " ")


def render() -> str:
    remaining = dict(sorted(SECURITY_CATALOG.items()))
    out = [_HEADER]
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
    if remaining:
        # Never silently dropped: a rule with no group is a rule this document
        # would otherwise omit while claiming to be the whole list.
        out.append(f"## Other{NL}")
        out.append("| Rule | Severity | Produced by | Fires when | Instead |")
        out.append("|---|---|---|---|---|")
        for spec in remaining.values():
            out.append(
                f"| `{spec.rule_id}` | {spec.severity.value} | `{spec.produced_by}` "
                f"| {_cell(spec.description)} | {_cell(spec.instead)} |"
            )
        out.append("")
    out.append(f"_{len(SECURITY_CATALOG)} security rules._{NL}")
    return NL.join(out)


def main() -> int:
    target = pathlib.Path(__file__).resolve().parents[1] / "docs" / "security-rules.md"
    rendered = render()
    previous = target.read_text(encoding="utf-8") if target.is_file() else None
    if previous == rendered:
        print(f"ok     {target.name} ({len(SECURITY_CATALOG)} rules)")
        return 0
    if "--check" in sys.argv:
        print(
            "error: docs/security-rules.md is stale; run scripts/generate_security_rules.py",
            file=sys.stderr,
        )
        return 1
    target.write_text(rendered, encoding="utf-8", newline=NL)
    print(f"wrote  {target.name} ({len(SECURITY_CATALOG)} rules)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
