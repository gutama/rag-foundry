"""Audit trail for semantic governance actions (FR13, ADR-0012/0014).

The services record an ``AuditEvent`` for every merge (``entity.merged``),
split (``entity.split``), resolution decision (``resolution.decision``) and
assertion status change, creation included (``assertion.transition``). The
writer depends only on the ORM, so those services can call it without
circular imports. Events are append-only; nothing here edits or deletes
them.
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rag_foundry.db.models import AuditEvent


class AuditRecord(BaseModel):
    """One audit event."""

    id: uuid.UUID = Field(description="Event id")
    event_type: str = Field(description="What happened")
    actor_id: str = Field(description="Who did it")
    resource_type: str = Field(description="Kind of resource affected")
    resource_id: str = Field(description="Id of the resource affected")
    details: Dict[str, Any] = Field(description="Event specifics")
    timestamp: datetime = Field(description="When")


def _json_ready(value: Any) -> Any:
    """Turn UUIDs (also inside lists and dicts) into strings."""
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dict):
        return {k: _json_ready(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(v) for v in value]
    return value


async def record_audit(
    session: AsyncSession,
    event_type: str,
    actor_id: str,
    resource_type: str,
    resource_id: uuid.UUID,
    details: Dict[str, Any],
) -> None:
    """Append an audit event.

    Args:
        session: Database session.
        event_type: What happened, e.g. ``entity.merged``.
        actor_id: Who did it.
        resource_type: Kind of resource, e.g. ``entity``.
        resource_id: Id of the resource.
        details: Event specifics; UUIDs are stored as strings.
    """
    session.add(
        AuditEvent(
            event_type=event_type,
            actor_id=actor_id,
            resource_type=resource_type,
            resource_id=str(resource_id),
            details=_json_ready(details),
            timestamp=datetime.now(timezone.utc),
        )
    )


class AuditTrail:
    """Reads the audit trail."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the reader.

        Args:
            session: SQLAlchemy AsyncSession.
        """
        self.session = session

    async def list_events(
        self,
        event_type: Optional[str] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[Union[uuid.UUID, str]] = None,
    ) -> List[AuditRecord]:
        """List audit events, oldest first.

        Args:
            event_type: Only this event type.
            resource_type: Only this resource type.
            resource_id: Only this resource.

        Returns:
            Matching events.
        """
        stmt = select(AuditEvent).order_by(
            AuditEvent.timestamp, AuditEvent.id
        )
        if event_type is not None:
            stmt = stmt.where(AuditEvent.event_type == event_type)
        if resource_type is not None:
            stmt = stmt.where(AuditEvent.resource_type == resource_type)
        if resource_id is not None:
            stmt = stmt.where(AuditEvent.resource_id == str(resource_id))
        records = (await self.session.execute(stmt)).scalars().all()
        return [
            AuditRecord(
                id=r.id,
                event_type=r.event_type,
                actor_id=r.actor_id,
                resource_type=r.resource_type,
                resource_id=r.resource_id,
                details=r.details,
                timestamp=(
                    r.timestamp if r.timestamp.tzinfo is not None
                    else r.timestamp.replace(tzinfo=timezone.utc)
                ),
            )
            for r in records
        ]
