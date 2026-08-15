"""Dense semantic vector retrieval service with cosine similarity and pgvector compatibility."""

import math
import uuid
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from rag_foundry.retrieval.embeddings import EmbeddingService
from rag_foundry.retrieval.models import (
    BoundingBox,
    RankedChunk,
    RetrievalQuery,
)


class DenseVectorRecord(BaseModel):
    """Container for indexed chunk text, embedding, and governance metadata."""

    chunk_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    document_version_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    workspace_id: uuid.UUID
    text: str
    vector: Optional[List[float]] = None
    section_path: List[str] = Field(default_factory=list)
    page_numbers: List[int] = Field(default_factory=list)
    bounding_boxes: List[BoundingBox] = Field(default_factory=list)
    security_domain: str = "general"
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DenseVectorRetriever:
    """Dense semantic vector retriever with workspace isolation and similarity scoring."""

    def __init__(self, embedding_service: EmbeddingService) -> None:
        """Initialize DenseVectorRetriever.

        Args:
            embedding_service: EmbeddingService provider for vector representations.
        """
        self.embedding_service = embedding_service
        self._records: Dict[uuid.UUID, DenseVectorRecord] = {}

    async def index_records(self, records: List[DenseVectorRecord]) -> None:
        """Index a batch of chunk vector records, generating embeddings if missing.

        Args:
            records: List of DenseVectorRecord objects to index.
        """
        texts_to_embed: List[str] = []
        indices_to_embed: List[int] = []

        for idx, rec in enumerate(records):
            if rec.vector is None:
                texts_to_embed.append(rec.text)
                indices_to_embed.append(idx)

        if texts_to_embed:
            computed_embeddings = self.embedding_service.embed_texts(texts_to_embed)
            for idx, emb in zip(indices_to_embed, computed_embeddings):
                records[idx].vector = emb

        for rec in records:
            self._records[rec.chunk_id] = rec

    @staticmethod
    def _cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
        """Compute normalized cosine similarity in [0.0, 1.0] range between two float vectors."""
        dot = sum(a * b for a, b in zip(vec1, vec2))
        norm1 = math.sqrt(sum(a * a for a in vec1))
        norm2 = math.sqrt(sum(b * b for b in vec2))
        if norm1 == 0.0 or norm2 == 0.0:
            return 0.0
        raw_cos = dot / (norm1 * norm2)
        # Normalize from [-1.0, 1.0] to [0.0, 1.0]
        normalized = (raw_cos + 1.0) / 2.0
        return max(0.0, min(1.0, normalized))

    async def retrieve(self, query: RetrievalQuery) -> List[RankedChunk]:
        """Perform dense semantic search across indexed records.

        Args:
            query: RetrievalQuery containing query text, filter constraints, and top_k.

        Returns:
            List of RankedChunk objects ordered by cosine similarity descending.
        """
        query_vector = self.embedding_service.embed_query(query.query_text)
        scored_candidates: List[RankedChunk] = []

        for rec in self._records.values():
            # 1. Strict workspace isolation filter
            if rec.workspace_id != query.filter.workspace_id:
                continue

            # 2. Document IDs filter if present
            if query.filter.document_ids and rec.document_version_id not in query.filter.document_ids:
                continue

            # 3. Security domain filter if present
            if (
                query.filter.security_domains
                and rec.security_domain not in query.filter.security_domains
            ):
                continue

            # 4. Metadata filters if present
            if query.filter.metadata_filters:
                mismatch = False
                for k, v in query.filter.metadata_filters.items():
                    if rec.metadata.get(k) != v:
                        mismatch = True
                        break
                if mismatch:
                    continue

            # Compute similarity score
            if rec.vector is None:
                continue

            similarity = self._cosine_similarity(query_vector, rec.vector)

            # Check min relevance score
            if similarity < query.min_relevance_score:
                continue

            scored_candidates.append(
                RankedChunk(
                    chunk_id=rec.chunk_id,
                    document_version_id=rec.document_version_id,
                    workspace_id=rec.workspace_id,
                    text=rec.text,
                    score=round(similarity, 4),
                    retrieval_sources=["dense"],
                    section_path=rec.section_path,
                    page_numbers=rec.page_numbers,
                    bounding_boxes=rec.bounding_boxes,
                )
            )

        # Sort descending by similarity score
        scored_candidates.sort(key=lambda x: x.score, reverse=True)

        # Truncate to top_k and assign dense_rank
        top_candidates = scored_candidates[: query.top_k]
        for rank_idx, chunk in enumerate(top_candidates, start=1):
            chunk.dense_rank = rank_idx

        return top_candidates
