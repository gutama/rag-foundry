"""Low-level review queue bookkeeping shared by the semantic services.

The services that create reviewable work (resolution, assertion lifecycle,
validation, lineage) keep the queue in step through these helpers, so an
item can never stay open after its target was decided elsewhere. The module
depends only on the ORM models, which lets those services use it without
circular imports; the steward-facing API lives in ``review_queue.py``.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rag_foundry.db.models import ReviewItemRecord

CANDIDATE_KIND = "resolution_candidate"
ASSERTION_KIND = "assertion"


async def open_item(
    session: AsyncSession, kind: str, target_id: uuid.UUID
) -> Optional[ReviewItemRecord]:
    """Return the open item for a target, if any."""
    stmt = select(ReviewItemRecord).where(
        ReviewItemRecord.kind == kind,
        ReviewItemRecord.target_id == target_id,
        ReviewItemRecord.status == "open",
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def enqueue(
    session: AsyncSession,
    kind: str,
    target_id: uuid.UUID,
    workspace_id: uuid.UUID,
    semantic_profile_id: uuid.UUID,
    reason: str,
) -> ReviewItemRecord:
    """Open an item for a target, or refresh the reason of the open one.

    Args:
        session: Database session.
        kind: Item kind.
        target_id: Candidate or assertion id.
        workspace_id: Workspace of the target.
        semantic_profile_id: Semantic profile of the target.
        reason: Why it needs review.

    Returns:
        The open item.
    """
    existing = await open_item(session, kind, target_id)
    if existing is not None:
        existing.reason = reason
        return existing
    record = ReviewItemRecord(
        kind=kind,
        target_id=target_id,
        workspace_id=workspace_id,
        semantic_profile_id=semantic_profile_id,
        status="open",
        reason=reason,
        created_at=datetime.now(timezone.utc),
    )
    session.add(record)
    return record


async def settle(
    session: AsyncSession,
    kind: str,
    target_id: uuid.UUID,
    status: str,
    actor_id: str,
    reason: Optional[str] = None,
) -> None:
    """Record the outcome on a target's open item, if there is one.

    Args:
        session: Database session.
        kind: Item kind.
        target_id: Candidate or assertion id.
        status: ``approved``, ``rejected`` or ``closed``.
        actor_id: Who decided.
        reason: Why.
    """
    record = await open_item(session, kind, target_id)
    if record is None:
        return
    record.status = status
    record.decided_by = actor_id
    record.decided_at = datetime.now(timezone.utc)
    record.decision_reason = reason
