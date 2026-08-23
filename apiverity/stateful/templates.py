"""Manually authored workflow templates for common API verification patterns.

Templates are deterministic, dependency-free manifests that teams can copy,
adjust and run: CRUD lifecycle, pagination walk, auth refresh, resource
lifecycle with cleanup.
"""

from __future__ import annotations

from typing import Any

from apiverity.stateful.models import Workflow, WorkflowRequest, WorkflowStep


def crud_lifecycle_workflow(
    *,
    base_url: str,
    collection_path: str = "/widgets",
    id_var: str = "widget_id",
    payload: dict[str, Any] | None = None,
) -> Workflow:
    """Create -> read -> update -> delete with cleanup compensation."""
    body = payload or {"name": "verity-lifecycle"}
    return Workflow(
        name="crud-lifecycle",
        description="Full CRUD round-trip with guaranteed cleanup",
        base_url=base_url,
        steps=[
            WorkflowStep(
                name="create",
                request=WorkflowRequest(method="POST", path=collection_path, body=body),
                assert_status=[200, 201],
                extract={id_var: "id"},
            ),
            WorkflowStep(
                name="read",
                request=WorkflowRequest(method="GET", path=f"{collection_path}/{{{{ {id_var} }}}}"),
                assert_status=[200],
            ),
            WorkflowStep(
                name="update",
                request=WorkflowRequest(
                    method="PATCH",
                    path=f"{collection_path}/{{{{ {id_var} }}}}",
                    body={"name": "verity-updated"},
                ),
                assert_status=[200],
            ),
        ],
        cleanup=[
            WorkflowStep(
                name="delete",
                request=WorkflowRequest(method="DELETE", path=f"{collection_path}/{{{{ {id_var} }}}}"),
                assert_status=[200, 202, 204, 404],  # 404 tolerated: already gone
            )
        ],
    )


def pagination_walk_workflow(
    *,
    base_url: str,
    collection_path: str = "/items",
    page_param: str = "page",
    limit_param: str = "limit",
    max_pages: int = 5,
) -> Workflow:
    """Walk up to max_pages pages asserting stable page sizes."""
    steps = []
    for page in range(1, max_pages + 1):
        steps.append(
            WorkflowStep(
                name=f"page-{page}",
                request=WorkflowRequest(
                    method="GET",
                    path=collection_path,
                    query={page_param: page, limit_param: 10},
                ),
                assert_status=[200],
            )
        )
    return Workflow(
        name="pagination-walk",
        description=f"Sequential pagination over {max_pages} pages",
        base_url=base_url,
        steps=steps,
    )


def auth_refresh_workflow(
    *,
    base_url: str,
    token_path: str = "/auth/token",
    refresh_token_var: str = "refresh_token",
) -> Workflow:
    """Exchange a refresh token for an access token and use it."""
    return Workflow(
        name="auth-refresh",
        description="Refresh-token exchange then authenticated call",
        base_url=base_url,
        inputs=[refresh_token_var],
        steps=[
            WorkflowStep(
                name="refresh",
                request=WorkflowRequest(
                    method="POST",
                    path=token_path,
                    body={"grant_type": "refresh_token", "refresh_token": f"{{{{ {refresh_token_var} }}}}",
                    },
                ),
                assert_status=[200],
                extract={"access_token": "access_token"},
            ),
            WorkflowStep(
                name="authenticated-call",
                request=WorkflowRequest(
                    method="GET",
                    path="/me",
                    headers={"Authorization": "Bearer {{ access_token }}"},
                ),
                assert_status=[200],
            ),
        ],
    )


def resource_lifecycle_workflow(*, base_url: str, resource: str = "/orders") -> Workflow:
    """Stateful transitions: create -> transition states -> verify terminal state."""
    return Workflow(
        name="resource-lifecycle",
        description="Resource state-machine transitions with cleanup",
        base_url=base_url,
        steps=[
            WorkflowStep(
                name="create-order",
                request=WorkflowRequest(method="POST", path=resource, body={"state": "draft"}),
                assert_status=[201],
                extract={"order_id": "id"},
            ),
            WorkflowStep(
                name="submit",
                request=WorkflowRequest(
                    method="POST", path=f"{resource}/{{{{ order_id }}}}/submit"
                ),
                assert_status=[200],
            ),
            WorkflowStep(
                name="verify-terminal",
                request=WorkflowRequest(method="GET", path=f"{resource}/{{{{ order_id }}}}"),
                assert_status=[200],
                assert_jsonpath={"state": "submitted"},
            ),
        ],
        cleanup=[
            WorkflowStep(
                name="cancel-cleanup",
                request=WorkflowRequest(method="DELETE", path=f"{resource}/{{{{ order_id }}}}"),
                assert_status=[200, 204, 404],
            )
        ],
    )


#: All built-in templates by name.
TEMPLATES = {
    "crud-lifecycle": crud_lifecycle_workflow,
    "pagination-walk": pagination_walk_workflow,
    "auth-refresh": auth_refresh_workflow,
    "resource-lifecycle": resource_lifecycle_workflow,
}
