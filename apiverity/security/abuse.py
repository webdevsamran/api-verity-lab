"""The abuse surface: what a caller can ask for, and what happens when it is too much.

`SEC-RATE-LIMIT-METADATA` already said, once per contract, that nothing
anywhere mentioned a rate limit. That is the easy half and it is nearly useless
on a contract that *does* mention one: an API with rate limiting documented on
four of forty operations passes it, and the other thirty-six are the ones a
client discovers in production.

So the checks here are about the shape of what is declared rather than its
presence somewhere.

## The standards position, checked 2026-09-10

`RateLimit` and `RateLimit-Policy` come from
[draft-ietf-httpapi-ratelimit-headers](https://datatracker.ietf.org/doc/draft-ietf-httpapi-ratelimit-headers/),
revision **-11**, last updated **2026-05-23**. It is an **active Internet-Draft
and not an RFC**, and its datatracker page records no intended RFC status. Two
fields, both Structured Field Lists: `RateLimit-Policy` carries the quota (`q`),
its units (`qu`), the window (`w`) and a partition key (`pk`); `RateLimit`
carries the remaining quota (`r`), the effective window (`t`) and `pk`.

That pair *replaced* the three-field `RateLimit-Limit` / `RateLimit-Remaining` /
`RateLimit-Reset` set from earlier revisions of the same draft. And `X-RateLimit-*`
was never specified by anything at all.

None of that is a reason to tell anyone to migrate, and this module does not.
Recommending a move to a draft is exactly the overreach that gets a linter
switched off. What it does is name which of the three a contract declares, at
INFO, so the choice is a choice rather than an accident.

`Retry-After` is different: it is standardised, in
[RFC 9110 §10.2.3](https://www.rfc-editor.org/rfc/rfc9110#section-10.2.3), and a
429 without one is a real defect. A client that cannot compute a backoff retries
immediately, which turns a rate limit into an outage.
"""

from __future__ import annotations

from apiverity.core.model import Finding, Operation, Protocol, SchemaNode, Service, Severity

#: Where the draft ended up, and where it came from. Quoted in a finding so a
#: reader does not have to take the rule's word for which is which.
CURRENT_FIELDS = ("ratelimit", "ratelimit-policy")
LEGACY_FIELDS = ("ratelimit-limit", "ratelimit-remaining", "ratelimit-reset")

#: Statuses whose whole meaning is "come back later", and which therefore need
#: to say when. 503 is here for the same reason as 429: RFC 9110 defines
#: `Retry-After` for both, and a client that cannot compute a backoff retries
#: immediately.
BACKOFF_STATUSES = ("429", "503")

#: Query parameters that mean "how many". Matched on the name because there is
#: nowhere else to look: no specification marks a parameter as the page size,
#: and these are the spellings APIs actually use.
PAGE_SIZE_NAMES = frozenset(
    {
        "limit",
        "count",
        "size",
        "top",
        "page_size",
        "pagesize",
        "per_page",
        "perpage",
        "max_results",
        "maxresults",
        "page_limit",
        "pagelimit",
        "n",
    }
)

#: Numeric types a page size is expressed in. A string page size is somebody
#: else's problem.
_NUMERIC = {"integer", "number"}


def _headers(operation: Operation) -> set[str]:
    return {name.lower() for response in operation.responses for name in response.headers}


def _declared_statuses(operation: Operation) -> set[str]:
    return {response.status for response in operation.responses}


def _bounded(schema: SchemaNode | None) -> bool:
    if schema is None:
        return False
    if schema.maximum is not None or schema.exclusive_maximum is not None:
        return True
    # An enum of allowed page sizes is a ceiling written a different way.
    return bool(schema.enum)


def _retry_after(service: Service) -> list[Finding]:
    """A declared 429 or 503 that never says when to come back."""
    findings: list[Finding] = []
    for op in service.operations:
        headers = _headers(op)
        if "retry-after" in headers:
            continue
        for response in op.responses:
            if response.status not in BACKOFF_STATUSES:
                continue
            if "retry-after" in {name.lower() for name in response.headers}:
                continue
            findings.append(
                Finding(
                    rule_id="SEC-RATE-LIMIT-NO-RETRY-AFTER",
                    severity=Severity.WARN,
                    message=(
                        f"operation '{op.key}' declares {response.status} and no "
                        "`Retry-After` header. A client that cannot compute a backoff "
                        "retries immediately, which turns a rate limit into an outage"
                    ),
                    operation_key=op.key,
                    location=response.source_location or op.source_location,
                    hint=(
                        "Declare `Retry-After` on the response (RFC 9110 section 10.2.3). "
                        "Either a delay in seconds or an HTTP-date; both are valid."
                    ),
                )
            )
    return findings


def _inconsistent_429(service: Service) -> list[Finding]:
    """Operations with no 429, in a contract where other operations have one.

    Reported only when the contract declares 429 *somewhere*. An API that
    documents no limit at all is already covered, once, by
    `SEC-RATE-LIMIT-METADATA`; emitting a finding per operation for it would
    produce a wall of identical warnings that says one thing.

    This is the other case, and it is the one worth reading: the API does rate
    limit, some operations say so, and these do not.
    """
    limited = [op for op in service.operations if "429" in _declared_statuses(op)]
    if not limited or len(limited) == len(service.operations):
        return []
    named = ", ".join(sorted(op.key for op in limited)[:3])
    return [
        Finding(
            rule_id="SEC-RATE-LIMIT-NO-429",
            severity=Severity.WARN,
            message=(
                f"operation '{op.key}' declares no 429, though {len(limited)} operation(s) "
                f"in this contract do ({named})"
            ),
            operation_key=op.key,
            location=op.source_location,
            hint=(
                "Declare 429 here too, or say in the description that this operation is "
                "not limited. A caller cannot tell an operation with no limit from one "
                "whose limit nobody wrote down."
            ),
        )
        for op in service.operations
        if "429" not in _declared_statuses(op)
    ]


def _header_vocabulary(service: Service) -> list[Finding]:
    """Which of the three rate-limit vocabularies this contract speaks.

    Informational, both of them. The current pair is a draft, so telling anyone
    to move to it would be recommending an unstable target -- which is the kind
    of advice that gets a linter switched off. Naming what is declared is
    useful; instructing is not.
    """
    declared: set[str] = set()
    for op in service.operations:
        declared |= _headers(op)

    findings: list[Finding] = []
    vendor = sorted(name for name in declared if name.startswith("x-ratelimit"))
    if vendor:
        findings.append(
            Finding(
                rule_id="SEC-RATE-LIMIT-VENDOR-HEADERS",
                severity=Severity.INFO,
                message=(
                    f"this contract declares vendor rate-limit headers ({', '.join(vendor)}). "
                    "No specification defines them, so every client hardcodes this "
                    "spelling"
                ),
                location=service.source_location,
                hint=(
                    "Nothing to fix. Recorded because the standardised spellings are "
                    "different: `RateLimit` and `RateLimit-Policy`, from "
                    "draft-ietf-httpapi-ratelimit-headers-11 (2026-05-23), which is an "
                    "active Internet-Draft rather than an RFC."
                ),
            )
        )

    legacy = sorted(name for name in declared if name in LEGACY_FIELDS)
    if legacy:
        findings.append(
            Finding(
                rule_id="SEC-RATE-LIMIT-LEGACY-FIELDS",
                severity=Severity.INFO,
                message=(
                    f"this contract declares the three-field rate-limit set ({', '.join(legacy)}), "
                    "which later revisions of the same draft replaced with the "
                    "`RateLimit` / `RateLimit-Policy` pair"
                ),
                location=service.source_location,
                hint=(
                    "Nothing to fix, and deliberately no instruction to migrate: the "
                    "replacement is draft-ietf-httpapi-ratelimit-headers-11 (2026-05-23), "
                    "an active Internet-Draft with no intended RFC status recorded. "
                    "Recorded so the choice is a choice."
                ),
            )
        )
    return findings


def _unbounded_page_size(service: Service) -> list[Finding]:
    """`?limit=1000000`.

    Matched on the parameter's name, which is a heuristic and is worth being
    explicit about: nothing in any specification marks a parameter as the page
    size, so the alternative to a name list is not checking at all. The list is
    the spellings APIs actually use, and a false positive costs a reader one
    glance.
    """
    findings: list[Finding] = []
    for op in service.operations:
        for parameter in op.parameters:
            if parameter.location.value != "query":
                continue
            if parameter.name.lower().replace("-", "_") not in PAGE_SIZE_NAMES:
                continue
            schema = parameter.schema_node
            if schema is None or (schema.type not in _NUMERIC):
                continue
            if _bounded(schema):
                continue
            findings.append(
                Finding(
                    rule_id="SEC-ABUSE-UNBOUNDED-PAGE-SIZE",
                    severity=Severity.WARN,
                    message=(
                        f"operation '{op.key}' takes '{parameter.name}' with no `maximum`, "
                        "so the contract permits any page size a caller asks for"
                    ),
                    operation_key=op.key,
                    location=parameter.source_location or op.source_location,
                    hint=(
                        "Declare `maximum` on the parameter. If the server already caps it, "
                        "the contract still says otherwise, and a client written against "
                        "the contract will ask for the number it says is allowed."
                    ),
                )
            )
    return findings


def run_abuse_checks(service: Service) -> list[Finding]:
    """Every check in this module, in a stable order.

    HTTP-shaped protocols only. A gRPC or MCP contract has no status codes and
    no response headers, so every check here would be a finding about a field
    the format does not have -- which is the failure mode `SEC-AUTH-NOT-EXPRESSIBLE`
    exists to avoid repeating.
    """
    if service.protocol not in (Protocol.OPENAPI, Protocol.SOAP):
        return []
    findings: list[Finding] = []
    findings.extend(_inconsistent_429(service))
    findings.extend(_retry_after(service))
    findings.extend(_header_vocabulary(service))
    findings.extend(_unbounded_page_size(service))
    return findings


__all__ = [
    "BACKOFF_STATUSES",
    "CURRENT_FIELDS",
    "LEGACY_FIELDS",
    "PAGE_SIZE_NAMES",
    "run_abuse_checks",
]
