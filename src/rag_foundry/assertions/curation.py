"""Curated versus extracted knowledge (ADR-0013).

Curated knowledge is authored or approved by stewards; extracted knowledge
is machine output and starts as a candidate. This module keeps the two
apart:

- **Re-extraction adds evidence, never authority.** When an extraction
  states a fact that already exists and is still live (candidate,
  validated or approved, of either origin), the new evidence chunks are
  appended and nothing else changes: not the status, the origin or the
  confidence. Facts match on workspace, subject, property, value (type-
  strict: ``1``, ``True`` and ``"1"`` differ) and validity interval (naive
  bounds are read as UTC, as they are stored).
- **Extracted never supersedes curated.** ``supersede`` retires an approved
  assertion, optionally naming an approved replacement about the same
  subject and property; an extracted replacement for a curated assertion
  is refused.

A conflicting extraction, e.g. a second value for a single-valued property,
is simply a new candidate; validation then rejects it on ``max_count``.
"""

import uuid
from datetime import datetime
from typing import Any, List, Optional, Tuple

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rag_foundry.assertions.lifecycle import (
    AssertionStateError,
    AssertionStore,
    SemanticAssertionError,
    assertion_from_record,
    require_actor,
)
from rag_foundry.assertions.models import (
    LiteralValue,
    SemanticAssertion,
    utc_or_none,
)
from rag_foundry.db.models import AssertionRecord, Chunk

LIVE_STATUSES = ("candidate", "validated", "approved")
CURATOR_METHOD = "steward"


class CurationError(SemanticAssertionError):
    """Raised for supersessions that do not make sense."""


class CuratedProtectionError(CurationError):
    """Raised when extracted knowledge would replace curated knowledge."""


class ExtractionResult(BaseModel):
    """The outcome of recording one extraction."""

    assertion: SemanticAssertion = Field(description="New or matched")
    created: bool = Field(description="True if a new assertion was made")
    added_evidence: List[uuid.UUID] = Field(
        description="Chunks newly cited by this extraction"
    )


def _value_key(value: Any) -> Tuple[str, Any]:
    """Compare literals by type as well as value."""
    return (type(value).__name__, value)


class CurationService:
    """Records extractions and curated facts, and supersedes assertions."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the service.

        Args:
            session: SQLAlchemy AsyncSession.
        """
        self.session = session
        self._store = AssertionStore(session)

    async def record_extraction(
        self,
        actor_id: str,
        workspace_id: uuid.UUID,
        semantic_profile_id: uuid.UUID,
        subject_entity_id: uuid.UUID,
        property_uri: str,
        extraction_method: str,
        confidence: float,
        source_chunk_ids: List[uuid.UUID],
        object_entity_id: Optional[uuid.UUID] = None,
        literal_value: Optional[LiteralValue] = None,
        extraction_model: Optional[str] = None,
        extraction_prompt_version: Optional[str] = None,
        valid_from: Optional[datetime] = None,
        valid_to: Optional[datetime] = None,
    ) -> ExtractionResult:
        """Record an extracted fact, or add evidence to the matching one.

        Evidence added to an existing assertion must resolve in its
        workspace, because an approved assertion is not validated again
        automatically. A new candidate's evidence is checked by validation.

        Args:
            actor_id: Extraction job or extractor.
            workspace_id: Owning workspace.
            semantic_profile_id: Semantic profile.
            subject_entity_id: Subject entity.
            property_uri: Property IRI.
            extraction_method: How it was extracted.
            confidence: Extraction confidence.
            source_chunk_ids: Chunks the fact was found in.
            object_entity_id: Object entity, for object properties.
            literal_value: Literal, for data properties.
            extraction_model: Model used, if any.
            extraction_prompt_version: Prompt version, if any.
            valid_from: Start of validity.
            valid_to: End of validity.

        Returns:
            The new or matched assertion and the evidence added.

        Raises:
            ValueError: If a field is invalid or new evidence does not
                resolve in the workspace.
            EntityNotFoundError: If the subject or object does not exist.
        """
        require_actor(actor_id)
        match = await self._find_live_match(
            workspace_id, subject_entity_id, property_uri, object_entity_id,
            literal_value, valid_from, valid_to,
        )
        if match is None:
            assertion = await self._store.create_assertion(
                actor_id=actor_id,
                workspace_id=workspace_id,
                semantic_profile_id=semantic_profile_id,
                subject_entity_id=subject_entity_id,
                property_uri=property_uri,
                origin="extracted",
                extraction_method=extraction_method,
                confidence=confidence,
                source_chunk_ids=source_chunk_ids,
                object_entity_id=object_entity_id,
                literal_value=literal_value,
                extraction_model=extraction_model,
                extraction_prompt_version=extraction_prompt_version,
                valid_from=valid_from,
                valid_to=valid_to,
            )
            return ExtractionResult(
                assertion=assertion,
                created=True,
                added_evidence=list(assertion.source_chunk_ids),
            )
        cited = set(match.source_chunk_ids)
        new = [c for c in dict.fromkeys(source_chunk_ids)
               if str(c) not in cited]
        await self._check_evidence(workspace_id, new)
        if new:
            match.source_chunk_ids = list(match.source_chunk_ids) + [
                str(c) for c in new
            ]
            await self.session.flush()
        return ExtractionResult(
            assertion=assertion_from_record(match),
            created=False,
            added_evidence=new,
        )

    async def create_curated(
        self,
        actor_id: str,
        workspace_id: uuid.UUID,
        semantic_profile_id: uuid.UUID,
        subject_entity_id: uuid.UUID,
        property_uri: str,
        source_chunk_ids: Optional[List[uuid.UUID]] = None,
        object_entity_id: Optional[uuid.UUID] = None,
        literal_value: Optional[LiteralValue] = None,
        extraction_method: str = CURATOR_METHOD,
        confidence: float = 1.0,
        valid_from: Optional[datetime] = None,
        valid_to: Optional[datetime] = None,
    ) -> SemanticAssertion:
        """Create a curated candidate authored by a steward or import.

        Curated assertions still go through validation and approval.

        Args:
            actor_id: Steward or curation job.
            workspace_id: Owning workspace.
            semantic_profile_id: Semantic profile.
            subject_entity_id: Subject entity.
            property_uri: Property IRI.
            source_chunk_ids: Supporting chunks, if any.
            object_entity_id: Object entity, for object properties.
            literal_value: Literal, for data properties.
            extraction_method: How it was produced; defaults to steward.
            confidence: Confidence; defaults to 1.0.
            valid_from: Start of validity.
            valid_to: End of validity.

        Returns:
            The new curated candidate.
        """
        return await self._store.create_assertion(
            actor_id=actor_id,
            workspace_id=workspace_id,
            semantic_profile_id=semantic_profile_id,
            subject_entity_id=subject_entity_id,
            property_uri=property_uri,
            origin="curated",
            extraction_method=extraction_method,
            confidence=confidence,
            source_chunk_ids=source_chunk_ids,
            object_entity_id=object_entity_id,
            literal_value=literal_value,
            valid_from=valid_from,
            valid_to=valid_to,
        )

    async def supersede(
        self,
        assertion_id: uuid.UUID,
        replacement_id: Optional[uuid.UUID],
        actor_id: str,
        reason: str,
    ) -> SemanticAssertion:
        """Retire an approved assertion, optionally naming its replacement.

        Args:
            assertion_id: Approved assertion to retire.
            replacement_id: Approved assertion that replaces it, if any.
            actor_id: Steward performing the change.
            reason: Why it is retired.

        Returns:
            The superseded assertion.

        Raises:
            ValueError: If the actor or reason is blank.
            AssertionNotFoundError: If an assertion does not exist.
            AssertionStateError: If either assertion is not approved.
            CurationError: If the replacement is the same assertion or is
                about another subject, property or workspace.
            CuratedProtectionError: If an extracted assertion would replace
                a curated one.
        """
        require_actor(actor_id)
        if not reason.strip():
            raise ValueError("Superseding an assertion needs a reason")
        old = await self._store.load_record(assertion_id)
        self._require_approved(old)
        if replacement_id is not None:
            if replacement_id == assertion_id:
                raise CurationError("An assertion cannot replace itself")
            new = await self._store.load_record(replacement_id)
            self._require_approved(new)
            if (new.workspace_id, new.subject_entity_id, new.property_uri) \
                    != (old.workspace_id, old.subject_entity_id,
                        old.property_uri):
                raise CurationError(
                    "A replacement must be about the same subject and "
                    "property in the same workspace"
                )
            if old.origin == "curated" and new.origin == "extracted":
                raise CuratedProtectionError(
                    "Extracted knowledge cannot supersede curated knowledge"
                )
        await self._store.apply_transition(old, "superseded", actor_id,
                                           reason)
        old.superseded_by_id = replacement_id
        await self.session.flush()
        return assertion_from_record(old)

    # --- Helpers ----------------------------------------------------------

    @staticmethod
    def _require_approved(record: AssertionRecord) -> None:
        """Refuse assertions that are not approved.

        Raises:
            AssertionStateError: If the assertion is not approved.
        """
        if record.status != "approved":
            raise AssertionStateError(
                f"Assertion {record.id} is {record.status}, not approved"
            )

    async def _find_live_match(
        self,
        workspace_id: uuid.UUID,
        subject_entity_id: uuid.UUID,
        property_uri: str,
        object_entity_id: Optional[uuid.UUID],
        literal_value: Optional[LiteralValue],
        valid_from: Optional[datetime],
        valid_to: Optional[datetime],
    ) -> Optional[AssertionRecord]:
        """Find a live assertion stating the same fact, oldest first."""
        stmt = (
            select(AssertionRecord)
            .where(
                AssertionRecord.workspace_id == workspace_id,
                AssertionRecord.subject_entity_id == subject_entity_id,
                AssertionRecord.property_uri == property_uri,
                AssertionRecord.status.in_(LIVE_STATUSES),
            )
            .order_by(AssertionRecord.created_at, AssertionRecord.id)
        )
        records = (await self.session.execute(stmt)).scalars().all()
        wanted = (
            object_entity_id,
            _value_key(literal_value),
            utc_or_none(valid_from),
            utc_or_none(valid_to),
        )
        for record in records:
            current = assertion_from_record(record)
            found = (
                current.object_entity_id,
                _value_key(current.literal_value),
                current.valid_from,
                current.valid_to,
            )
            if found == wanted:
                return record
        return None

    async def _check_evidence(
        self, workspace_id: uuid.UUID, chunk_ids: List[uuid.UUID]
    ) -> None:
        """Check that chunks exist in the workspace.

        Raises:
            ValueError: If a chunk is missing or in another workspace.
        """
        if not chunk_ids:
            return
        stmt = select(Chunk.id).where(
            Chunk.id.in_(chunk_ids), Chunk.workspace_id == workspace_id
        )
        found = set((await self.session.execute(stmt)).scalars().all())
        unresolved = [c for c in chunk_ids if c not in found]
        if unresolved:
            raise ValueError(
                f"Evidence chunks not found in the workspace: {unresolved}"
            )
