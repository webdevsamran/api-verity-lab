"""A worked example of a third-party rule pack.

Three rules a real platform team would want and this project deliberately does
not ship, because they are house style rather than facts about contracts:

* **HOUSE-PATH-CASE** — paths are `kebab-case`. Somebody has to decide between
  `/user-profiles` and `/userProfiles`, and it is not this tool.
* **HOUSE-LIST-PAGINATION** — a collection `GET` declares a paging parameter.
  Which parameter, and whether it is required, is a house decision; that there
  should be one is a lesson every team learns the same way.
* **HOUSE-ERROR-SHAPE** — every operation declares at least one 4xx response.
  A contract that describes only its happy path is a contract whose consumers
  guess at failure.

## Why these are here and not in the engine

A rule the project ships is a rule every user gets, and a rule every user gets
has to be true for every user. "Paths are kebab-case" is true for a great many
teams and false for the ones who standardised on something else years ago —
publishing it as a built-in would produce a false positive on their first run,
and a false positive is what gets a rule switched off along with its
neighbours.

That is the line: the engine ships rules about what *breaks consumers*; a pack
ships rules about what a team has agreed to.

## Shape

The entry point returns a `RulePack`. It can be the pack itself or a callable
returning one — `discover()` calls it if it is callable — and a factory is the
better habit, because it defers the work until somebody asks.
"""

from __future__ import annotations

import re

from apiverity.core.model import Finding, Protocol, Service, Severity
from apiverity.rules.policy import RuleDefinition, RulePack

VERSION = "1.0.0"

#: `/user-profiles/{id}` yes, `/userProfiles/{id}` no. Path *parameters* are
#: exempt: `{userId}` is a variable name, and a team's casing convention for
#: those is a different argument.
KEBAB = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

#: Any one of these counts. A pack that demanded a specific spelling would be
#: enforcing this pack's opinion rather than the team's.
PAGING = ("limit", "page", "per_page", "perPage", "page_size", "pageSize", "cursor", "offset")


def _segments(path: str) -> list[str]:
    return [s for s in path.split("/") if s and not s.startswith("{")]


def path_case(service: Service) -> list[Finding]:
    findings: list[Finding] = []
    for operation in service.operations:
        offenders = [s for s in _segments(operation.path or "") if not KEBAB.match(s)]
        if offenders:
            findings.append(
                Finding(
                    rule_id="HOUSE-PATH-CASE",
                    severity=Severity.WARN,
                    message=(
                        f"path '{operation.path}' has non-kebab-case segment(s): "
                        f"{', '.join(offenders)}"
                    ),
                    operation_key=operation.key,
                    hint="rename the segment, or drop this rule if your house style differs",
                )
            )
    return findings


def list_pagination(service: Service) -> list[Finding]:
    findings: list[Finding] = []
    for operation in service.operations:
        if (operation.method or "").upper() != "GET":
            continue
        path = operation.path or ""
        # A collection, not an item: `/orders` pages, `/orders/{id}` does not.
        if not path or path.rstrip("/").endswith("}"):
            continue
        names = {p.name for p in (operation.parameters or [])}
        if not names.intersection(PAGING):
            findings.append(
                Finding(
                    rule_id="HOUSE-LIST-PAGINATION",
                    severity=Severity.WARN,
                    message=(
                        f"collection operation '{operation.key}' declares no paging parameter "
                        f"(any of: {', '.join(PAGING)})"
                    ),
                    operation_key=operation.key,
                    hint="add a paging parameter before the collection grows one for you",
                )
            )
    return findings


def error_shape(service: Service) -> list[Finding]:
    findings: list[Finding] = []
    for operation in service.operations:
        # `responses` is a list of `Response`, not a dict keyed by status. The
        # first version of this rule read it as a mapping and quietly reported
        # every operation, which is what a pack's own tests are for.
        codes = [str(r.status) for r in (operation.responses or [])]
        if not any(code.startswith("4") for code in codes):
            findings.append(
                Finding(
                    rule_id="HOUSE-ERROR-SHAPE",
                    severity=Severity.INFO,
                    message=(
                        f"operation '{operation.key}' declares no 4xx response "
                        f"(declared: {', '.join(sorted(codes)) or 'none'})"
                    ),
                    operation_key=operation.key,
                    hint="a contract that describes only its happy path leaves failure to guesswork",
                )
            )
    return findings


#: HTTP-shaped protocols only. A GraphQL schema has no paths and one status
#: code, so running these against it would produce findings nobody can act on
#: -- and a rule that fires where it cannot be satisfied is the fastest way to
#: get a whole pack disabled.
HTTP_LIKE = frozenset({Protocol.OPENAPI})

RULES = (
    RuleDefinition(
        rule_id="HOUSE-PATH-CASE",
        severity=Severity.WARN,
        rationale="Mixed path casing makes an API read as several APIs stitched together.",
        remediation="Rename the segment to kebab-case.",
        protocols=HTTP_LIKE,
        check=path_case,
    ),
    RuleDefinition(
        rule_id="HOUSE-LIST-PAGINATION",
        severity=Severity.WARN,
        rationale=(
            "A collection endpoint without paging is fine until the collection is large, "
            "and adding paging afterwards is a breaking change."
        ),
        remediation="Declare a paging parameter now, while adding one is additive.",
        protocols=HTTP_LIKE,
        check=list_pagination,
    ),
    RuleDefinition(
        rule_id="HOUSE-ERROR-SHAPE",
        severity=Severity.INFO,
        rationale="Consumers write error handling against the contract or against guesswork.",
        remediation="Declare the 4xx responses this operation can return.",
        protocols=HTTP_LIKE,
        check=error_shape,
    ),
)

PACK = RulePack(
    name="house-rules",
    version=VERSION,
    description="An example third-party pack: house style rules the engine does not ship.",
    rules=RULES,
)


def pack() -> RulePack:
    """The entry point.

    A factory rather than the pack itself, so importing this module is cheap
    and the work happens when something asks for it. `discover()` accepts
    either.
    """
    return PACK


__all__ = ["PACK", "RULES", "VERSION", "error_shape", "list_pagination", "pack", "path_case"]
