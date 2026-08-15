"""Authorization-Before-Retrieval security guard and tenancy isolation service."""

import uuid
from typing import List, Optional

from pydantic import BaseModel, Field

from rag_foundry.retrieval.models import RetrievalQuery


class SecurityAuthorizationError(PermissionError):
    """Raised when an actor attempts retrieval against unauthorized workspaces or domains."""

    pass


class SecurityContext(BaseModel):
    """Context holding actor credentials, allowed workspaces, and security domains."""

    user_id: str = Field(description="Unique actor or service account identifier")
    allowed_workspaces: List[uuid.UUID] = Field(
        default_factory=list, description="Whitelisted workspace IDs"
    )
    allowed_security_domains: List[str] = Field(
        default_factory=list,
        description="Whitelisted security classification domains (e.g. ['public', 'internal'])",
    )
    roles: List[str] = Field(
        default_factory=list, description="Actor roles (e.g. ['analyst', 'admin'])"
    )

    def can_access_workspace(self, workspace_id: uuid.UUID) -> bool:
        """Check if the security context has access to the given workspace."""
        return workspace_id in self.allowed_workspaces

    def can_access_domain(self, domain: str) -> bool:
        """Check if the security context is permitted to access a given domain."""
        return domain in self.allowed_security_domains


class WorkspaceGuard:
    """Enforces authorization before retrieval execution to prevent data leakage."""

    def validate_and_sanitize_query(
        self,
        query: RetrievalQuery,
        security_context: SecurityContext,
    ) -> RetrievalQuery:
        """Validate query workspace and security domains against the provided security context.

        Args:
            query: The proposed RetrievalQuery.
            security_context: The actor's SecurityContext.

        Returns:
            The validated (and sanitized) RetrievalQuery.

        Raises:
            SecurityAuthorizationError: If workspace or security domain access is denied.
        """
        # 1. Validate workspace isolation
        if not security_context.can_access_workspace(query.filter.workspace_id):
            raise SecurityAuthorizationError(
                f"Unauthorized workspace access: user '{security_context.user_id}' "
                f"is not authorized for workspace '{query.filter.workspace_id}'."
            )

        # 2. Validate requested security domains
        if query.filter.security_domains:
            for domain in query.filter.security_domains:
                if not security_context.can_access_domain(domain):
                    raise SecurityAuthorizationError(
                        f"Unauthorized security domain: user '{security_context.user_id}' "
                        f"is not authorized for domain '{domain}'."
                    )
        else:
            # If no specific domains requested in query filter, populate with actor's allowed domains
            query.filter.security_domains = list(security_context.allowed_security_domains)

        return query
