"""Auditable entity merges, splits and redirects (ADR-0012).

Corrections to entity identity are governed operations, not upserts:

- **Merge** keeps a survivor and retires a duplicate. The duplicate becomes
  ``merged`` with ``merged_into_id`` pointing at the survivor; its typed
  identifiers move to the survivor (an identifier names one entity), and
  its labels and aliases are added to the survivor's aliases. The duplicate
  row stays as it was, so its history remains readable.
- **Split** retires a conflated entity and creates explicit successors. Each
  successor claims the original's identifiers it should carry; identifiers
  nobody claims stay on the original. Mentions resolved to the original are
  reset to ``unresolved``, because no single successor can inherit them,
  and validated or approved assertions naming it are flagged for steward
  re-review (their status is not changed silently).
- **Redirects** follow merges through chains. A chain that ends at a split
  entity raises ``EntitySplitError`` instead of guessing a successor.

Every operation needs an actor and a reason and appends ``entity_lineage``
rows; nothing here edits or deletes lineage. Methods flush but never
commit; the caller owns the transaction.
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Set, Tuple

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from rag_foundry.db.models import (
    AssertionRecord,
    EntityIdentifierRecord,
    EntityLineageRecord,
    EntityMentionRecord,
    EntityRecord,
)
from rag_foundry.entities.models import (
    Entity,
    validate_aliases,
    validate_identifiers,
)
from rag_foundry.entities.store import (
    DuplicateIdentifierError,
    EntityError,
    EntityStore,
    as_utc,
    entity_from_record,
    new_entity_record,
)
from rag_foundry.ontology.models import validate_iri, validate_labels
from rag_foundry.stewardship.audit import record_audit
from rag_foundry.stewardship.queue_records import ASSERTION_KIND, enqueue


class LineageError(EntityError):
    """Base class for merge, split and redirect errors."""


class EntityMergeError(LineageError):
    """Raised when two entities cannot be merged."""


class EntitySplitError(LineageError):
    """Raised for invalid splits, or redirects that end at a split."""


class SuccessorSpec(BaseModel):
    """What one successor of a split should look like."""

    canonical_uri: str = Field(description="Canonical IRI of the successor")
    preferred_labels: Dict[str, str] = Field(
        description="Language tag to preferred label"
    )
    aliases: Dict[str, List[str]] = Field(
        default_factory=dict, description="Language tag to aliases"
    )
    identifiers: Dict[str, str] = Field(
        default_factory=dict,
        description="Identifiers to take from the original, or new ones",
    )
    ontology_class_uri: Optional[str] = Field(
        default=None, description="Class; defaults to the original's class"
    )

    _check_canonical = field_validator("canonical_uri")(validate_iri)
    _check_labels = field_validator("preferred_labels")(validate_labels)
    _check_aliases = field_validator("aliases")(validate_aliases)
    _check_identifiers = field_validator("identifiers")(validate_identifiers)

    @field_validator("ontology_class_uri")
    @classmethod
    def _check_class(cls, value: Optional[str]) -> Optional[str]:
        """Validate the class IRI when present."""
        return None if value is None else validate_iri(value)


class LineageEvent(BaseModel):
    """One predecessor-to-successor link of a merge or split."""

    id: uuid.UUID = Field(description="Row id")
    event_id: uuid.UUID = Field(description="Operation the link belongs to")
    event_type: Literal["merge", "split"] = Field(description="Operation")
    workspace_id: uuid.UUID = Field(description="Workspace")
    predecessor_id: uuid.UUID = Field(description="Retired entity")
    successor_id: uuid.UUID = Field(description="Surviving or new entity")
    actor_id: str = Field(description="Who performed the operation")
    reason: str = Field(description="Why")
    details: Dict[str, Any] = Field(description="What moved")
    created_at: datetime = Field(description="When")


class MergeResult(BaseModel):
    """The outcome of a merge."""

    event_id: uuid.UUID = Field(description="Lineage event id")
    survivor: Entity = Field(description="The surviving entity")
    merged: Entity = Field(description="The retired duplicate")


class SplitResult(BaseModel):
    """The outcome of a split."""

    event_id: uuid.UUID = Field(description="Lineage event id")
    original: Entity = Field(description="The retired entity")
    successors: List[Entity] = Field(description="New entities, in order")
    reset_mention_ids: List[uuid.UUID] = Field(
        description="Mentions reset to unresolved"
    )
    flagged_assertion_ids: List[uuid.UUID] = Field(
        description="Assertions flagged for re-review"
    )


def _require_text(value: str, what: str) -> None:
    """Reject blank actors and reasons.

    Raises:
        ValueError: If the value is blank.
    """
    if not value.strip():
        raise ValueError(f"Lineage operations need a non-blank {what}")


def _event_from_record(record: EntityLineageRecord) -> LineageEvent:
    """Convert a lineage record to a model."""
    return LineageEvent(
        id=record.id,
        event_id=record.event_id,
        event_type=record.event_type,
        workspace_id=record.workspace_id,
        predecessor_id=record.predecessor_id,
        successor_id=record.successor_id,
        actor_id=record.actor_id,
        reason=record.reason,
        details=record.details,
        created_at=as_utc(record.created_at),
    )


class EntityLineageService:
    """Merges and splits entities and follows their redirects."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the service.

        Args:
            session: SQLAlchemy AsyncSession.
        """
        self.session = session
        self._store = EntityStore(session)

    async def merge(
        self,
        survivor_id: uuid.UUID,
        merged_id: uuid.UUID,
        actor_id: str,
        reason: str,
    ) -> MergeResult:
        """Merge a duplicate entity into a survivor.

        Args:
            survivor_id: Entity that remains.
            merged_id: Duplicate to retire.
            actor_id: Who performs the merge.
            reason: Why the entities are the same.

        Returns:
            Both entities after the merge and the lineage event id.

        Raises:
            ValueError: If the actor or reason is blank.
            EntityMergeError: If the ids are equal, or the entities differ
                in workspace or class, or hold conflicting identifiers.
            EntityNotFoundError: If either entity does not exist.
            EntityStateError: If either entity is not active.
        """
        _require_text(actor_id, "actor")
        _require_text(reason, "reason")
        if survivor_id == merged_id:
            raise EntityMergeError("An entity cannot be merged into itself")
        survivor = await self._store.load_active_record(survivor_id)
        merged = await self._store.load_active_record(merged_id)
        if survivor.workspace_id != merged.workspace_id:
            raise EntityMergeError("Entities are in different workspaces")
        if survivor.ontology_class_uri != merged.ontology_class_uri:
            raise EntityMergeError(
                f"Classes differ: {survivor.ontology_class_uri} and "
                f"{merged.ontology_class_uri}"
            )
        held = {i.scheme: i.value for i in survivor.identifiers}
        for identifier in merged.identifiers:
            if identifier.scheme in held:
                raise EntityMergeError(
                    f"Conflicting {identifier.scheme} identifiers "
                    f"{held[identifier.scheme]!r} and {identifier.value!r} "
                    "prove these are different entities"
                )

        moved = {i.scheme: i.value for i in merged.identifiers}
        for identifier in list(merged.identifiers):
            survivor.identifiers.append(identifier)
        aliases, added = self._absorb_names(survivor, merged)
        survivor_entity = Entity.model_validate(
            {**entity_from_record(survivor).model_dump(), "aliases": aliases}
        )
        now = datetime.now(timezone.utc)
        survivor.aliases = aliases
        survivor.updated_at = now
        merged.status = "merged"
        merged.merged_into_id = survivor.id
        merged.updated_at = now

        event_id = uuid.uuid4()
        self.session.add(
            EntityLineageRecord(
                event_id=event_id,
                event_type="merge",
                workspace_id=survivor.workspace_id,
                predecessor=merged,
                successor=survivor,
                actor_id=actor_id,
                reason=reason,
                details={"moved_identifiers": moved, "added_aliases": added},
                created_at=now,
            )
        )
        await record_audit(
            self.session, "entity.merged", actor_id, "entity", merged.id,
            {
                "event_id": event_id,
                "survivor_id": survivor.id,
                "reason": reason,
                "moved_identifiers": moved,
                "added_aliases": added,
            },
        )
        await self.session.flush()
        return MergeResult(
            event_id=event_id,
            survivor=survivor_entity,
            merged=entity_from_record(merged),
        )

    async def split(
        self,
        entity_id: uuid.UUID,
        successors: List[SuccessorSpec],
        actor_id: str,
        reason: str,
    ) -> SplitResult:
        """Split a conflated entity into new successor entities.

        Args:
            entity_id: Entity to retire.
            successors: Two or more successor descriptions.
            actor_id: Who performs the split.
            reason: Why the entity was conflated.

        Returns:
            The retired original, the successors, the mentions reset to
            unresolved, the assertions flagged for re-review and the
            lineage event id.

        Raises:
            ValueError: If the actor or reason is blank.
            EntitySplitError: If there are fewer than two successors, or
                successors share a canonical IRI or an identifier.
            EntityNotFoundError: If the entity does not exist.
            EntityStateError: If the entity is not active.
            DuplicateEntityError: If a successor IRI is already taken.
            DuplicateIdentifierError: If a successor claims an identifier
                held by an entity other than the original.
        """
        _require_text(actor_id, "actor")
        _require_text(reason, "reason")
        self._check_successors(successors)
        original = await self._store.load_active_record(entity_id)
        owned = {(i.scheme, i.value): i for i in original.identifiers}
        for spec in successors:
            await self._store.ensure_canonical_uri_free(
                original.workspace_id, spec.canonical_uri
            )
            for scheme, value in spec.identifiers.items():
                holder = await self._store.identifier_holder(
                    original.workspace_id, scheme, value
                )
                if holder is not None and holder != original.id:
                    raise DuplicateIdentifierError(
                        f"{scheme} {value!r} already identifies entity "
                        f"{holder}"
                    )

        now = datetime.now(timezone.utc)
        event_id = uuid.uuid4()
        records: List[EntityRecord] = []
        for spec in successors:
            successor = Entity(
                workspace_id=original.workspace_id,
                semantic_profile_id=original.semantic_profile_id,
                canonical_uri=spec.canonical_uri,
                ontology_class_uri=(
                    spec.ontology_class_uri or original.ontology_class_uri
                ),
                preferred_labels=spec.preferred_labels,
                aliases=spec.aliases,
                identifiers=spec.identifiers,
                created_at=now,
            )
            record = new_entity_record(successor)
            for scheme, value in spec.identifiers.items():
                existing = owned.get((scheme, value))
                record.identifiers.append(
                    existing
                    if existing is not None
                    else EntityIdentifierRecord(
                        workspace_id=original.workspace_id,
                        scheme=scheme,
                        value=value,
                    )
                )
            self.session.add(record)
            records.append(record)
            self.session.add(
                EntityLineageRecord(
                    event_id=event_id,
                    event_type="split",
                    workspace_id=original.workspace_id,
                    predecessor=original,
                    successor=record,
                    actor_id=actor_id,
                    reason=reason,
                    details={"identifiers": dict(spec.identifiers)},
                    created_at=now,
                )
            )
        original.status = "split"
        original.updated_at = now
        reset = await self._reset_mentions(original.id)
        flagged = await self._flag_assertions(original.id, event_id, now)
        await record_audit(
            self.session, "entity.split", actor_id, "entity", original.id,
            {
                "event_id": event_id,
                "reason": reason,
                "successor_ids": [r.id for r in records],
                "reset_mention_ids": reset,
                "flagged_assertion_ids": flagged,
            },
        )
        await self.session.flush()
        return SplitResult(
            event_id=event_id,
            original=entity_from_record(original),
            successors=[entity_from_record(r) for r in records],
            reset_mention_ids=reset,
            flagged_assertion_ids=flagged,
        )

    async def current_entity(self, entity_id: uuid.UUID) -> Entity:
        """Follow merge redirects to the entity that now stands for an id.

        Args:
            entity_id: Any entity id, current or retired.

        Returns:
            The end of the redirect chain (active or deprecated).

        Raises:
            EntityNotFoundError: If an entity on the chain does not exist.
            EntitySplitError: If the chain ends at a split entity.
            LineageError: If the redirects form a cycle.
        """
        seen: Set[uuid.UUID] = set()
        record = await self._store.load_record(entity_id)
        while record.status == "merged" and record.merged_into_id:
            seen.add(record.id)
            if record.merged_into_id in seen:
                raise LineageError(f"Redirect cycle at entity {record.id}")
            record = await self._store.load_record(record.merged_into_id)
        if record.status == "split":
            raise EntitySplitError(
                f"Entity {record.id} was split; resolve the mention again"
            )
        return entity_from_record(record)

    async def history(self, entity_id: uuid.UUID) -> List[LineageEvent]:
        """List lineage links involving an entity, oldest first.

        Args:
            entity_id: Entity id.

        Returns:
            Links where the entity is predecessor or successor.
        """
        stmt = (
            select(EntityLineageRecord)
            .where(
                or_(
                    EntityLineageRecord.predecessor_id == entity_id,
                    EntityLineageRecord.successor_id == entity_id,
                )
            )
            .order_by(
                EntityLineageRecord.created_at,
                EntityLineageRecord.event_id,
                EntityLineageRecord.successor_id,
            )
        )
        records = (await self.session.execute(stmt)).scalars().all()
        return [_event_from_record(r) for r in records]

    # --- Helpers ----------------------------------------------------------

    @staticmethod
    def _absorb_names(
        survivor: EntityRecord, merged: EntityRecord
    ) -> Tuple[Dict[str, List[str]], Dict[str, List[str]]]:
        """Add the merged entity's labels and aliases to survivor aliases.

        Returns:
            The survivor's new aliases and the aliases that were added.
        """
        aliases = {k: list(v) for k, v in survivor.aliases.items()}
        added: Dict[str, List[str]] = {}
        names = list(merged.preferred_labels.items()) + [
            (language, name)
            for language, language_aliases in merged.aliases.items()
            for name in language_aliases
        ]
        for language, name in names:
            if name == survivor.preferred_labels.get(language):
                continue
            if name in aliases.get(language, []):
                continue
            aliases.setdefault(language, []).append(name)
            added.setdefault(language, []).append(name)
        return aliases, added

    @staticmethod
    def _check_successors(successors: List[SuccessorSpec]) -> None:
        """Check the successor list before touching the database.

        Raises:
            EntitySplitError: For fewer than two successors, or shared
                canonical IRIs or identifiers.
        """
        if len(successors) < 2:
            raise EntitySplitError("A split needs at least two successors")
        uris = [spec.canonical_uri for spec in successors]
        if len(set(uris)) != len(uris):
            raise EntitySplitError("Successors need distinct canonical IRIs")
        claimed = [
            (scheme, value)
            for spec in successors
            for scheme, value in spec.identifiers.items()
        ]
        if len(set(claimed)) != len(claimed):
            raise EntitySplitError(
                "An identifier can be given to only one successor"
            )

    async def _reset_mentions(
        self, entity_id: uuid.UUID
    ) -> List[uuid.UUID]:
        """Unresolve mentions linked to an entity; return their ids."""
        stmt = (
            select(EntityMentionRecord)
            .where(EntityMentionRecord.resolved_entity_id == entity_id)
            .order_by(EntityMentionRecord.id)
        )
        mentions = (await self.session.execute(stmt)).scalars().all()
        for mention in mentions:
            mention.resolution_status = "unresolved"
            mention.resolved_entity_id = None
        return [mention.id for mention in mentions]

    async def _flag_assertions(
        self, entity_id: uuid.UUID, event_id: uuid.UUID, when: datetime
    ) -> List[uuid.UUID]:
        """Flag trusted assertions naming a split entity for re-review."""
        stmt = (
            select(AssertionRecord)
            .where(
                or_(
                    AssertionRecord.subject_entity_id == entity_id,
                    AssertionRecord.object_entity_id == entity_id,
                ),
                AssertionRecord.status.in_(("validated", "approved")),
            )
            .order_by(AssertionRecord.created_at, AssertionRecord.id)
        )
        records = (await self.session.execute(stmt)).scalars().all()
        for record in records:
            record.requires_review = True
            record.review_reason = (
                f"Entity {entity_id} was split (event {event_id}); restate "
                "the assertion against one of its successors"
            )
            record.updated_at = when
            await enqueue(
                self.session, ASSERTION_KIND, record.id,
                record.workspace_id, record.semantic_profile_id,
                record.review_reason,
            )
        return [record.id for record in records]
