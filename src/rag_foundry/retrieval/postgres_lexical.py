"""Compact-profile PostgreSQL Full-Text Search lexical retriever (ADR-0004)."""

import math
import re
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import Select, and_, func, or_, select

from rag_foundry.db.models import Chunk
from rag_foundry.retrieval.models import RankedChunk, RetrievalQuery
from rag_foundry.retrieval.postgres_filters import (
    SessionOrFactory,
    acquire_session,
    build_chunk_acl_conditions,
    matches_metadata_filters,
    parse_chunk_bounding_boxes,
)

_TOKEN_RE = re.compile(r"\b\w+\b")
_PHRASE_RE = re.compile(r'"([^"]*)"')


class PostgresLexicalRetriever:
    """Database-backed lexical retriever using PostgreSQL FTS + SQLite fallback.

    Pushes workspace, security-domain, document-ID, and metadata filters into
    SQL ``WHERE`` clauses prior to FTS ranking and ``LIMIT`` truncation.
    """

    def __init__(
        self,
        session_or_factory: SessionOrFactory,
        language: str = "english",
    ) -> None:
        """Initialize the compact-profile lexical retriever.

        Args:
            session_or_factory: AsyncSession or async_sessionmaker factory.
            language: PostgreSQL text search configuration (default 'english').
        """
        self.session_or_factory = session_or_factory
        self.language = language

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        """Extract lowercase alphanumeric tokens from text."""
        return _TOKEN_RE.findall(text.lower())

    @classmethod
    def _parse_query(cls, query_text: str) -> Dict[str, List[str]]:
        """Split a websearch-style query into quoted phrases and terms.

        Args:
            query_text: Raw or expanded query string.

        Returns:
            Dictionary with 'phrases' and 'terms' token lists.
        """
        phrases = [
            p.strip().lower()
            for p in _PHRASE_RE.findall(query_text)
            if p.strip()
        ]
        without_phrases = _PHRASE_RE.sub(" ", query_text)
        terms = [
            tok
            for tok in cls._tokenize(without_phrases)
            if tok not in {"or", "and"}
        ]
        return {"phrases": phrases, "terms": terms}

    @classmethod
    def _score_text(
        cls,
        text: str,
        parsed_query: Dict[str, List[str]],
    ) -> float:
        """Compute normalized lexical relevance in [0.0, 1.0] for SQLite.

        Args:
            text: Chunk text content.
            parsed_query: Output from ``_parse_query``.

        Returns:
            Normalized relevance score in [0.0, 1.0].
        """
        text_lower = text.lower()
        raw_score = 0.0

        for phrase in parsed_query["phrases"]:
            if phrase in text_lower:
                raw_score += 3.0

        tokens = cls._tokenize(text)
        if not tokens:
            return 0.0

        freq: Dict[str, int] = {}
        for tok in tokens:
            freq[tok] = freq.get(tok, 0) + 1

        for term in parsed_query["terms"]:
            if term in freq:
                tf = freq[term]
                raw_score += tf / (tf + 1.2)

        if raw_score <= 0.0:
            return 0.0
        return min(1.0, max(0.0, 1.0 - math.exp(-raw_score / 2.5)))

    @staticmethod
    def _normalize_pg_rank(raw_rank: float) -> float:
        """Normalize PostgreSQL ts_rank_cd score into [0.0, 1.0]."""
        rank_val = float(raw_rank)
        if rank_val <= 0.0:
            return 0.0
        return min(1.0, max(0.0, 1.0 - math.exp(-rank_val * 2.5)))

    def build_postgresql_query(
        self,
        query: RetrievalQuery,
    ) -> Optional[Select[Any]]:
        """Build a PostgreSQL FTS query with pre-retrieval ACL WHERE pushdown.

        Uses the indexed ``chunks.search_vector`` column via ``@@`` (falling
        back to ``to_tsvector`` only when ``search_vector`` is NULL) and ranks
        matches using ``ts_rank_cd`` with deterministic ``chunks.id ASC``
        tie-breaking.

        Args:
            query: RetrievalQuery specification.

        Returns:
            Compiled-ready SQLAlchemy Select statement, or ``None`` if the
            query fails closed or has empty search text.
        """
        query_text = query.query_text.strip()
        if not query_text:
            return None

        conditions = build_chunk_acl_conditions(query, "postgresql")
        if conditions is None:
            return None

        ts_query = func.websearch_to_tsquery(self.language, query_text)
        fallback_vec = func.to_tsvector(self.language, Chunk.text)
        ts_match = or_(
            Chunk.search_vector.op("@@")(ts_query),
            and_(
                Chunk.search_vector.is_(None),
                fallback_vec.op("@@")(ts_query),
            ),
        )
        effective_vec = func.coalesce(Chunk.search_vector, fallback_vec)
        rank_expr = func.ts_rank_cd(effective_vec, ts_query)

        return (
            select(Chunk, rank_expr.label("fts_rank"))
            .where(*conditions, ts_match)
            .order_by(rank_expr.desc(), Chunk.id.asc())
            .limit(query.top_k)
        )

    async def retrieve(self, query: RetrievalQuery) -> List[RankedChunk]:
        """Execute full-text lexical retrieval with pre-retrieval ACL pushdown.

        Args:
            query: RetrievalQuery containing query text, filters, and top_k.

        Returns:
            Deterministically ordered list of RankedChunk instances.
        """
        if not query.filter.security_domains:
            return []
        if (
            query.filter.document_ids is not None
            and len(query.filter.document_ids) == 0
        ):
            return []
        if not query.query_text.strip():
            return []

        async with acquire_session(self.session_or_factory) as (
            session,
            dialect_name,
        ):
            if dialect_name == "postgresql":
                return await self._retrieve_postgresql(session, query)
            return await self._retrieve_sqlite(session, query)

    async def _retrieve_postgresql(
        self,
        session: Any,
        query: RetrievalQuery,
    ) -> List[RankedChunk]:
        """Execute native PostgreSQL FTS query and normalize scores."""
        stmt = self.build_postgresql_query(query)
        if stmt is None:
            return []

        result = await session.execute(stmt)
        rows = result.all()

        scored: List[Tuple[float, Chunk]] = []
        for chunk, raw_rank in rows:
            score = self._normalize_pg_rank(raw_rank)
            if score <= 0.0 or score < query.min_relevance_score:
                continue
            scored.append((round(score, 4), chunk))

        scored.sort(key=lambda item: (-item[0], str(item[1].id)))
        return self._to_ranked_chunks(scored[: query.top_k])

    async def _retrieve_sqlite(
        self,
        session: Any,
        query: RetrievalQuery,
    ) -> List[RankedChunk]:
        """Execute SQL ACL-filtered retrieval with Python lexical scoring."""
        conditions = build_chunk_acl_conditions(query, "sqlite")
        if conditions is None:
            return []

        parsed_query = self._parse_query(query.query_text)
        if not parsed_query["phrases"] and not parsed_query["terms"]:
            return []

        stmt = select(Chunk).where(*conditions)
        result = await session.execute(stmt)
        chunks = result.scalars().all()

        scored: List[Tuple[float, Chunk]] = []
        for chunk in chunks:
            if not matches_metadata_filters(
                chunk.chunk_metadata, query.filter.metadata_filters
            ):
                continue
            score = self._score_text(chunk.text, parsed_query)
            if score <= 0.0 or score < query.min_relevance_score:
                continue
            scored.append((round(score, 4), chunk))

        scored.sort(key=lambda item: (-item[0], str(item[1].id)))
        return self._to_ranked_chunks(scored[: query.top_k])

    @staticmethod
    def _to_ranked_chunks(
        scored_rows: List[Tuple[float, Chunk]],
    ) -> List[RankedChunk]:
        """Convert scored Chunk ORM rows into RankedChunk domain models."""
        ranked: List[RankedChunk] = []
        for rank_idx, (score, chunk) in enumerate(scored_rows, start=1):
            ranked.append(
                RankedChunk(
                    chunk_id=chunk.id,
                    document_version_id=chunk.document_version_id,
                    workspace_id=chunk.workspace_id,
                    text=chunk.text,
                    score=score,
                    retrieval_sources=["lexical"],
                    lexical_rank=rank_idx,
                    section_path=list(chunk.section_path or []),
                    page_numbers=list(chunk.page_numbers or []),
                    bounding_boxes=parse_chunk_bounding_boxes(
                        chunk.bounding_boxes
                    ),
                )
            )
        return ranked
