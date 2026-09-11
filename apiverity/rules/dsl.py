"""Governance rules a team writes in YAML, without forking this package.

[`rule-packs.md`](../../docs/rule-packs.md) says how to ship a pack as a Python
distribution. That is the right answer for a rule with real logic in it and the
wrong one for *"every path must be kebab-case"* — which is most of what an
organisation actually wants to enforce and does not justify a package, a
release process and a place to put it.

```yaml
pack: acme-house-style
version: 1.0.0
rules:
  - id: ACME-PATHS-KEBAB
    severity: warn
    rationale: a mixed-case path is a support ticket about a 404
    remediation: rename the path; add the old one as a deprecated alias first
    select: operation
    where:
      path: {matches: "^(/[a-z0-9-]+)+(/\\{[a-zA-Z0-9_]+\\})?$"}
```

## A fixed vocabulary, not an expression language

Every selector below reads one field of the normalized contract model. There is
no `eval`, no JSONPath, no embedded language.

That is a deliberate ceiling. A general expression evaluator would be a second
engine inside this one — precisely what `rule-packs.md` argues against for
Spectral — and it would let somebody write a rule this project cannot explain,
in a tool whose whole claim is that every finding has a stable id and a reason.

When the vocabulary runs out, write Python. A pack is twenty lines.

## An unknown word is refused by name

The failure this is built to avoid: a DSL that accepts an unrecognised selector,
matches nothing, and hands a team a rule they believe is running. Every unknown
key raises with the list of what is available, at load time, before anything
has been checked and reported clean.

## What a rule may exempt, and what that costs

`except` takes operation keys. It is a plain list of keys, not a pattern, so
an exemption names what it exempts — a glob that grows to cover six operations
nobody reviewed is the escape hatch becoming the policy.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from apiverity.core.model import (
    Finding,
    Operation,
    Protocol,
    Service,
    Severity,
)
from apiverity.rules.policy import RuleDefinition, RulePack

#: What a rule may select. Each is one pass over one part of the model.
SELECTORS = ("operation", "service")

#: `operation` fields, and what each reads.
OPERATION_FIELDS: dict[str, str] = {
    "operation_id": "the operation's declared operationId",
    "method": "the HTTP method, uppercased",
    "path": "the path template as written",
    "summary": "the one-line summary",
    "description": "the long description",
    "tags": "the operation's tags",
    "security": "the security requirements, or none if it inherits",
    "responses": "the declared status codes",
    "parameters": "the declared parameter names",
    "request_body": "whether a request body is declared",
}

#: `service` fields.
SERVICE_FIELDS: dict[str, str] = {
    "title": "the contract title",
    "version": "the contract version",
    "servers": "the declared server URLs",
    "security_schemes": "the names of the declared security schemes",
    "global_security": "the contract-wide security requirements",
}

#: The tests a field may be put to.
PREDICATES: dict[str, str] = {
    "present": "the field is set and not empty",
    "absent": "the field is unset or empty",
    "matches": "every value matches this regular expression",
    "not_matches": "no value matches this regular expression",
    "includes": "the collection contains this value",
    "excludes": "the collection does not contain this value",
    "one_of": "the value is one of these",
}

_SEVERITIES = {s.value.lower(): s for s in Severity}


class PolicyError(Exception):
    """A policy file this will not load.

    Raised at load time on purpose. A rule that silently matched nothing would
    be a gate somebody believes they have.
    """


def _values(target: Operation | Service, field: str) -> list[str] | None:
    """The field, as a list of strings, or None when it is unset.

    `None` and `[]` are different answers and the callers depend on it:
    "declares no tags" is absent, while "declares the tag ''" is not.
    """
    if isinstance(target, Operation):
        if field == "operation_id":
            return [target.operation_id] if target.operation_id else None
        if field == "method":
            return [target.method.upper()] if target.method else None
        if field == "path":
            return [target.path] if target.path else None
        if field == "summary":
            return [target.summary] if target.summary else None
        if field == "description":
            return [target.description] if target.description else None
        if field == "tags":
            return list(target.tags) or None
        if field == "security":
            # `None` means the operation inherits; an empty list means it
            # explicitly declares no security, which is the anonymous case and
            # a different fact.
            if target.security is None:
                return None
            return [r.scheme_name for r in target.security] or [""]
        if field == "responses":
            return [r.status for r in target.responses] or None
        if field == "parameters":
            return [p.name for p in target.parameters] or None
        if field == "request_body":
            return ["declared"] if target.request_body is not None else None
        return None

    if field == "title":
        return [target.title] if target.title else None
    if field == "version":
        return [target.version] if target.version else None
    if field == "servers":
        return [s.url for s in target.servers] or None
    if field == "security_schemes":
        return list(target.security_schemes) or None
    if field == "global_security":
        return [r.scheme_name for r in target.global_security] or None
    return None


def _test(values: list[str] | None, predicate: str, expected: Any) -> bool:
    """True when the field satisfies the predicate."""
    if predicate == "present":
        return bool(values)
    if predicate == "absent":
        return not values
    if not values:
        # A field that is not there cannot match a pattern. `absent` is the
        # predicate for asking about that, and conflating the two would make
        # `matches` silently pass on every operation that omits the field.
        return False
    if predicate == "matches":
        pattern = re.compile(str(expected))
        return all(pattern.search(v) for v in values)
    if predicate == "not_matches":
        pattern = re.compile(str(expected))
        return not any(pattern.search(v) for v in values)
    if predicate == "includes":
        return str(expected) in values
    if predicate == "excludes":
        return str(expected) not in values
    if predicate == "one_of":
        allowed = {str(x) for x in (expected or [])}
        return all(v in allowed for v in values)
    return False  # pragma: no cover - unreachable, validated at load


@dataclass(frozen=True)
class Condition:
    field: str
    predicate: str
    expected: Any = None

    def describe(self) -> str:
        if self.predicate in ("present", "absent"):
            return f"{self.field} is {self.predicate}"
        return f"{self.field} {self.predicate} {self.expected!r}"


@dataclass
class DslRule:
    rule_id: str
    severity: Severity
    rationale: str
    remediation: str
    select: str
    conditions: list[Condition]
    #: Operation keys this rule does not apply to, named individually.
    exempt: list[str]
    protocols: frozenset[Protocol]

    def _failures(self, target: Operation | Service) -> list[Condition]:
        return [
            c
            for c in self.conditions
            if not _test(_values(target, c.field), c.predicate, c.expected)
        ]

    def check(self, service: Service) -> list[Finding]:
        out: list[Finding] = []
        if self.select == "service":
            broken = self._failures(service)
            if broken:
                out.append(
                    Finding(
                        rule_id=self.rule_id,
                        severity=self.severity,
                        message=f"{self.rationale} ({'; '.join(c.describe() for c in broken)})",
                        hint=self.remediation,
                        location=service.source_location,
                    )
                )
            return out

        for op in service.operations:
            if op.key in self.exempt:
                continue
            broken = self._failures(op)
            if broken:
                out.append(
                    Finding(
                        rule_id=self.rule_id,
                        severity=self.severity,
                        message=(
                            f"'{op.key}': {self.rationale} "
                            f"({'; '.join(c.describe() for c in broken)})"
                        ),
                        operation_key=op.key,
                        hint=self.remediation,
                        location=op.source_location,
                    )
                )
        return out


def _require(raw: dict[str, Any], key: str, where: str) -> Any:
    if key not in raw or raw[key] in (None, ""):
        raise PolicyError(f"{where} has no `{key}`")
    return raw[key]


def _conditions(raw: Any, rule_id: str, fields: dict[str, str]) -> list[Condition]:
    if not isinstance(raw, dict) or not raw:
        raise PolicyError(f"rule '{rule_id}' has no `where` conditions")
    out: list[Condition] = []
    for field, test in raw.items():
        if field not in fields:
            raise PolicyError(
                f"rule '{rule_id}' selects `{field}`, which is not a field this "
                f"vocabulary has. Available: {', '.join(sorted(fields))}"
            )
        if isinstance(test, str):
            # `operation_id: present` -- the shorthand for a predicate that
            # takes no argument.
            if test not in PREDICATES:
                raise PolicyError(
                    f"rule '{rule_id}' uses predicate `{test}` on `{field}`, which is "
                    f"not one this vocabulary has. Available: {', '.join(sorted(PREDICATES))}"
                )
            out.append(Condition(field=field, predicate=test))
            continue
        if not isinstance(test, dict) or len(test) != 1:
            raise PolicyError(
                f"rule '{rule_id}' gives `{field}` something that is neither a predicate "
                "name nor a single `{predicate: value}` mapping"
            )
        predicate, expected = next(iter(test.items()))
        if predicate not in PREDICATES:
            raise PolicyError(
                f"rule '{rule_id}' uses predicate `{predicate}` on `{field}`, which is "
                f"not one this vocabulary has. Available: {', '.join(sorted(PREDICATES))}"
            )
        if predicate in ("matches", "not_matches"):
            try:
                re.compile(str(expected))
            except re.error as exc:
                raise PolicyError(
                    f"rule '{rule_id}' has a `{predicate}` pattern that will not compile: {exc}"
                ) from exc
        out.append(Condition(field=field, predicate=predicate, expected=expected))
    return out


def load(path: str | Path) -> tuple[RulePack, list[DslRule]]:
    """Read a policy file into a pack `PolicyEngine` can run."""
    import yaml

    source = Path(path)
    try:
        raw = yaml.safe_load(source.read_text(encoding="utf-8-sig"))
    except (OSError, yaml.YAMLError) as exc:
        raise PolicyError(f"could not read '{source}': {exc}") from exc
    if not isinstance(raw, dict):
        raise PolicyError(f"'{source}' is not a policy file: the document is not a mapping")

    name = str(_require(raw, "pack", str(source)))
    version = str(_require(raw, "version", str(source)))
    rules_raw = raw.get("rules")
    if not isinstance(rules_raw, list) or not rules_raw:
        raise PolicyError(f"'{source}' declares no `rules`")

    rules: list[DslRule] = []
    seen: set[str] = set()
    for entry in rules_raw:
        if not isinstance(entry, dict):
            raise PolicyError(f"'{source}' has a rule that is not a mapping")
        rule_id = str(_require(entry, "id", f"a rule in '{source}'"))
        if rule_id in seen:
            # Two rules with one id cannot both be explained, and one would
            # silently win. The same reason `PolicyEngine` refuses it across
            # packs.
            raise PolicyError(f"'{source}' declares rule '{rule_id}' twice")
        seen.add(rule_id)

        severity_name = str(entry.get("severity", "warn")).lower()
        if severity_name not in _SEVERITIES:
            raise PolicyError(
                f"rule '{rule_id}' has severity '{severity_name}'. "
                f"Available: {', '.join(sorted(_SEVERITIES))}"
            )
        select = str(entry.get("select", "operation"))
        if select not in SELECTORS:
            raise PolicyError(
                f"rule '{rule_id}' selects '{select}'. Available: {', '.join(SELECTORS)}"
            )

        protocols = entry.get("protocols")
        if protocols is None:
            allowed = frozenset(Protocol)
        else:
            try:
                allowed = frozenset(Protocol(str(p)) for p in protocols)
            except ValueError as exc:
                raise PolicyError(
                    f"rule '{rule_id}' names a protocol that does not exist: {exc}"
                ) from exc

        rules.append(
            DslRule(
                rule_id=rule_id,
                severity=_SEVERITIES[severity_name],
                rationale=str(_require(entry, "rationale", f"rule '{rule_id}'")),
                remediation=str(_require(entry, "remediation", f"rule '{rule_id}'")),
                select=select,
                conditions=_conditions(
                    entry.get("where"),
                    rule_id,
                    OPERATION_FIELDS if select == "operation" else SERVICE_FIELDS,
                ),
                exempt=[str(k) for k in (entry.get("except") or [])],
                protocols=allowed,
            )
        )

    pack = RulePack(
        name=name,
        version=version,
        description=str(raw.get("description") or f"policy rules from {source.name}"),
        rules=tuple(
            RuleDefinition(
                rule_id=r.rule_id,
                severity=r.severity,
                rationale=r.rationale,
                remediation=r.remediation,
                protocols=r.protocols,
                check=r.check,
            )
            for r in rules
        ),
    )
    return pack, rules


def vocabulary() -> dict[str, Any]:
    """Every word this DSL knows, for `apiverity rules --policy-vocabulary`.

    Published from the same tables the loader validates against, so the
    documentation of what is available cannot disagree with what is accepted.
    """
    return {
        "selectors": list(SELECTORS),
        "fields": {"operation": OPERATION_FIELDS, "service": SERVICE_FIELDS},
        "predicates": PREDICATES,
        "severities": sorted(_SEVERITIES),
    }


__all__ = [
    "OPERATION_FIELDS",
    "PREDICATES",
    "SELECTORS",
    "SERVICE_FIELDS",
    "Condition",
    "DslRule",
    "PolicyError",
    "load",
    "vocabulary",
]
