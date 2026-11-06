"""Assertion lifecycle and storage (ADR-0014).

The lifecycle is an explicit state machine::

    candidate -> validated | invalid
    validated -> approved | rejected | invalid   (re-validation can fail)
    approved  -> superseded
    invalid, rejected, superseded: terminal

Every status change, including creation, appends an entry with actor,
reason and time to ``assertion_transitions``; entries are never edited or
deleted. ``superseded`` is reserved for the dedicated supersede operation,
which enforces the curated-versus-extracted rules of ADR-0013.

Becoming ``validated`` puts the assertion in the steward review queue;
leaving that state settles its review item with the same actor and reason.

Methods flush but never commit; the caller owns the transaction.
"""

import uuid
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Set

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from rag_foundry.assertions.models import (
    AssertionTransition,
    LiteralValue,
    SemanticAssertion,
)
from rag_foundry.db.models import (
    AssertionRecord,
    AssertionTransitionRecord,
    EntityRecord,
)
from rag_foundry.entities.store import EntityNotFoundError, as_utc
from rag_foundry.stewardship.queue_records import (
    ASSERTION_KIND,
    enqueue,
    settle,
)

ALLOWED_TRANSITIONS: Dict[str, Set[str]] = {
    "candidate": {"validated", "invalid"},
    "validated": {"approved", "rejected", "invalid"},
    "approved": {"superseded"},
    "invalid": set(),
    "rejected": set(),
    "superseded": set(),
}


class SemanticAssertionError(Exception):
    """Base class for assertion errors."""


class AssertionNotFoundError(SemanticAssertionError):
    """Raised when an assertion id is unknown."""


class InvalidTransitionError(SemanticAssertionError):
    """Raised for a status change outside the state machine."""


class AssertionStateError(SemanticAssertionError):
    """Raised when an operation does not fit the assertion's state."""


def check_transition(current: str, target: str) -> None:
    """Check a status change against the state machine.

    Args:
        current: Current status.
        target: Requested status.

    Raises:
        InvalidTransitionError: If the change is not allowed.
    """
    if target not in ALLOWED_TRANSITIONS.get(current, set()):
        raise InvalidTransitionError(
            f"An assertion cannot go from {current} to {target}"
        )


def require_actor(actor_id: str) -> str:
    """Reject blank actor ids.

    Raises:
        ValueError: If the actor id is blank.
    """
    if not actor_id.strip():
        raise ValueError("Assertion changes must name the actor")
    return actor_id


def _optional_utc(value: Optional[datetime]) -> Optional[datetime]:
    """Attach UTC to a naive timestamp, keeping None."""
    return None if value is None else as_utc(value)


def assertion_from_record(record: AssertionRecord) -> SemanticAssertion:
    """Convert an assertion record to a model.

    Args:
        record: The ORM record.

    Returns:
        The assertion model.
    """
    return SemanticAssertion(
        id=record.id,
        workspace_id=record.workspace_id,
        semantic_profile_id=record.semantic_profile_id,
        subject_entity_id=record.subject_entity_id,
        property_uri=record.property_uri,
        object_entity_id=record.object_entity_id,
        literal_value=record.literal_value,
        source_chunk_ids=[uuid.UUID(c) for c in record.source_chunk_ids],
        origin=record.origin,
        extraction_method=record.extraction_method,
        extraction_model=record.extraction_model,
        extraction_prompt_version=record.extraction_prompt_version,
        confidence=record.confidence,
        status=record.status,
        ontology_release_id=record.ontology_release_id,
        requires_review=record.requires_review,
        review_reason=record.review_reason,
        superseded_by_id=record.superseded_by_id,
        valid_from=_optional_utc(record.valid_from),
        valid_to=_optional_utc(record.valid_to),
        created_at=as_utc(record.created_at),
    )


class AssertionStore:
    """Creates assertions and moves them through their lifecycle."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the store with an AsyncSession.

        Args:
            session: SQLAlchemy AsyncSession.
        """
        self.session = session

    async def create_assertion(
        self,
        actor_id: str,
        workspace_id: uuid.UUID,
        semantic_profile_id: uuid.UUID,
        subject_entity_id: uuid.UUID,
        property_uri: str,
        origin: str,
        extraction_method: str,
        confidence: float,
        source_chunk_ids: Optional[List[uuid.UUID]] = None,
        object_entity_id: Optional[uuid.UUID] = None,
        literal_value: Optional[LiteralValue] = None,
        extraction_model: Optional[str] = None,
        extraction_prompt_version: Optional[str] = None,
        valid_from: Optional[datetime] = None,
        valid_to: Optional[datetime] = None,
        reason: Optional[str] = None,
    ) -> SemanticAssertion:
        """Create a candidate assertion and log its creation.

        Args:
            actor_id: Who created it (extractor, steward, import job).
            workspace_id: Owning workspace.
            semantic_profile_id: Semantic profile.
            subject_entity_id: Subject entity.
            property_uri: Property IRI.
            origin: ``curated`` or ``extracted``.
            extraction_method: How it was produced.
            confidence: Confidence between 0 and 1.
            source_chunk_ids: Evidence chunks.
            object_entity_id: Object entity, for object properties.
            literal_value: Literal, for data properties.
            extraction_model: Model used, if any.
            extraction_prompt_version: Prompt version, if any.
            valid_from: Start of validity.
            valid_to: End of validity.
            reason: Note recorded with the creation entry.

        Returns:
            The new candidate assertion.

        Raises:
            ValueError: If the actor or a field is invalid.
            EntityNotFoundError: If the subject or object does not exist.
        """
        require_actor(actor_id)
        assertion = SemanticAssertion(
            workspace_id=workspace_id,
            semantic_profile_id=semantic_profile_id,
            subject_entity_id=subject_entity_id,
            property_uri=property_uri,
            object_entity_id=object_entity_id,
            literal_value=literal_value,
            source_chunk_ids=source_chunk_ids or [],
            origin=origin,
            extraction_method=extraction_method,
            extraction_model=extraction_model,
            extraction_prompt_version=extraction_prompt_version,
            confidence=confidence,
            valid_from=valid_from,
            valid_to=valid_to,
        )
        for entity_id in (subject_entity_id, object_entity_id):
            if entity_id is not None and await self.session.get(
                EntityRecord, entity_id
            ) is None:
                raise EntityNotFoundError(f"Entity {entity_id} not found")
        record = AssertionRecord(
            id=assertion.id,
            workspace_id=assertion.workspace_id,
            semantic_profile_id=assertion.semantic_profile_id,
            subject_entity_id=assertion.subject_entity_id,
            property_uri=assertion.property_uri,
            object_entity_id=assertion.object_entity_id,
            literal_value=assertion.literal_value,
            source_chunk_ids=[str(c) for c in assertion.source_chunk_ids],
            origin=assertion.origin,
            extraction_method=assertion.extraction_method,
            extraction_model=assertion.extraction_model,
            extraction_prompt_version=assertion.extraction_prompt_version,
            confidence=assertion.confidence,
            status=assertion.status,
            requires_review=False,
            valid_from=assertion.valid_from,
            valid_to=assertion.valid_to,
            created_at=assertion.created_at,
            updated_at=assertion.created_at,
        )
        self.session.add(record)
        self.session.add(
            AssertionTransitionRecord(
                assertion=record,
                sequence=1,
                from_status=None,
                to_status=assertion.status,
                actor_id=actor_id,
                reason=reason,
                created_at=assertion.created_at,
            )
        )
        await self.session.flush()
        return assertion

    async def get_assertion(
        self, assertion_id: uuid.UUID
    ) -> SemanticAssertion:
        """Load an assertion.

        Raises:
            AssertionNotFoundError: If the assertion does not exist.
        """
        return assertion_from_record(await self.load_record(assertion_id))

    async def list_assertions(
        self,
        entity_id: Optional[uuid.UUID] = None,
        statuses: Optional[Iterable[str]] = None,
        workspace_id: Optional[uuid.UUID] = None,
        property_uri: Optional[str] = None,
    ) -> List[SemanticAssertion]:
        """List assertions, oldest first.

        Args:
            entity_id: Only assertions with this subject or object.
            statuses: Only these statuses.
            workspace_id: Only this workspace.
            property_uri: Only this property.

        Returns:
            Matching assertions.
        """
        stmt = select(AssertionRecord).order_by(
            AssertionRecord.created_at, AssertionRecord.id
        )
        if entity_id is not None:
            stmt = stmt.where(
                or_(
                    AssertionRecord.subject_entity_id == entity_id,
                    AssertionRecord.object_entity_id == entity_id,
                )
            )
        if statuses is not None:
            stmt = stmt.where(AssertionRecord.status.in_(list(statuses)))
        if workspace_id is not None:
            stmt = stmt.where(AssertionRecord.workspace_id == workspace_id)
        if property_uri is not None:
            stmt = stmt.where(AssertionRecord.property_uri == property_uri)
        records = (await self.session.execute(stmt)).scalars().all()
        return [assertion_from_record(r) for r in records]

    async def transition(
        self,
        assertion_id: uuid.UUID,
        to_status: str,
        actor_id: str,
        reason: Optional[str] = None,
    ) -> SemanticAssertion:
        """Move an assertion to a new status and log the change.

        Args:
            assertion_id: Assertion id.
            to_status: Target status; ``superseded`` is not accepted here.
            actor_id: Who makes the change.
            reason: Why.

        Returns:
            The updated assertion.

        Raises:
            ValueError: If the actor is blank.
            AssertionStateError: If the target is ``superseded``.
            AssertionNotFoundError: If the assertion does not exist.
            InvalidTransitionError: If the change is not allowed.
        """
        require_actor(actor_id)
        if to_status == "superseded":
            raise AssertionStateError(
                "Use supersede() to replace an approved assertion"
            )
        record = await self.load_record(assertion_id)
        await self.apply_transition(record, to_status, actor_id, reason)
        return assertion_from_record(record)

    async def list_transitions(
        self, assertion_id: uuid.UUID
    ) -> List[AssertionTransition]:
        """List an assertion's status log in order.

        Args:
            assertion_id: Assertion id.

        Returns:
            Log entries, creation first.
        """
        stmt = (
            select(AssertionTransitionRecord)
            .where(AssertionTransitionRecord.assertion_id == assertion_id)
            .order_by(AssertionTransitionRecord.sequence)
        )
        records = (await self.session.execute(stmt)).scalars().all()
        return [
            AssertionTransition(
                id=r.id,
                assertion_id=r.assertion_id,
                sequence=r.sequence,
                from_status=r.from_status,
                to_status=r.to_status,
                actor_id=r.actor_id,
                reason=r.reason,
                created_at=as_utc(r.created_at),
            )
            for r in records
        ]

    async def load_record(self, assertion_id: uuid.UUID) -> AssertionRecord:
        """Load an assertion record.

        Raises:
            AssertionNotFoundError: If the assertion does not exist.
        """
        record = await self.session.get(AssertionRecord, assertion_id)
        if record is None:
            raise AssertionNotFoundError(
                f"Assertion {assertion_id} not found"
            )
        return record

    async def apply_transition(
        self,
        record: AssertionRecord,
        to_status: str,
        actor_id: str,
        reason: Optional[str],
    ) -> None:
        """Check, apply and log a status change on a loaded record.

        Raises:
            InvalidTransitionError: If the change is not allowed.
        """
        check_transition(record.status, to_status)
        stmt = select(func.max(AssertionTransitionRecord.sequence)).where(
            AssertionTransitionRecord.assertion_id == record.id
        )
        latest = (await self.session.execute(stmt)).scalar_one_or_none()
        now = datetime.now(timezone.utc)
        self.session.add(
            AssertionTransitionRecord(
                assertion=record,
                sequence=(latest or 0) + 1,
                from_status=record.status,
                to_status=to_status,
                actor_id=actor_id,
                reason=reason,
                created_at=now,
            )
        )
        record.status = to_status
        record.updated_at = now
        if to_status == "validated":
            await enqueue(
                self.session, ASSERTION_KIND, record.id,
                record.workspace_id, record.semantic_profile_id,
                "Validated; awaiting approval",
            )
        else:
            outcome = to_status if to_status in ("approved", "rejected") \
                else "closed"
            await settle(self.session, ASSERTION_KIND, record.id, outcome,
                         actor_id, reason)
        await self.session.flush()
