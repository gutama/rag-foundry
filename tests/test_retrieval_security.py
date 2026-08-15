"""Unit tests for Authorization-Before-Retrieval security guard (ADR-0016)."""

import uuid
import pytest

from rag_foundry.retrieval.models import RetrievalFilter, RetrievalQuery


def test_security_context_model():
    """Test SecurityContext instantiation and permission check helpers."""
    from rag_foundry.retrieval.security import SecurityContext

    user_id = str(uuid.uuid4())
    ws_1 = uuid.uuid4()
    ws_2 = uuid.uuid4()

    sec_ctx = SecurityContext(
        user_id=user_id,
        allowed_workspaces=[ws_1, ws_2],
        allowed_security_domains=["finance", "public"],
        roles=["analyst"],
    )

    assert sec_ctx.can_access_workspace(ws_1) is True
    assert sec_ctx.can_access_workspace(uuid.uuid4()) is False
    assert sec_ctx.can_access_domain("finance") is True
    assert sec_ctx.can_access_domain("secret_hr") is False


def test_workspace_guard_authorized_query():
    """Test WorkspaceGuard passes queries when workspace and domains are permitted."""
    from rag_foundry.retrieval.security import SecurityContext, WorkspaceGuard

    ws_id = uuid.uuid4()
    sec_ctx = SecurityContext(
        user_id="user_123",
        allowed_workspaces=[ws_id],
        allowed_security_domains=["governance", "public"],
    )

    guard = WorkspaceGuard()
    query = RetrievalQuery(
        query_text="Show ESG metrics",
        filter=RetrievalFilter(
            workspace_id=ws_id,
            security_domains=["governance"],
        ),
    )

    validated_query = guard.validate_and_sanitize_query(query, sec_ctx)
    assert validated_query.filter.workspace_id == ws_id
    assert validated_query.filter.security_domains == ["governance"]


def test_workspace_guard_rejects_unauthorized_workspace():
    """Test WorkspaceGuard raises SecurityAuthorizationError for unauthorized workspaces."""
    from rag_foundry.retrieval.security import (
        SecurityAuthorizationError,
        SecurityContext,
        WorkspaceGuard,
    )

    allowed_ws = uuid.uuid4()
    forbidden_ws = uuid.uuid4()

    sec_ctx = SecurityContext(
        user_id="user_123",
        allowed_workspaces=[allowed_ws],
        allowed_security_domains=["public"],
    )

    guard = WorkspaceGuard()
    query = RetrievalQuery(
        query_text="Leak data",
        filter=RetrievalFilter(workspace_id=forbidden_ws),
    )

    with pytest.raises(SecurityAuthorizationError) as exc_info:
        guard.validate_and_sanitize_query(query, sec_ctx)

    assert "Unauthorized workspace access" in str(exc_info.value)


def test_workspace_guard_rejects_unauthorized_domains():
    """Test WorkspaceGuard raises SecurityAuthorizationError when requesting forbidden domains."""
    from rag_foundry.retrieval.security import (
        SecurityAuthorizationError,
        SecurityContext,
        WorkspaceGuard,
    )

    ws_id = uuid.uuid4()
    sec_ctx = SecurityContext(
        user_id="user_123",
        allowed_workspaces=[ws_id],
        allowed_security_domains=["public"],
    )

    guard = WorkspaceGuard()
    query = RetrievalQuery(
        query_text="Confidential executive compensation",
        filter=RetrievalFilter(
            workspace_id=ws_id,
            security_domains=["executive_confidential"],
        ),
    )

    with pytest.raises(SecurityAuthorizationError) as exc_info:
        guard.validate_and_sanitize_query(query, sec_ctx)

    assert "Unauthorized security domain" in str(exc_info.value)
