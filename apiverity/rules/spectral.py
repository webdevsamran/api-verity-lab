"""Reading a Spectral ruleset, and saying honestly what it could not bring.

Spectral owns rule-catalog linting, and a team that has one has invested in it.
Migration cost is the real competitor, so this reads `.spectral.yaml` and says
which of its rules this project already covers, which it does not, and — the
part that matters — **which are not expressible here at all**.

## What it will not do

Run Spectral's rules. A Spectral rule is a JSONPath `given` plus a function
over the document, and reimplementing that would mean building a second engine
whose findings look like this project's and were computed by different code.
The whole design of this repository is one contract model that every engine
reads; a bolted-on JSONPath evaluator would be exactly the thing it was built
to avoid.

So this is a **migration report**, not a compatibility layer, and it is careful
to be read as one.

## The three answers, and why the third one is the useful one

* `covered` — a rule with an equivalent here, named. Turn it off in Spectral if
  you like.
* `not_covered` — a rule this project could express and does not. That list is
  a backlog, and it is the honest output of a tool asking to replace another.
* `not_expressible` — a rule that reaches into the *document* rather than the
  contract: a description's wording, a key's casing, a vendor extension's
  shape. This project compiles documents into a normalized model and most of
  that does not survive the compile, by design.

A migration tool that reported only the first list would be claiming coverage
it does not have. The count that decides whether to migrate is the second and
third together.

## Matching is by rule name, and says so

Spectral rule names are conventional (`oas3-valid-schema-example`,
`operation-operationId`) rather than standardised, and a ruleset may rename
anything. The mapping below is over the names the published rulesets use —
`spectral:oas` and `spectral:asyncapi` — plus the handful of styleguide names
common enough to be worth carrying. A custom rule with a bespoke name lands in
`not_covered` even when this project happens to check the same thing, which is
the safe direction to be wrong in: it over-reports the backlog rather than
over-claiming the coverage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: Spectral rule name -> the rule here that covers it.
#:
#: Over the names `spectral:oas` publishes, which is what a ruleset that starts
#: with `extends: spectral:oas` turns off by name.
EQUIVALENTS: dict[str, str] = {
    "operation-operationId": "GOV-MISSING-OPERATION-ID",
    "operation-operationId-unique": "GOV-MISSING-OPERATION-ID",
    "oas3-valid-schema-example": "LINT-INVALID-EXAMPLE",
    "oas3-valid-media-example": "LINT-INVALID-EXAMPLE",
    "oas2-valid-schema-example": "LINT-INVALID-EXAMPLE",
    "oas2-valid-media-example": "LINT-INVALID-EXAMPLE",
    "oas3-schema": "SPEC-SCHEMA-INVALID",
    "oas2-schema": "SPEC-SCHEMA-INVALID",
    "oas3-unused-component": "GOV-UNUSED-SECURITY-SCHEME",
    "oas2-unused-definition": "GOV-UNUSED-SECURITY-SCHEME",
    "operation-success-response": "LINT-EMPTY-RESPONSE",
    "oas3-server-not-example.com": "SEC-HTTPS-POLICY",
    "no-eval-in-markdown": "SEC-SECRET-IN-CONTRACT",
    "no-script-tags-in-markdown": "SEC-SECRET-IN-CONTRACT",
}

#: Rules that reach into the document rather than the contract, with the reason.
#:
#: Not a backlog. This project compiles a document into a normalized model, and
#: a rule about a description's wording or a key's casing is asking about the
#: document -- which is a different question, answered by a different kind of
#: tool, and one Spectral answers well.
NOT_EXPRESSIBLE: dict[str, str] = {
    "contact-properties": "about `info.contact`, which is document metadata, not contract",
    "info-contact": "about `info.contact`, which is document metadata, not contract",
    "info-description": "about the wording of a description",
    "info-license": "about `info.license`, which is document metadata, not contract",
    "license-url": "about `info.license`, which is document metadata, not contract",
    "openapi-tags": "about the document's tag list, not about any operation",
    "operation-tags": "about tagging convention rather than contract shape",
    "operation-description": "about the wording of a description",
    "operation-tag-defined": "about the document's tag list",
    "tag-description": "about the wording of a description",
    "operation-singular-tag": "about tagging convention",
    "description-duplicates-summary": "about the wording of a description",
    "path-keys-no-trailing-slash": "about how a path is written, not what it addresses",
    "path-declarations-must-exist": "about path-template syntax in the document",
    "path-not-include-query": "about how a path is written in the document",
    "no-$ref-siblings": "about `$ref` placement in the document, which the bundler resolves away",
    "oas3-api-servers": "about the document's `servers` block being present",
    "oas2-api-host": "about the document's `host` field being present",
    "oas2-api-schemes": "about the document's `schemes` field being present",
    "typed-enum": "about the document's enum literals matching a declared type",
    "duplicated-entry-in-enum": "about duplicate literals in the document",
}


class SpectralError(Exception):
    """A file that is not a Spectral ruleset."""


@dataclass
class Imported:
    """What a ruleset asked for, and what this project can answer."""

    source: str
    #: The `extends` entries, verbatim. A ruleset that extends `spectral:oas`
    #: carries every rule in that set without naming one of them, so the report
    #: has to say which sets were pulled in rather than counting only the
    #: rules written down here.
    extends: list[str] = field(default_factory=list)
    #: Spectral rule name -> this project's rule id.
    covered: dict[str, str] = field(default_factory=dict)
    #: Rules that could be expressed here and are not. The backlog.
    not_covered: list[str] = field(default_factory=list)
    #: Rule -> why it is about the document rather than the contract.
    not_expressible: dict[str, str] = field(default_factory=dict)
    #: Rules the ruleset explicitly turns off. Named, because a migration that
    #: silently re-enabled somebody's disabled rule has changed their gate.
    disabled: list[str] = field(default_factory=list)

    @property
    def named(self) -> int:
        return (
            len(self.covered)
            + len(self.not_covered)
            + len(self.not_expressible)
            + len(self.disabled)
        )

    def summary(self) -> str:
        parts = [
            f"{len(self.covered)} covered",
            f"{len(self.not_covered)} not covered",
            f"{len(self.not_expressible)} not expressible here",
        ]
        if self.disabled:
            parts.append(f"{len(self.disabled)} disabled in the ruleset")
        line = ", ".join(parts)
        if self.extends:
            # The honest caveat. `extends: spectral:oas` is sixty-odd rules the
            # file does not list, and a report counting only the named ones
            # would describe a fraction of the gate being migrated.
            line += (
                f". This ruleset extends {', '.join(self.extends)}, whose rules are not "
                "listed in the file and are not counted above"
            )
        return line

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "extends": self.extends,
            "summary": self.summary(),
            "covered": self.covered,
            "not_covered": self.not_covered,
            "not_expressible": self.not_expressible,
            "disabled": self.disabled,
            "rules_named_in_the_file": self.named,
        }


def _extends(raw: Any) -> list[str]:
    """`extends` is a string, a list, or a list of [name, severity] pairs."""
    if isinstance(raw, str):
        return [raw]
    out: list[str] = []
    for item in raw or []:
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, list) and item:
            out.append(str(item[0]))
    return out


#: What YAML hands back for a rule that is switched off.
#:
#: `False` is in here because YAML 1.1 parses a bare `off` as a boolean, so
#: `operation-tags: off` and `severity: off` both arrive as `False` -- and a
#: check comparing against the string `"off"` matches neither. Quoted (`"off"`)
#: it stays a string, so both forms have to be accepted.
_OFF = (False, "off", "OFF", "Off")


def _disabled(value: Any) -> bool:
    """Spectral turns a rule off with `false`, `off`, or `severity: off`."""
    if value in _OFF:
        return True
    return isinstance(value, dict) and value.get("severity") in _OFF


def read(path: str | Path) -> Imported:
    """Read a Spectral ruleset and classify every rule it names."""
    import yaml

    source = Path(path)
    try:
        raw = yaml.safe_load(source.read_text(encoding="utf-8-sig"))
    except (OSError, yaml.YAMLError) as exc:
        raise SpectralError(f"could not read '{source}': {exc}") from exc
    if not isinstance(raw, dict):
        raise SpectralError(f"'{source}' is not a Spectral ruleset: the document is not a mapping")
    if "rules" not in raw and "extends" not in raw:
        raise SpectralError(
            f"'{source}' has neither `rules` nor `extends`, so it is not a Spectral ruleset"
        )

    out = Imported(source=str(source), extends=_extends(raw.get("extends")))
    rules = raw.get("rules")
    if rules is not None and not isinstance(rules, dict):
        raise SpectralError(f"'{source}' has a `rules` key that is not a mapping")

    for name, value in (rules or {}).items():
        key = str(name)
        if _disabled(value):
            out.disabled.append(key)
        elif key in EQUIVALENTS:
            out.covered[key] = EQUIVALENTS[key]
        elif key in NOT_EXPRESSIBLE:
            out.not_expressible[key] = NOT_EXPRESSIBLE[key]
        else:
            # Including custom rules whose names this mapping has never seen.
            # Over-reporting the backlog is the safe direction: the alternative
            # is claiming coverage of a rule nobody checked.
            out.not_covered.append(key)

    out.not_covered.sort()
    out.disabled.sort()
    return out


__all__ = ["EQUIVALENTS", "NOT_EXPRESSIBLE", "Imported", "SpectralError", "read"]
