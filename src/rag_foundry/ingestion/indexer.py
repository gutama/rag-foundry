"""Document chunking, embedding, and atomic DB persistence (ADR-0002/0004)."""

import asyncio
import time
import uuid
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field
from sqlalchemy import delete, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from rag_foundry.chunking.models import DocumentChunk
from rag_foundry.chunking.structural import StructuralChunker
from rag_foundry.db.models import Chunk
from rag_foundry.parsing.models import CanonicalDocument
from rag_foundry.retrieval.embeddings import (
    EmbeddingService,
    MockDeterministicEmbeddingService,
    SentenceTransformerEmbeddingService,
    resolve_embedding_model_name,
)
from rag_foundry.retrieval.postgres_filters import (
    SessionOrFactory,
    acquire_session,
)


def deterministic_chunk_id(
    document_version_id: uuid.UUID,
    chunk_index: int,
    checksum: str,
) -> uuid.UUID:
    """Derive a deterministic UUIDv5 for idempotent chunk persistence.

    Args:
        document_version_id: Parent document version UUID.
        chunk_index: Zero-based sequential chunk index.
        checksum: Deterministic SHA-256 chunk checksum.

    Returns:
        Deterministic UUIDv5 unique to the document version, position, and text.
    """
    key = f"{document_version_id}:{chunk_index}:{checksum}"
    return uuid.uuid5(uuid.NAMESPACE_URL, key)


class IndexingResult(BaseModel):
    """Structured summary emitted after indexing a CanonicalDocument."""

    document_version_id: uuid.UUID = Field(
        description="Indexed document version UUID."
    )
    workspace_id: uuid.UUID = Field(
        description="Owning workspace UUID for tenant isolation."
    )
    chunk_count: int = Field(
        ge=0, description="Number of chunks persisted for this document."
    )
    chunk_ids: List[uuid.UUID] = Field(
        default_factory=list,
        description="Ordered UUIDs of persisted Chunk records.",
    )
    replaced_chunk_count: int = Field(
        default=0,
        ge=0,
        description="Number of prior Chunk rows replaced on re-indexing.",
    )
    embedding_model: Optional[str] = Field(
        default=None, description="Embedding model identifier pinned at index."
    )
    embedding_dim: Optional[int] = Field(
        default=None, description="Embedding vector dimensionality."
    )
    duration_ms: float = Field(
        default=0.0, ge=0.0, description="End-to-end indexing latency in ms."
    )


class IndexerService:
    """Wires StructuralChunker and EmbeddingService to atomic Chunk DB writes.

    Supports idempotent re-indexing by atomically replacing existing chunks for
    a ``document_version_id`` only after chunking and embedding succeed.
    """

    def __init__(
        self,
        session_or_factory: SessionOrFactory,
        embedding_service: Optional[EmbeddingService] = None,
        chunker: Optional[StructuralChunker] = None,
        embedding_model_name: Optional[str] = None,
        fts_language: str = "english",
        expected_embedding_dim: Optional[int] = None,
    ) -> None:
        """Initialize IndexerService.

        Args:
            session_or_factory: AsyncSession or async_sessionmaker factory.
            embedding_service: Optional EmbeddingService (defaults to
                MockDeterministicEmbeddingService).
            chunker: Optional StructuralChunker instance.
            embedding_model_name: Explicit embedding model name recorded on
                Chunk rows (inferred if omitted).
            fts_language: PostgreSQL text-search configuration for
                ``to_tsvector`` updates.
            expected_embedding_dim: Expected vector dimension matching the
                ``chunks.embedding`` column (defaults to ``Chunk.embedding``
                column dimension).

        Raises:
            ValueError: If ``embedding_service.dimension`` does not match the
                configured ``chunks.embedding`` column dimension.
        """
        self.session_or_factory = session_or_factory
        self.embedding_service: EmbeddingService = (
            embedding_service or MockDeterministicEmbeddingService()
        )
        self.chunker = chunker or StructuralChunker()
        self.embedding_model_name = resolve_embedding_model_name(
            self.embedding_service, embedding_model_name
        )
        self.fts_language = fts_language

        schema_dim = getattr(Chunk.__table__.c.embedding.type, "dim", None)
        target_dim = (
            expected_embedding_dim
            if expected_embedding_dim is not None
            else schema_dim
        )
        if target_dim is not None and target_dim <= 0:
            raise ValueError("expected_embedding_dim must be positive.")
        self.expected_embedding_dim = target_dim

        # Fail fast if the embedding service dimension disagrees with the
        # Chunk.embedding column (skip eager model load for lazy ST adapters
        # whose dimension is not yet explicitly configured).
        has_known_dim = (
            not isinstance(
                self.embedding_service, SentenceTransformerEmbeddingService
            )
            or self.embedding_service._dimension is not None
        )
        if target_dim is not None and has_known_dim:
            service_dim = self.embedding_service.dimension
            if service_dim != target_dim:
                raise ValueError(
                    f"Embedding dimension mismatch with Chunk.embedding "
                    f"schema: service dimension is {service_dim}, but "
                    f"column expects {target_dim}. Align the model or set "
                    f"RAG_FOUNDRY_EMBEDDING_DIM={service_dim} and migrate."
                )

    def build_postgresql_fts_update(
        self, document_version_id: uuid.UUID
    ) -> Any:
        """Build a PostgreSQL UPDATE populating ``chunks.search_vector``.

        Args:
            document_version_id: Target document version UUID.

        Returns:
            SQLAlchemy Update statement using PostgreSQL ``to_tsvector``.
        """
        return (
            update(Chunk)
            .where(Chunk.document_version_id == document_version_id)
            .values(
                search_vector=func.to_tsvector(self.fts_language, Chunk.text)
            )
        )

    def _compute_validated_embeddings(
        self, doc_chunks: List[DocumentChunk]
    ) -> List[List[float]]:
        """Compute and validate embeddings before opening DB write txn."""
        if not doc_chunks:
            return []

        texts = [c.text for c in doc_chunks]
        vectors = self.embedding_service.embed_texts(texts)
        if len(vectors) != len(doc_chunks):
            raise ValueError(
                f"Embedding count mismatch: expected {len(doc_chunks)}, "
                f"got {len(vectors)}."
            )

        expected_dim = self.embedding_service.dimension
        if (
            self.expected_embedding_dim is not None
            and expected_dim != self.expected_embedding_dim
        ):
            raise ValueError(
                f"Embedding dimension mismatch with Chunk.embedding schema: "
                f"service dimension is {expected_dim}, but column expects "
                f"{self.expected_embedding_dim}."
            )

        for idx, vec in enumerate(vectors):
            if len(vec) != expected_dim:
                raise ValueError(
                    f"Embedding dimension mismatch at chunk {idx}: expected "
                    f"{expected_dim}, got {len(vec)}."
                )
        return vectors

    def _build_chunk_rows(
        self,
        doc_chunks: List[DocumentChunk],
        vectors: List[List[float]],
        *,
        document_version_id: uuid.UUID,
        workspace_id: uuid.UUID,
        semantic_profile_id: uuid.UUID,
        security_domain: str,
        metadata: Optional[Dict[str, Any]],
        dialect_name: str,
        embedding_dim: int,
    ) -> List[Chunk]:
        """Convert DocumentChunk domain models + vectors into Chunk ORM rows."""
        rows: List[Chunk] = []
        for doc_chunk, vec in zip(doc_chunks, vectors):
            merged_meta: Dict[str, Any] = dict(doc_chunk.metadata)
            merged_meta.setdefault(
                "element_types", list(doc_chunk.element_types)
            )
            if metadata:
                merged_meta.update(metadata)

            chunk_uuid = deterministic_chunk_id(
                document_version_id=document_version_id,
                chunk_index=doc_chunk.chunk_index,
                checksum=doc_chunk.checksum,
            )
            rows.append(
                Chunk(
                    id=chunk_uuid,
                    document_version_id=document_version_id,
                    workspace_id=workspace_id,
                    chunk_index=doc_chunk.chunk_index,
                    text=doc_chunk.text,
                    section_path=list(doc_chunk.section_path),
                    page_numbers=list(doc_chunk.page_numbers),
                    bounding_boxes=[
                        bbox.model_dump() for bbox in doc_chunk.bounding_boxes
                    ],
                    security_domain=security_domain,
                    chunk_metadata=merged_meta,
                    embedding=vec,
                    embedding_model=self.embedding_model_name,
                    embedding_dim=embedding_dim,
                    search_vector=(
                        None
                        if dialect_name == "postgresql"
                        else doc_chunk.text.lower()
                    ),
                    checksum=doc_chunk.checksum,
                    chunker_name=doc_chunk.chunker_name,
                    chunker_version=doc_chunk.chunker_version,
                    semantic_profile_id=semantic_profile_id,
                )
            )
        return rows

    async def index_document(
        self,
        canonical_doc: CanonicalDocument,
        document_version_id: uuid.UUID,
        workspace_id: uuid.UUID,
        semantic_profile_id: uuid.UUID,
        *,
        security_domain: str = "general",
        metadata: Optional[Dict[str, Any]] = None,
        commit: bool = True,
    ) -> IndexingResult:
        """Chunk, embed, and atomically persist a parsed document to DB.

        Args:
            canonical_doc: Parsed CanonicalDocument input.
            document_version_id: Persisted Document row UUID.
            workspace_id: Owning workspace UUID.
            semantic_profile_id: Pinned SemanticProfile UUID.
            security_domain: Non-empty security domain tag (default 'general').
            metadata: Optional governed metadata dictionary copied onto chunks.
            commit: Whether to commit the session after writing (default True).
                When False, writes remain uncommitted inside the caller's
                session transaction so they can be grouped or rolled back.

        Returns:
            IndexingResult summarizing persisted chunk IDs and counts.

        Raises:
            ValueError: If security_domain is empty, commit=False is used with
                a session factory, or embedding dimensions fail validation.
        """
        start = time.perf_counter()
        domain_clean = security_domain.strip()
        if not domain_clean:
            raise ValueError("security_domain must be a non-empty string.")
        if not commit and not isinstance(
            self.session_or_factory, AsyncSession
        ):
            raise ValueError(
                "commit=False requires an explicit AsyncSession instance so "
                "the caller controls transaction commit or rollback."
            )

        # 1. Chunk and embed BEFORE mutating database state for atomicity
        doc_chunks = self.chunker.chunk_document(canonical_doc)
        vectors = await asyncio.to_thread(
            self._compute_validated_embeddings, doc_chunks
        )
        embedding_dim = (
            len(vectors[0]) if vectors else self.embedding_service.dimension
        )

        # 2. Atomically replace existing chunks for this document_version_id
        async with acquire_session(self.session_or_factory) as (
            session,
            dialect_name,
        ):
            chunk_rows = self._build_chunk_rows(
                doc_chunks,
                vectors,
                document_version_id=document_version_id,
                workspace_id=workspace_id,
                semantic_profile_id=semantic_profile_id,
                security_domain=domain_clean,
                metadata=metadata,
                dialect_name=dialect_name,
                embedding_dim=embedding_dim,
            )
            # Capture IDs BEFORE commit/close so default expire_on_commit=True
            # never triggers DetachedInstanceError or MissingGreenlet.
            chunk_ids = [row.id for row in chunk_rows]

            async def _apply_writes() -> int:
                del_res = await session.execute(
                    delete(Chunk).where(
                        Chunk.document_version_id == document_version_id
                    )
                )
                replaced = int(del_res.rowcount or 0)
                if chunk_rows:
                    session.add_all(chunk_rows)
                    await session.flush()
                    if dialect_name == "postgresql":
                        await session.execute(
                            self.build_postgresql_fts_update(
                                document_version_id
                            )
                        )
                return replaced

            if commit:
                if session.in_transaction():
                    if dialect_name == "postgresql":
                        async with session.begin_nested():
                            replaced_count = await _apply_writes()
                    else:
                        replaced_count = await _apply_writes()
                    await session.commit()
                else:
                    async with session.begin():
                        replaced_count = await _apply_writes()
            else:
                if session.in_transaction():
                    if dialect_name == "postgresql":
                        async with session.begin_nested():
                            replaced_count = await _apply_writes()
                    else:
                        replaced_count = await _apply_writes()
                else:
                    # Autobegin a caller-owned transaction without committing
                    # (avoiding SAVEPOINT on SQLite before BEGIN, which commits
                    # on RELEASE SAVEPOINT).
                    try:
                        replaced_count = await _apply_writes()
                    except Exception:
                        await session.rollback()
                        raise

        duration_ms = round((time.perf_counter() - start) * 1000.0, 3)
        return IndexingResult(
            document_version_id=document_version_id,
            workspace_id=workspace_id,
            chunk_count=len(chunk_ids),
            chunk_ids=chunk_ids,
            replaced_chunk_count=replaced_count,
            embedding_model=self.embedding_model_name,
            embedding_dim=embedding_dim,
            duration_ms=duration_ms,
        )
