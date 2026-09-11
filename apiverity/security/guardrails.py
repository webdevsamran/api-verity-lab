"""What a generated payload is not allowed to carry to a live server.

`security/leakage.py` reads what comes *back*. This reads what goes out, which
is the half nobody checks because synthetic data feels safe by construction.

It is not. A generated payload is built from the contract, and a contract is a
document somebody wrote: an `example`, a `default`, an `enum` member. If one of
those carries a credential -- and `security/packs.py` exists because they do --
then a fuzz run reads it out of the repository and posts it to whatever
`--base-url` names. That is not a leak the tool found; it is one the tool
performed.

So a payload carrying something credential-shaped is **not sent**. Reported,
counted as a failure of that case, and the run continues with the rest. The
alternative -- a WARN beside a request that already went out -- is a finding
about an action that cannot be undone.

## The other one: size

`maxLength: 10000000` is a legal schema. A boundary generator asked for the
largest valid string produces ten megabytes, and sending it is a denial of
service somebody wrote by running a test suite. Capped, with the cap in the
finding, because a payload silently shrunk is a case that did not test what it
says it tested.

## What is deliberately not here

Injection payloads. A generated value that looks like SQL or a shell fragment
came out of the contract's own `pattern` or `enum`, so refusing to send it
would refuse to test what the contract says it accepts -- and a service that
mishandles it has a bug this run exists to find. The guardrail is about what
this tool must not *do*, not about what the target must not receive.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from apiverity.core.model import Finding, Severity

#: Refuse a body larger than this unless the caller raises it. A quarter of a
#: megabyte is far above any hand-written example and far below the size at
#: which a request becomes an attack.
DEFAULT_MAX_BYTES = 256 * 1024


@dataclass(frozen=True)
class Guardrails:
    """What this run is allowed to send."""

    max_bytes: int = DEFAULT_MAX_BYTES
    #: Send a payload carrying something credential-shaped anyway.
    #:
    #: Exists because a contract can legitimately declare a *token field* with
    #: a realistic-looking example, and a team testing their own staging
    #: environment may know that. It is an explicit choice with a name, not a
    #: default, for the same reason `replay` needs one to touch production.
    allow_credentials: bool = False

    def with_limit(self, max_bytes: int | None) -> Guardrails:
        return self if max_bytes is None else Guardrails(max_bytes, self.allow_credentials)


@dataclass
class Verdict:
    """Whether a payload may be sent, and what was found in it."""

    allowed: bool = True
    findings: list[Finding] = field(default_factory=list)
    #: The size that was measured, so a report can say how far over it was.
    size_bytes: int = 0

    @property
    def reasons(self) -> list[str]:
        return [f.message for f in self.findings]


def _size(body: Any) -> int:
    if body is None:
        return 0
    if isinstance(body, (bytes, bytearray)):
        return len(body)
    if isinstance(body, str):
        return len(body.encode("utf-8", "replace"))
    try:
        return len(json.dumps(body, default=str).encode("utf-8"))
    except (TypeError, ValueError):
        # Unserializable is not enormous. The send will fail on its own terms
        # and that failure belongs to the case, not to this check.
        return 0


def inspect(
    body: Any,
    *,
    operation_key: str | None = None,
    config: Guardrails | None = None,
) -> Verdict:
    """Decide whether a generated payload may go out.

    Returns a verdict rather than raising, because a run of four hundred cases
    should lose the one case that is unsendable, not the other three hundred
    and ninety-nine.
    """
    rules = config or Guardrails()
    verdict = Verdict(size_bytes=_size(body))

    from apiverity.security.leakage import scan_body

    leaks = scan_body(body)
    if leaks:
        # Named by kind and pointer, never by value -- the same rule
        # `leakage.py` follows. A guardrail that printed the credential to
        # prove it stopped it has copied it into a log.
        detail = ", ".join(f"{leak.kind} at {leak.pointer or '(root)'}" for leak in leaks[:5])
        if rules.allow_credentials:
            verdict.findings.append(
                Finding(
                    rule_id="GUARD-PAYLOAD-CREDENTIAL",
                    severity=Severity.WARN,
                    message=(
                        f"the generated payload carries {detail}, and --allow-credential-payloads "
                        "was given, so it was sent"
                    ),
                    operation_key=operation_key,
                    hint=(
                        "The value came out of the contract -- an example, a default or an "
                        "enum member. If it is a real credential, it is now in the target's "
                        "logs as well as in the document."
                    ),
                )
            )
        else:
            verdict.allowed = False
            verdict.findings.append(
                Finding(
                    rule_id="GUARD-PAYLOAD-CREDENTIAL",
                    severity=Severity.ERROR,
                    message=(
                        f"not sent: the generated payload carries {detail}, which this run "
                        "would have posted to the target"
                    ),
                    operation_key=operation_key,
                    hint=(
                        "The value came from the contract, so the first thing to check is the "
                        "document. `apiverity validate` reports committed secrets in examples. "
                        "Pass --allow-credential-payloads if the field is a token field and the "
                        "example is not a real credential."
                    ),
                )
            )

    if verdict.size_bytes > rules.max_bytes:
        verdict.allowed = False
        verdict.findings.append(
            Finding(
                rule_id="GUARD-PAYLOAD-SIZE",
                severity=Severity.WARN,
                message=(
                    f"not sent: the generated payload is {verdict.size_bytes} bytes, over the "
                    f"{rules.max_bytes}-byte guardrail"
                ),
                operation_key=operation_key,
                hint=(
                    "A schema is free to declare `maxLength: 10000000`, and a boundary case "
                    "asking for the largest valid value produces exactly that. Raise the "
                    "guardrail with --max-payload-bytes if the target is meant to take it. "
                    "Truncating instead would run a case that did not test what it says it "
                    "tested."
                ),
            )
        )

    return verdict


__all__ = ["DEFAULT_MAX_BYTES", "Guardrails", "Verdict", "inspect"]
