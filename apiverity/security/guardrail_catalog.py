"""The outbound guardrails, for `explain` and the generated catalogue.

Both are about what this tool must not *do*. Neither is a finding about the
target: a payload that is not sent has told you nothing about the service.
"""

from __future__ import annotations

from apiverity.core.model import Severity
from apiverity.rules.check_catalog import CheckRuleSpec
from apiverity.rules.check_catalog import spec as _spec

_FAMILY = "Outbound guardrails"
_BY = "test"

GUARDRAIL_CATALOG: dict[str, CheckRuleSpec] = dict(
    [
        _spec(
            "GUARD-PAYLOAD-CREDENTIAL",
            Severity.ERROR,
            "a generated payload carried something credential-shaped, and was not sent",
            "check the contract first: the value came from an example, a default or an "
            "enum member, and `apiverity validate` reports committed secrets in "
            "examples. If the field is a token field and the example is not a real "
            "credential, pass --allow-credential-payloads. The check runs before the "
            "request rather than after it, because a finding about a credential this "
            "process already posted is a finding about something nobody can take back",
            _BY,
            _FAMILY,
        ),
        _spec(
            "GUARD-PAYLOAD-SIZE",
            Severity.WARN,
            "a generated payload was larger than the outbound guardrail, and was not sent",
            "raise it with --max-payload-bytes if the target is meant to take a body "
            "that size. `maxLength: 10000000` is a legal schema and a boundary case "
            "asking for the largest valid value produces exactly that, which is a "
            "denial of service somebody wrote by running a test suite. The payload is "
            "refused rather than truncated: a shortened case is a case that did not "
            "test what it says it tested",
            _BY,
            _FAMILY,
        ),
    ]
)

__all__ = ["GUARDRAIL_CATALOG"]
