"""The authentication half of the static security lint.

Two of these rules could never fire. `_effective_security` fell back to
`Service.global_security`, whose default is `[]`, so the "explicitly anonymous"
branch matched every operation in every contract that declared nothing -- and
`SEC-AUTH-MISSING` and `SEC-UNAUTH-WRITE` sat behind it, unreachable, in a tool
whose job is to report exactly that.

The tests are written against the distinction that was collapsed: an empty list
the *document* wrote versus an empty list the *model* defaulted to.
"""

from __future__ import annotations

import pytest

from apiverity.core.model import (
    Operation,
    OperationKind,
    Protocol,
    SecurityRequirement,
    Service,
    Severity,
)
from apiverity.security.checks import run_security_checks


def _ids(service: Service) -> dict[str, Severity]:
    return {f.rule_id: f.severity for f in run_security_checks(service)}


def _openapi(*operations: Operation, **kwargs: object) -> Service:
    return Service(
        title="t", version="1", protocol=Protocol.OPENAPI, operations=list(operations), **kwargs
    )


def _post() -> Operation:
    return Operation(kind=OperationKind.HTTP, method="POST", path="/orders", operation_id="create")


def test_an_unauthenticated_write_is_reported_at_all() -> None:
    """The regression this module exists for: the rule never fired."""
    assert "SEC-UNAUTH-WRITE" in _ids(_openapi(_post()))


def test_an_unauthenticated_write_is_a_warning_not_an_error() -> None:
    """The finding is about the document, not the deployment.

    A gateway may require a token the contract never mentions, and an
    undocumented requirement is indistinguishable from an absent one at this
    distance. A gate that blocks a merge on something it cannot establish is a
    gate someone switches off.
    """
    assert _ids(_openapi(_post()))["SEC-UNAUTH-WRITE"] is Severity.WARN


def test_a_read_with_no_authentication_is_reported_without_the_write_finding() -> None:
    get = Operation(kind=OperationKind.HTTP, method="GET", path="/orders", operation_id="list")
    ids = _ids(_openapi(get))
    assert "SEC-AUTH-MISSING" in ids
    assert "SEC-UNAUTH-WRITE" not in ids


def test_only_a_declared_empty_security_counts_as_explicitly_anonymous() -> None:
    """`security: []` on an operation is a statement; the model default is not."""
    declared = Operation(
        kind=OperationKind.HTTP, method="POST", path="/orders", operation_id="c", security=[]
    )
    ids = _ids(_openapi(declared))
    assert "SEC-AUTH-ANONYMOUS" in ids
    assert "SEC-AUTH-MISSING" not in ids
    assert "SEC-UNAUTH-WRITE" not in ids


def test_a_global_requirement_is_inherited_and_silences_the_finding() -> None:
    service = _openapi(_post(), global_security=[SecurityRequirement(scheme_name="bearer")])
    ids = _ids(service)
    assert "SEC-AUTH-MISSING" not in ids
    assert "SEC-UNAUTH-WRITE" not in ids


@pytest.mark.parametrize(
    ("protocol", "kind"),
    [
        (Protocol.GRPC, OperationKind.GRPC_RPC),
        (Protocol.GRAPHQL, OperationKind.GRAPHQL_FIELD),
        (Protocol.MCP, OperationKind.MCP_TOOL),
    ],
)
def test_a_format_with_nowhere_to_declare_auth_says_so_once(
    protocol: Protocol, kind: OperationKind
) -> None:
    """Not once per operation: no edit to the file could ever clear those."""
    service = Service(
        title="t",
        version="1",
        protocol=protocol,
        operations=[
            Operation(kind=kind, rpc_name="a", service_name="s", operation_id="a"),
            Operation(kind=kind, rpc_name="b", service_name="s", operation_id="b"),
        ],
    )
    findings = run_security_checks(service)
    notes = [f for f in findings if f.rule_id == "SEC-AUTH-NOT-EXPRESSIBLE"]
    assert len(notes) == 1
    assert not [f for f in findings if f.rule_id in {"SEC-AUTH-MISSING", "SEC-AUTH-ANONYMOUS"}]


def test_the_note_refuses_to_be_read_as_a_clean_bill_of_health() -> None:
    service = Service(
        title="t",
        version="1",
        protocol=Protocol.MCP,
        operations=[Operation(kind=OperationKind.MCP_TOOL, rpc_name="a", service_name="s")],
    )
    (note,) = [f for f in run_security_checks(service) if f.rule_id == "SEC-AUTH-NOT-EXPRESSIBLE"]
    assert "not evidence that this service is open" in note.message


def test_a_format_this_adapter_does_not_read_is_a_different_claim() -> None:
    """AsyncAPI documents *can* declare security; this build does not read it.

    Reporting that as "the format cannot express authentication" would blame
    the contract for a gap in the loader.
    """
    service = Service(
        title="t",
        version="1",
        protocol=Protocol.ASYNCAPI,
        operations=[Operation(kind=OperationKind.EVENT, operation_id="e")],
    )
    ids = _ids(service)
    assert "SEC-AUTH-NOT-READ" in ids
    assert "SEC-AUTH-NOT-EXPRESSIBLE" not in ids
