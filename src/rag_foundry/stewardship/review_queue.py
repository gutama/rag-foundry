"""Curator review queue (FR12, ADR-0014, ADR-0022).

Items enter the queue automatically: pending resolution candidates,
assertions that pass validation, and approved assertions flagged by a
split or a failed revalidation. Stewards approve or reject them here; each
decision records actor, time, reason and the item's semantic profile, and
is carried out through the owning service, so the candidate or assertion
and its item always agree.

Approval rules:

- a resolution candidate is approved through ``ResolutionService``;
- a validated assertion is approved only if its latest validation passed
  against its pinned release and every cited evidence chunk still resolves
  in its workspace (extracted assertions must cite at least one);
- a flagged assertion cannot be approved here: revalidating it clears the
  flag when the cause is fixed. Rejecting it retires (supersedes) it.

Approving an approved item again has no further effect.
"""

import uuid
from datetime import datetime
from typing import Iterable, List, Literal, Optional

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rag_foundry.assertions.curation import CurationService
from rag_foundry.assertions.lifecycle import AssertionStore, require_actor
from rag_foundry.assertions.validation import AssertionValidator
from rag_foundry.db.models import AssertionRecord, Chunk, ReviewItemRecord
from rag_foundry.entities.resolution import ResolutionService
from rag_foundry.entities.store import as_utc
from rag_foundry.stewardship.queue_records import (
    ASSERTION_KIND,
    CANDIDATE_KIND,
    settle,
)

ReviewKind = Literal["resolution_candidate", "assertion"]
ReviewStatus = Literal["open", "approved", "rejected", "closed"]


class ReviewError(Exception):
    """Base class for review queue errors."""


class ReviewItemNotFoundError(ReviewError):
    """Raised when an item id is unknown."""


class ReviewStateError(ReviewError):
    """Raised when an item cannot take the requested decision."""


class ReviewRefusedError(ReviewError):
    """Raised when governance rules forbid approving an item."""


class ReviewItem(BaseModel):
    """An item awaiting, or decided by, a steward."""

    id: uuid.UUID = Field(description="Item id")
    kind: ReviewKind = Field(description="What needs review")
    target_id: uuid.UUID = Field(description="Candidate or assertion id")
    workspace_id: uuid.UUID = Field(description="Workspace")
    semantic_profile_id: uuid.UUID = Field(description="Semantic profile")
    status: ReviewStatus = Field(description="Item status")
    reason: str = Field(description="Why it was queued")
    created_at: datetime = Field(description="When it was queued")
    decided_by: Optional[str] = Field(description="Who decided")
    decided_at: Optional[datetime] = Field(description="When")
    decision_reason: Optional[str] = Field(description="Why")


def _item_from_record(record: ReviewItemRecord) -> ReviewItem:
    """Convert an item record to a model."""
    return ReviewItem(
        id=record.id,
        kind=record.kind,
        target_id=record.target_id,
        workspace_id=record.workspace_id,
        semantic_profile_id=record.semantic_profile_id,
        status=record.status,
        reason=record.reason,
        created_at=as_utc(record.created_at),
        decided_by=record.decided_by,
        decided_at=(
            None if record.decided_at is None else as_utc(record.decided_at)
        ),
        decision_reason=record.decision_reason,
    )


class ReviewQueue:
    """Lists review items and carries out steward decisions."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the queue.

        Args:
            session: SQLAlchemy AsyncSession.
        """
        self.session = session

    async def list_items(
        self,
        workspace_id: Optional[uuid.UUID] = None,
        kind: Optional[str] = None,
        statuses: Optional[Iterable[str]] = ("open",),
    ) -> List[ReviewItem]:
        """List items, oldest first.

        Args:
            workspace_id: Only this workspace.
            kind: Only this kind.
            statuses: Only these statuses; None for every status.

        Returns:
            Matching items.
        """
        stmt = select(ReviewItemRecord).order_by(
            ReviewItemRecord.created_at, ReviewItemRecord.id
        )
        if workspace_id is not None:
            stmt = stmt.where(ReviewItemRecord.workspace_id == workspace_id)
        if kind is not None:
            stmt = stmt.where(ReviewItemRecord.kind == kind)
        if statuses is not None:
            stmt = stmt.where(ReviewItemRecord.status.in_(list(statuses)))
        records = (await self.session.execute(stmt)).scalars().all()
        return [_item_from_record(r) for r in records]

    async def get_item(self, item_id: uuid.UUID) -> ReviewItem:
        """Load an item.

        Raises:
            ReviewItemNotFoundError: If the item does not exist.
        """
        return _item_from_record(await self._record(item_id))

    async def approve(
        self,
        item_id: uuid.UUID,
        actor_id: str,
        reason: Optional[str] = None,
    ) -> ReviewItem:
        """Approve an item's target.

        Args:
            item_id: Item id.
            actor_id: Steward deciding.
            reason: Why.

        Returns:
            The decided item; an already approved item is returned as is.

        Raises:
            ValueError: If the actor is blank.
            ReviewItemNotFoundError: If the item does not exist.
            ReviewStateError: If the item was rejected or closed.
            ReviewRefusedError: If governance rules forbid the approval.
        """
        require_actor(actor_id)
        record = await self._record(item_id)
        if record.status == "approved":
            return _item_from_record(record)
        self._require_open(record)
        if record.kind == CANDIDATE_KIND:
            await ResolutionService(self.session).approve_candidate(
                record.target_id, actor_id=actor_id, reason=reason
            )
        else:
            assertion = await AssertionStore(self.session).load_record(
                record.target_id
            )
            await self._check_approvable(assertion)
            await AssertionStore(self.session).transition(
                assertion.id, "approved", actor_id=actor_id, reason=reason
            )
        return await self.get_item(item_id)

    async def reject(
        self,
        item_id: uuid.UUID,
        actor_id: str,
        reason: Optional[str] = None,
    ) -> ReviewItem:
        """Reject an item's target.

        A validated assertion becomes ``rejected``; a flagged approved
        assertion is retired (``superseded``) without replacement.

        Args:
            item_id: Item id.
            actor_id: Steward deciding.
            reason: Why.

        Returns:
            The decided item.

        Raises:
            ValueError: If the actor is blank.
            ReviewItemNotFoundError: If the item does not exist.
            ReviewStateError: If the item is not open.
        """
        require_actor(actor_id)
        record = await self._record(item_id)
        self._require_open(record)
        if record.kind == CANDIDATE_KIND:
            await ResolutionService(self.session).reject_candidate(
                record.target_id, actor_id=actor_id, reason=reason
            )
            return await self.get_item(item_id)
        assertion = await AssertionStore(self.session).load_record(
            record.target_id
        )
        if assertion.status == "approved":
            await settle(self.session, ASSERTION_KIND, assertion.id,
                         "rejected", actor_id, reason)
            await CurationService(self.session).supersede(
                assertion.id, None, actor_id=actor_id,
                reason=reason or "Rejected in review",
            )
        else:
            await AssertionStore(self.session).transition(
                assertion.id, "rejected", actor_id=actor_id, reason=reason
            )
        return await self.get_item(item_id)

    # --- Helpers ----------------------------------------------------------

    async def _record(self, item_id: uuid.UUID) -> ReviewItemRecord:
        """Load an item record.

        Raises:
            ReviewItemNotFoundError: If the item does not exist.
        """
        record = await self.session.get(ReviewItemRecord, item_id)
        if record is None:
            raise ReviewItemNotFoundError(f"Review item {item_id} not found")
        return record

    @staticmethod
    def _require_open(record: ReviewItemRecord) -> None:
        """Refuse decisions on items that are no longer open.

        Raises:
            ReviewStateError: If the item is not open.
        """
        if record.status != "open":
            raise ReviewStateError(
                f"Review item {record.id} is {record.status}"
            )

    async def _check_approvable(self, assertion: AssertionRecord) -> None:
        """Apply the approval rules for an assertion.

        Raises:
            ReviewRefusedError: If the assertion is flagged, its latest
                validation failed or does not match its pinned release, or
                its evidence no longer resolves.
        """
        if assertion.requires_review:
            raise ReviewRefusedError(
                f"Assertion {assertion.id} is flagged: "
                f"{assertion.review_reason}. Revalidate it once the cause "
                "is fixed, or reject it"
            )
        report = await AssertionValidator(self.session).latest_report(
            assertion.id
        )
        if (
            report is None
            or not report.valid
            or report.ontology_release_id != assertion.ontology_release_id
        ):
            raise ReviewRefusedError(
                f"Assertion {assertion.id} has no passing validation for "
                "its pinned ontology release"
            )
        chunk_ids = [uuid.UUID(c) for c in assertion.source_chunk_ids]
        if not chunk_ids and assertion.origin == "extracted":
            raise ReviewRefusedError(
                f"Extracted assertion {assertion.id} cites no evidence"
            )
        stmt = select(Chunk.id).where(
            Chunk.id.in_(chunk_ids),
            Chunk.workspace_id == assertion.workspace_id,
        )
        found = set((await self.session.execute(stmt)).scalars().all())
        missing = [c for c in chunk_ids if c not in found]
        if missing:
            raise ReviewRefusedError(
                f"Evidence of assertion {assertion.id} no longer resolves: "
                f"{missing}"
            )
