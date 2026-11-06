"""Persistence for entities, their identifiers and mentions (ADR-0012).

Entities are scoped to a workspace, the tenancy and security boundary used
by retrieval (ADR-0005). Within a workspace a canonical IRI names one
entity, and a typed identifier ``(scheme, value)`` belongs to at most one
entity. The database enforces the identifier rule as well, so it holds
even if this service is bypassed.

Only active entities can be edited here; merges and splits live in
``lineage.py``. Methods flush but never commit; the caller owns the
transaction.
"""

import uuid
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from rag_foundry.db.models import (
    EntityIdentifierRecord,
    EntityMentionRecord,
    EntityRecord,
)
from rag_foundry.entities.models import (
    Entity,
    Mention,
    validate_identifiers,
)


class EntityError(Exception):
    """Base class for entity errors."""


class EntityNotFoundError(EntityError):
    """Raised when an entity id is unknown."""


class MentionNotFoundError(EntityError):
    """Raised when a mention id is unknown."""


class DuplicateEntityError(EntityError):
    """Raised when a canonical IRI is already used in the workspace."""


class DuplicateIdentifierError(EntityError):
    """Raised when an identifier is taken or conflicts with another."""


class EntityStateError(EntityError):
    """Raised when an operation needs an active entity."""


def as_utc(value: datetime) -> datetime:
    """Attach UTC to naive timestamps, which SQLite returns.

    Args:
        value: Timestamp read from the database.

    Returns:
        The timestamp with a timezone.
    """
    if value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


def entity_from_record(record: EntityRecord) -> Entity:
    """Convert an entity record, with loaded identifiers, to a model.

    Args:
        record: The ORM record.

    Returns:
        The entity model.
    """
    return Entity(
        id=record.id,
        workspace_id=record.workspace_id,
        semantic_profile_id=record.semantic_profile_id,
        canonical_uri=record.canonical_uri,
        ontology_class_uri=record.ontology_class_uri,
        preferred_labels=record.preferred_labels,
        aliases=record.aliases,
        identifiers={i.scheme: i.value for i in record.identifiers},
        status=record.status,
        merged_into_id=record.merged_into_id,
        created_at=as_utc(record.created_at),
    )


def mention_from_record(record: EntityMentionRecord) -> Mention:
    """Convert a mention record to a model.

    Args:
        record: The ORM record.

    Returns:
        The mention model.
    """
    return Mention(
        id=record.id,
        workspace_id=record.workspace_id,
        semantic_profile_id=record.semantic_profile_id,
        chunk_id=record.chunk_id,
        start_offset=record.start_offset,
        end_offset=record.end_offset,
        surface_text=record.surface_text,
        ontology_class_uri=record.ontology_class_uri,
        identifiers=record.identifiers,
        resolution_status=record.resolution_status,
        resolved_entity_id=record.resolved_entity_id,
        created_at=as_utc(record.created_at),
    )


class EntityStore:
    """Creates, edits and looks up entities and mentions."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the store with an AsyncSession.

        Args:
            session: SQLAlchemy AsyncSession.
        """
        self.session = session

    async def create_entity(
        self,
        workspace_id: uuid.UUID,
        semantic_profile_id: uuid.UUID,
        canonical_uri: str,
        ontology_class_uri: str,
        preferred_labels: Dict[str, str],
        aliases: Optional[Dict[str, List[str]]] = None,
        identifiers: Optional[Dict[str, str]] = None,
    ) -> Entity:
        """Create an active entity.

        Args:
            workspace_id: Owning workspace.
            semantic_profile_id: Semantic profile.
            canonical_uri: Canonical IRI, unique in the workspace.
            ontology_class_uri: Ontology class IRI.
            preferred_labels: Language tag to preferred label.
            aliases: Language tag to aliases.
            identifiers: Scheme to identifier value.

        Returns:
            The new entity.

        Raises:
            ValueError: If a field is invalid.
            DuplicateEntityError: If the canonical IRI is taken.
            DuplicateIdentifierError: If an identifier is taken.
        """
        entity = Entity(
            workspace_id=workspace_id,
            semantic_profile_id=semantic_profile_id,
            canonical_uri=canonical_uri,
            ontology_class_uri=ontology_class_uri,
            preferred_labels=preferred_labels,
            aliases=aliases or {},
            identifiers=identifiers or {},
        )
        await self.ensure_canonical_uri_free(workspace_id, canonical_uri)
        for scheme, value in entity.identifiers.items():
            await self._ensure_identifier_free(workspace_id, scheme, value)
        self.session.add(
            EntityRecord(
                id=entity.id,
                workspace_id=entity.workspace_id,
                semantic_profile_id=entity.semantic_profile_id,
                canonical_uri=entity.canonical_uri,
                ontology_class_uri=entity.ontology_class_uri,
                preferred_labels=dict(entity.preferred_labels),
                aliases={k: list(v) for k, v in entity.aliases.items()},
                status=entity.status,
                created_at=entity.created_at,
                updated_at=entity.created_at,
                identifiers=[
                    EntityIdentifierRecord(
                        workspace_id=workspace_id, scheme=scheme, value=value
                    )
                    for scheme, value in entity.identifiers.items()
                ],
            )
        )
        await self.session.flush()
        return entity

    async def get_entity(self, entity_id: uuid.UUID) -> Entity:
        """Load an entity.

        Args:
            entity_id: Entity id.

        Returns:
            The entity.

        Raises:
            EntityNotFoundError: If the entity does not exist.
        """
        return entity_from_record(await self.load_record(entity_id))

    async def list_entities(
        self,
        workspace_id: uuid.UUID,
        statuses: Optional[Iterable[str]] = ("active",),
    ) -> List[Entity]:
        """List a workspace's entities, sorted by canonical IRI.

        Args:
            workspace_id: Workspace to list.
            statuses: Statuses to include; None includes every status.

        Returns:
            Matching entities.
        """
        stmt = (
            select(EntityRecord)
            .options(selectinload(EntityRecord.identifiers))
            .where(EntityRecord.workspace_id == workspace_id)
            .order_by(EntityRecord.canonical_uri)
        )
        if statuses is not None:
            stmt = stmt.where(EntityRecord.status.in_(list(statuses)))
        records = (await self.session.execute(stmt)).scalars().all()
        return [entity_from_record(record) for record in records]

    async def find_by_identifier(
        self, workspace_id: uuid.UUID, scheme: str, value: str
    ) -> Optional[Entity]:
        """Find the entity holding a typed identifier.

        Args:
            workspace_id: Workspace to search.
            scheme: Identifier scheme.
            value: Identifier value.

        Returns:
            The entity, or None.
        """
        stmt = select(EntityIdentifierRecord.entity_id).where(
            EntityIdentifierRecord.workspace_id == workspace_id,
            EntityIdentifierRecord.scheme == scheme,
            EntityIdentifierRecord.value == value,
        )
        entity_id = (await self.session.execute(stmt)).scalar_one_or_none()
        return None if entity_id is None else await self.get_entity(
            entity_id
        )

    async def add_alias(
        self, entity_id: uuid.UUID, language: str, alias: str
    ) -> Entity:
        """Add an alias to an active entity; repeats are ignored.

        Args:
            entity_id: Entity id.
            language: BCP 47 language tag.
            alias: Alias text.

        Returns:
            The updated entity.

        Raises:
            ValueError: If the tag or alias is invalid.
            EntityNotFoundError: If the entity does not exist.
            EntityStateError: If the entity is not active.
        """
        record = await self.load_active_record(entity_id)
        aliases = {k: list(v) for k, v in record.aliases.items()}
        if alias in aliases.get(language, []):
            return entity_from_record(record)
        aliases.setdefault(language, []).append(alias)
        entity = Entity.model_validate(
            {**entity_from_record(record).model_dump(), "aliases": aliases}
        )
        record.aliases = aliases
        record.updated_at = datetime.now(timezone.utc)
        await self.session.flush()
        return entity

    async def add_identifier(
        self, entity_id: uuid.UUID, scheme: str, value: str
    ) -> Entity:
        """Add a typed identifier to an active entity.

        Adding the value the entity already holds is a no-op.

        Args:
            entity_id: Entity id.
            scheme: Identifier scheme.
            value: Identifier value.

        Returns:
            The updated entity.

        Raises:
            ValueError: If the scheme or value is invalid.
            EntityNotFoundError: If the entity does not exist.
            EntityStateError: If the entity is not active.
            DuplicateIdentifierError: If the entity has another value for
                the scheme, or another entity holds this one.
        """
        validate_identifiers({scheme: value})
        record = await self.load_active_record(entity_id)
        existing = {i.scheme: i.value for i in record.identifiers}
        if existing.get(scheme) == value:
            return entity_from_record(record)
        if scheme in existing:
            raise DuplicateIdentifierError(
                f"Entity {entity_id} already has {scheme} "
                f"{existing[scheme]!r}"
            )
        await self._ensure_identifier_free(record.workspace_id, scheme, value)
        record.identifiers.append(
            EntityIdentifierRecord(
                workspace_id=record.workspace_id, scheme=scheme, value=value
            )
        )
        record.updated_at = datetime.now(timezone.utc)
        await self.session.flush()
        return entity_from_record(record)

    async def record_mention(
        self,
        workspace_id: uuid.UUID,
        semantic_profile_id: uuid.UUID,
        chunk_id: uuid.UUID,
        start_offset: int,
        end_offset: int,
        surface_text: str,
        ontology_class_uri: Optional[str] = None,
        identifiers: Optional[Dict[str, str]] = None,
    ) -> Mention:
        """Record an unresolved mention.

        Args:
            workspace_id: Owning workspace.
            semantic_profile_id: Semantic profile.
            chunk_id: Chunk the mention occurs in.
            start_offset: Span start (characters).
            end_offset: Span end, exclusive.
            surface_text: Text as it appears.
            ontology_class_uri: Expected ontology class, if known.
            identifiers: Identifiers extracted with the mention.

        Returns:
            The new mention.

        Raises:
            ValueError: If a field is invalid.
        """
        mention = Mention(
            workspace_id=workspace_id,
            semantic_profile_id=semantic_profile_id,
            chunk_id=chunk_id,
            start_offset=start_offset,
            end_offset=end_offset,
            surface_text=surface_text,
            ontology_class_uri=ontology_class_uri,
            identifiers=identifiers or {},
        )
        self.session.add(
            EntityMentionRecord(
                id=mention.id,
                workspace_id=mention.workspace_id,
                semantic_profile_id=mention.semantic_profile_id,
                chunk_id=mention.chunk_id,
                start_offset=mention.start_offset,
                end_offset=mention.end_offset,
                surface_text=mention.surface_text,
                ontology_class_uri=mention.ontology_class_uri,
                identifiers=dict(mention.identifiers),
                resolution_status=mention.resolution_status,
                created_at=mention.created_at,
            )
        )
        await self.session.flush()
        return mention

    async def get_mention(self, mention_id: uuid.UUID) -> Mention:
        """Load a mention.

        Args:
            mention_id: Mention id.

        Returns:
            The mention.

        Raises:
            MentionNotFoundError: If the mention does not exist.
        """
        record = await self.session.get(EntityMentionRecord, mention_id)
        if record is None:
            raise MentionNotFoundError(f"Mention {mention_id} not found")
        return mention_from_record(record)

    async def load_record(self, entity_id: uuid.UUID) -> EntityRecord:
        """Load an entity record with its identifiers.

        Raises:
            EntityNotFoundError: If the entity does not exist.
        """
        stmt = (
            select(EntityRecord)
            .options(selectinload(EntityRecord.identifiers))
            .where(EntityRecord.id == entity_id)
        )
        record = (await self.session.execute(stmt)).scalar_one_or_none()
        if record is None:
            raise EntityNotFoundError(f"Entity {entity_id} not found")
        return record

    async def load_active_record(
        self, entity_id: uuid.UUID
    ) -> EntityRecord:
        """Load an entity record that must be active.

        Raises:
            EntityNotFoundError: If the entity does not exist.
            EntityStateError: If the entity is not active.
        """
        record = await self.load_record(entity_id)
        if record.status != "active":
            raise EntityStateError(
                f"Entity {entity_id} is {record.status}, not active"
            )
        return record

    async def ensure_canonical_uri_free(
        self, workspace_id: uuid.UUID, canonical_uri: str
    ) -> None:
        """Check that no entity in the workspace uses a canonical IRI.

        Raises:
            DuplicateEntityError: If the IRI is taken.
        """
        stmt = select(EntityRecord.id).where(
            EntityRecord.workspace_id == workspace_id,
            EntityRecord.canonical_uri == canonical_uri,
        )
        if (await self.session.execute(stmt)).first() is not None:
            raise DuplicateEntityError(
                f"{canonical_uri} already names an entity in this workspace"
            )

    async def _ensure_identifier_free(
        self, workspace_id: uuid.UUID, scheme: str, value: str
    ) -> None:
        """Check that no entity in the workspace holds an identifier.

        Raises:
            DuplicateIdentifierError: If the identifier is taken.
        """
        stmt = select(EntityIdentifierRecord.entity_id).where(
            EntityIdentifierRecord.workspace_id == workspace_id,
            EntityIdentifierRecord.scheme == scheme,
            EntityIdentifierRecord.value == value,
        )
        holder = (await self.session.execute(stmt)).scalar_one_or_none()
        if holder is not None:
            raise DuplicateIdentifierError(
                f"{scheme} {value!r} already identifies entity {holder}"
            )
