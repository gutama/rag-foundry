"""Authorized loader bridging Phase 4 assertions and Phase 5 chunk ACLs."""

import re
import uuid
from typing import (
    Any,
    Dict,
    List,
    Optional,
    Protocol,
    Sequence,
    Set,
    Tuple,
    runtime_checkable,
)

from pydantic import ValidationError
from sqlalchemy import select

from rag_foundry.db.models import (
    AssertionRecord,
    Chunk,
    Document,
    EntityRecord,
)
from rag_foundry.generation.models import (
    EvidenceEntry,
    KnowledgeAuthority,
)
from rag_foundry.retrieval.models import BoundingBox
from rag_foundry.retrieval.postgres_filters import (
    SessionOrFactory,
    acquire_session,
)
from rag_foundry.retrieval.security import (
    SecurityAuthorizationError,
    SecurityContext,
)

_EXCLUDED_STATUSES = ("rejected", "superseded")
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> Set[str]:
    """Extract lowercase alphanumeric tokens for deterministic scoring."""
    return set(_TOKEN_RE.findall(text.lower()))


def _clamp_confidence(value: float) -> float:
    """Clamp confidence score into [0.0, 1.0]."""
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return float(value)


_CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|[_-]+")


def _humanize_property_uri(property_uri: str) -> str:
    """Extract a readable property label from an ontology URI."""
    cleaned = property_uri.strip()
    if "#" in cleaned:
        local = cleaned.rsplit("#", 1)[-1]
    elif "/" in cleaned:
        local = cleaned.rstrip("/").rsplit("/", 1)[-1]
    else:
        local = cleaned
    if not local:
        return cleaned
    words = _CAMEL_BOUNDARY_RE.sub(" ", local).strip().lower()
    return " ".join(words.split()) or cleaned


def _resolve_entity_label(
    entity: Optional[EntityRecord],
    entity_id: uuid.UUID,
    language: str,
) -> str:
    """Select the preferred human-readable label for an EntityRecord."""
    if entity is None:
        return str(entity_id)
    labels = entity.preferred_labels or {}
    if language in labels and labels[language]:
        return str(labels[language])
    if "en" in labels and labels["en"]:
        return str(labels["en"])
    for key in sorted(labels.keys()):
        if labels[key]:
            return str(labels[key])
    return entity.canonical_uri or str(entity_id)


def _parse_chunk_uuids(raw_ids: Sequence[Any]) -> Optional[List[uuid.UUID]]:
    """Parse raw JSON chunk ID strings; return None if any ID is malformed."""
    parsed: List[uuid.UUID] = []
    for raw in raw_ids:
        try:
            parsed.append(
                raw if isinstance(raw, uuid.UUID) else uuid.UUID(str(raw))
            )
        except (ValueError, TypeError):
            return None
    return parsed


def _parse_bboxes(raw_boxes: Sequence[Any]) -> List[BoundingBox]:
    """Safely deserialize BoundingBox dicts from Chunk JSON payloads."""
    boxes: List[BoundingBox] = []
    for item in raw_boxes:
        if isinstance(item, BoundingBox):
            boxes.append(item)
        elif isinstance(item, dict):
            try:
                boxes.append(BoundingBox.model_validate(item))
            except ValidationError:
                continue
    return boxes


@runtime_checkable
class AssertionContextProvider(Protocol):
    """Protocol for loading authorized semantic assertions as EvidenceEntry."""

    async def load_assertions(
        self,
        *,
        workspace_id: uuid.UUID,
        security_context: SecurityContext,
        semantic_profile_id: Optional[uuid.UUID] = None,
        query_text: Optional[str] = None,
        include_extracted_candidates: bool = True,
        limit: int = 20,
    ) -> List[EvidenceEntry]:
        """Return authorized assertions classified into curated/extracted."""
        ...


async def load_chunk_security_domains(
    session_or_factory: SessionOrFactory,
    workspace_id: uuid.UUID,
    chunk_ids: Sequence[uuid.UUID],
) -> Dict[uuid.UUID, str]:
    """Fetch workspace-scoped chunk_id -> security_domain mappings from DB.

    Args:
        session_or_factory: Bound AsyncSession or async_sessionmaker factory.
        workspace_id: Target workspace UUID.
        chunk_ids: Chunk UUIDs to inspect.

    Returns:
        Dictionary mapping found chunk UUIDs to their security domain strings.
    """
    unique_ids = list(dict.fromkeys(chunk_ids))
    if not unique_ids:
        return {}
    async with acquire_session(session_or_factory) as (session, _dialect):
        stmt = select(Chunk.id, Chunk.security_domain).where(
            Chunk.workspace_id == workspace_id,
            Chunk.id.in_(unique_ids),
        )
        rows = (await session.execute(stmt)).all()
    return {row[0]: str(row[1]) for row in rows}


class AssertionContextLoader:
    """Loads authorized AssertionRecord rows with entity & chunk provenance.

    Enforces ADR-0005 authorization before disclosure and ADR-0013 curated vs.
    extracted authority classification:
    - Unauthorized ``workspace_id`` raises ``SecurityAuthorizationError``.
    - Empty ``allowed_security_domains`` fails closed and returns ``[]``.
    - ``rejected`` and ``superseded`` assertions are always excluded.
    - Assertions with ``source_chunk_ids`` are disclosed ONLY when EVERY
      backing chunk resolves within ``workspace_id`` and EVERY backing chunk's
      ``security_domain`` is authorized under ``security_context``.
    - Assertions with empty ``source_chunk_ids`` are disclosed ONLY when they
      are curated/approved AND ``default_curated_security_domain`` is allowed.
    """

    def __init__(
        self,
        session_or_factory: SessionOrFactory,
        *,
        default_curated_security_domain: str = "general",
        language: str = "en",
    ) -> None:
        """Initialize the database-backed assertion context loader.

        Args:
            session_or_factory: AsyncSession or async_sessionmaker factory.
            default_curated_security_domain: Domain required when a steward
                curated/approved assertion has no backing source chunks.
            language: Preferred entity label language code.
        """
        self._session_or_factory = session_or_factory
        self._default_curated_domain = default_curated_security_domain
        self._language = language

    async def load_assertions(
        self,
        *,
        workspace_id: uuid.UUID,
        security_context: SecurityContext,
        semantic_profile_id: Optional[uuid.UUID] = None,
        query_text: Optional[str] = None,
        include_extracted_candidates: bool = True,
        limit: int = 20,
    ) -> List[EvidenceEntry]:
        """Load authorized, classified assertion EvidenceEntry objects.

        Args:
            workspace_id: Target workspace UUID.
            security_context: Caller SecurityContext verified before query.
            semantic_profile_id: Optional semantic profile filter.
            query_text: Optional question text used for deterministic ranking.
            include_extracted_candidates: Whether unapproved extracted
                assertions should be included alongside curated facts.
            limit: Maximum number of assertion entries to return.

        Returns:
            Deterministically ordered list of authorized EvidenceEntry items.

        Raises:
            SecurityAuthorizationError: If caller lacks workspace access.
        """
        if not security_context.can_access_workspace(workspace_id):
            raise SecurityAuthorizationError(
                f"Unauthorized workspace access: user "
                f"'{security_context.user_id}' cannot read assertions in "
                f"workspace '{workspace_id}'."
            )

        if not security_context.allowed_security_domains or limit <= 0:
            return []

        async with acquire_session(self._session_or_factory) as (
            session,
            _dialect,
        ):
            stmt = select(AssertionRecord).where(
                AssertionRecord.workspace_id == workspace_id,
                AssertionRecord.status.notin_(_EXCLUDED_STATUSES),
            )
            if semantic_profile_id is not None:
                stmt = stmt.where(
                    AssertionRecord.semantic_profile_id == semantic_profile_id
                )
            rows = list((await session.execute(stmt)).scalars().all())
            if not rows:
                return []

            # Filter candidate origin/authority early and gather chunk/entity
            # IDs for single-roundtrip batched lookups.
            eligible: List[Tuple[AssertionRecord, KnowledgeAuthority]] = []
            chunk_id_set: Set[uuid.UUID] = set()
            entity_id_set: Set[uuid.UUID] = set()

            for row in rows:
                authority = (
                    KnowledgeAuthority.CURATED
                    if row.origin == "curated" or row.status == "approved"
                    else KnowledgeAuthority.EXTRACTED
                )
                if (
                    authority == KnowledgeAuthority.EXTRACTED
                    and not include_extracted_candidates
                ):
                    continue
                eligible.append((row, authority))
                parsed_chunks = _parse_chunk_uuids(row.source_chunk_ids or [])
                if parsed_chunks:
                    chunk_id_set.update(parsed_chunks)
                entity_id_set.add(row.subject_entity_id)
                if row.object_entity_id is not None:
                    entity_id_set.add(row.object_entity_id)

            if not eligible:
                return []

            chunks_by_id: Dict[uuid.UUID, Chunk] = {}
            doc_titles: Dict[uuid.UUID, str] = {}
            if chunk_id_set:
                chunk_stmt = select(Chunk).where(
                    Chunk.workspace_id == workspace_id,
                    Chunk.id.in_(list(chunk_id_set)),
                )
                for ch in (await session.execute(chunk_stmt)).scalars().all():
                    chunks_by_id[ch.id] = ch

                doc_ids = {
                    ch.document_version_id for ch in chunks_by_id.values()
                }
                if doc_ids:
                    doc_stmt = select(Document.id, Document.title).where(
                        Document.workspace_id == workspace_id,
                        Document.id.in_(list(doc_ids)),
                    )
                    doc_rows = (await session.execute(doc_stmt)).all()
                    for d_id, d_title in doc_rows:
                        if d_title:
                            doc_titles[d_id] = str(d_title)

            entities_by_id: Dict[uuid.UUID, EntityRecord] = {}
            if entity_id_set:
                ent_stmt = select(EntityRecord).where(
                    EntityRecord.workspace_id == workspace_id,
                    EntityRecord.id.in_(list(entity_id_set)),
                )
                for ent in (await session.execute(ent_stmt)).scalars().all():
                    entities_by_id[ent.id] = ent

        query_tokens = _tokenize(query_text) if query_text else set()
        scored_entries: List[Tuple[int, int, float, str, EvidenceEntry]] = []

        for row, authority in eligible:
            entry = self._build_authorized_entry(
                row=row,
                authority=authority,
                security_context=security_context,
                chunks_by_id=chunks_by_id,
                doc_titles=doc_titles,
                entities_by_id=entities_by_id,
            )
            if entry is None:
                continue
            overlap = (
                len(query_tokens & _tokenize(entry.text))
                if query_tokens
                else 0
            )
            auth_rank = 0 if authority == KnowledgeAuthority.CURATED else 1
            scored_entries.append(
                (
                    auth_rank,
                    -overlap,
                    -entry.confidence_score,
                    str(row.id),
                    entry,
                )
            )

        scored_entries.sort(
            key=lambda item: (item[0], item[1], item[2], item[3])
        )
        selected = scored_entries[:limit]

        return [
            item[4].model_copy(update={"evidence_id": f"A{idx}"})
            for idx, item in enumerate(selected, start=1)
        ]

    def _build_authorized_entry(
        self,
        *,
        row: AssertionRecord,
        authority: KnowledgeAuthority,
        security_context: SecurityContext,
        chunks_by_id: Dict[uuid.UUID, Chunk],
        doc_titles: Dict[uuid.UUID, str],
        entities_by_id: Dict[uuid.UUID, EntityRecord],
    ) -> Optional[EvidenceEntry]:
        """Verify chunk-level ACLs and build a normalized EvidenceEntry."""
        raw_chunk_ids = row.source_chunk_ids or []
        resolved_chunks: List[Chunk] = []

        if raw_chunk_ids:
            parsed_ids = _parse_chunk_uuids(raw_chunk_ids)
            if not parsed_ids:
                return None
            for cid in parsed_ids:
                chunk = chunks_by_id.get(cid)
                if chunk is None:
                    # Unresolvable backing chunk -> fail closed.
                    return None
                if not security_context.can_access_domain(
                    chunk.security_domain
                ):
                    # Any unauthorized backing domain hides the assertion.
                    return None
                resolved_chunks.append(chunk)
        else:
            # Provenance-free assertions allowed ONLY if curated/approved
            # and caller holds default_curated_security_domain.
            if authority != KnowledgeAuthority.CURATED:
                return None
            if not security_context.can_access_domain(
                self._default_curated_domain
            ):
                return None

        subj_label = _resolve_entity_label(
            entities_by_id.get(row.subject_entity_id),
            row.subject_entity_id,
            self._language,
        )
        prop_label = _humanize_property_uri(row.property_uri)

        linked_entities: List[uuid.UUID] = [row.subject_entity_id]
        if row.object_entity_id is not None:
            linked_entities.append(row.object_entity_id)
            obj_label = _resolve_entity_label(
                entities_by_id.get(row.object_entity_id),
                row.object_entity_id,
                self._language,
            )
            statement = f"{subj_label} {prop_label} {obj_label}."
        else:
            lit = "" if row.literal_value is None else str(row.literal_value)
            statement = f"{subj_label} {prop_label}: {lit}."

        if resolved_chunks:
            domains = tuple(
                dict.fromkeys(ch.security_domain for ch in resolved_chunks)
            )
            primary_domain = domains[0]
            first_chunk = resolved_chunks[0]
            doc_ver_id: Optional[uuid.UUID] = first_chunk.document_version_id
            doc_title: Optional[str] = doc_titles.get(doc_ver_id)
            primary_chunk_id: Optional[uuid.UUID] = first_chunk.id
            src_chunk_ids = tuple(ch.id for ch in resolved_chunks)
            pages = tuple(
                sorted({p for ch in resolved_chunks for p in ch.page_numbers})
            )
            sections: Tuple[str, ...] = ()
            for ch in resolved_chunks:
                if ch.section_path:
                    sections = tuple(ch.section_path)
                    break
            bboxes = tuple(
                box
                for ch in resolved_chunks
                for box in _parse_bboxes(ch.bounding_boxes)
            )
        else:
            domains = (self._default_curated_domain,)
            primary_domain = self._default_curated_domain
            doc_ver_id = None
            doc_title = None
            primary_chunk_id = None
            src_chunk_ids = ()
            pages = ()
            sections = ()
            bboxes = ()

        origin = "curated" if row.origin == "curated" else "extracted"
        return EvidenceEntry(
            evidence_id="A0",
            authority=authority,
            text=statement,
            workspace_id=row.workspace_id,
            security_domain=primary_domain,
            security_domains=domains,
            document_version_id=doc_ver_id,
            document_title=doc_title,
            chunk_id=primary_chunk_id,
            source_chunk_ids=src_chunk_ids,
            assertion_id=row.id,
            assertion_origin=origin,
            assertion_status=row.status,
            subject_entity_id=row.subject_entity_id,
            object_entity_id=row.object_entity_id,
            property_uri=row.property_uri,
            section_path=sections,
            page_numbers=pages,
            bounding_boxes=bboxes,
            entity_ids=tuple(linked_entities),
            confidence_score=_clamp_confidence(row.confidence),
        )
