"""Compact-profile SQLAlchemy/pgvector dense semantic retriever (ADR-0004)."""

import math
from typing import Any, List, Optional, Tuple

from sqlalchemy import Select, select

from rag_foundry.db.models import Chunk
from rag_foundry.retrieval.embeddings import EmbeddingService
from rag_foundry.retrieval.models import RankedChunk, RetrievalQuery
from rag_foundry.retrieval.postgres_filters import (
    SessionOrFactory,
    acquire_session,
    build_chunk_acl_conditions,
    matches_metadata_filters,
    parse_chunk_bounding_boxes,
)


class PostgresDenseRetriever:
    """Database-backed dense retriever using pgvector with SQLite fallback.

    Enforces workspace isolation, allowed security domains, optional document
    ID whitelists, and metadata filters prior to similarity scoring or ranking.
    """

    def __init__(
        self,
        session_or_factory: SessionOrFactory,
        embedding_service: EmbeddingService,
    ) -> None:
        """Initialize the compact-profile dense retriever.

        Args:
            session_or_factory: AsyncSession or async_sessionmaker factory.
            embedding_service: EmbeddingService used to embed incoming queries.
        """
        self.session_or_factory = session_or_factory
        self.embedding_service = embedding_service

    @staticmethod
    def _cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
        """Compute normalized cosine similarity in [0.0, 1.0].

        Args:
            vec1: First embedding vector.
            vec2: Second embedding vector.

        Returns:
            Similarity normalized from [-1.0, 1.0] into [0.0, 1.0].
        """
        if len(vec1) != len(vec2) or not vec1:
            return 0.0
        dot = sum(a * b for a, b in zip(vec1, vec2))
        norm1 = math.sqrt(sum(a * a for a in vec1))
        norm2 = math.sqrt(sum(b * b for b in vec2))
        if norm1 == 0.0 or norm2 == 0.0:
            return 0.0
        raw_cos = dot / (norm1 * norm2)
        return max(0.0, min(1.0, (raw_cos + 1.0) / 2.0))

    @staticmethod
    def _distance_to_similarity(cosine_distance: float) -> float:
        """Convert pgvector cosine distance [0, 2] to similarity in [0, 1].

        Args:
            cosine_distance: Value returned by pgvector ``<=>`` operator.

        Returns:
            Normalized similarity matching ``(cos_sim + 1.0) / 2.0``.
        """
        return max(0.0, min(1.0, 1.0 - (float(cosine_distance) / 2.0)))

    def build_postgresql_query(
        self,
        query: RetrievalQuery,
        query_vector: List[float],
    ) -> Optional[Select[Any]]:
        """Build a PostgreSQL pgvector cosine-distance query with ACL pushdown.

        All workspace, security-domain, document-ID, and metadata filters are
        pushed into SQL ``WHERE`` before ``<=>`` ordering and ``LIMIT``.

        Args:
            query: RetrievalQuery specification.
            query_vector: Dense query vector produced by EmbeddingService.

        Returns:
            Compiled-ready SQLAlchemy Select statement, or ``None`` if the
            query fails closed.
        """
        conditions = build_chunk_acl_conditions(query, "postgresql")
        if conditions is None:
            return None

        raw_distance = Chunk.embedding.cosine_distance(query_vector)
        return (
            select(Chunk, raw_distance.label("cosine_distance"))
            .where(*conditions, Chunk.embedding.is_not(None))
            .order_by(raw_distance.asc(), Chunk.id.asc())
            .limit(query.top_k)
        )

    async def retrieve(self, query: RetrievalQuery) -> List[RankedChunk]:
        """Retrieve top-k chunks ordered by cosine similarity with ACL pushdown.

        Args:
            query: RetrievalQuery containing query text, filters, and top_k.

        Returns:
            Deterministically ordered list of RankedChunk instances.
        """
        # Fail closed before embedding or touching the database.
        if not query.filter.security_domains:
            return []
        if (
            query.filter.document_ids is not None
            and len(query.filter.document_ids) == 0
        ):
            return []

        query_vector = self.embedding_service.embed_query(query.query_text)

        async with acquire_session(self.session_or_factory) as (
            session,
            dialect_name,
        ):
            if dialect_name == "postgresql":
                return await self._retrieve_postgresql(
                    session, query, query_vector
                )
            return await self._retrieve_sqlite(session, query, query_vector)

    async def _retrieve_postgresql(
        self,
        session: Any,
        query: RetrievalQuery,
        query_vector: List[float],
    ) -> List[RankedChunk]:
        """Execute native pgvector similarity query on PostgreSQL."""
        stmt = self.build_postgresql_query(query, query_vector)
        if stmt is None:
            return []
        result = await session.execute(stmt)
        rows = result.all()

        scored: List[Tuple[float, Chunk]] = []
        for chunk, distance in rows:
            similarity = self._distance_to_similarity(distance)
            if similarity < query.min_relevance_score:
                continue
            scored.append((round(similarity, 4), chunk))

        scored.sort(key=lambda item: (-item[0], str(item[1].id)))
        return self._to_ranked_chunks(scored[: query.top_k])

    async def _retrieve_sqlite(
        self,
        session: Any,
        query: RetrievalQuery,
        query_vector: List[float],
    ) -> List[RankedChunk]:
        """Execute SQL-filtered retrieval with Python cosine scoring."""
        conditions = build_chunk_acl_conditions(query, "sqlite")
        if conditions is None:
            return []

        stmt = select(Chunk).where(*conditions, Chunk.embedding.is_not(None))
        result = await session.execute(stmt)
        chunks = result.scalars().all()

        scored: List[Tuple[float, Chunk]] = []
        for chunk in chunks:
            if not matches_metadata_filters(
                chunk.chunk_metadata, query.filter.metadata_filters
            ):
                continue
            if not chunk.embedding:
                continue
            similarity = self._cosine_similarity(query_vector, chunk.embedding)
            if similarity < query.min_relevance_score:
                continue
            scored.append((round(similarity, 4), chunk))

        scored.sort(key=lambda item: (-item[0], str(item[1].id)))
        return self._to_ranked_chunks(scored[: query.top_k])

    @staticmethod
    def _to_ranked_chunks(
        scored_rows: List[Tuple[float, Chunk]],
    ) -> List[RankedChunk]:
        """Convert scored Chunk ORM rows into RankedChunk domain objects."""
        ranked: List[RankedChunk] = []
        for rank_idx, (score, chunk) in enumerate(scored_rows, start=1):
            ranked.append(
                RankedChunk(
                    chunk_id=chunk.id,
                    document_version_id=chunk.document_version_id,
                    workspace_id=chunk.workspace_id,
                    text=chunk.text,
                    score=score,
                    retrieval_sources=["dense"],
                    dense_rank=rank_idx,
                    section_path=list(chunk.section_path or []),
                    page_numbers=list(chunk.page_numbers or []),
                    bounding_boxes=parse_chunk_bounding_boxes(
                        chunk.bounding_boxes
                    ),
                )
            )
        return ranked
