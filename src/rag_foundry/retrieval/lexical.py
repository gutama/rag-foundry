"""Governed lexical full-text search retriever with phrase matching and BM25 scoring."""

import math
import re
import uuid
from typing import Any, Dict, List, Optional, Set

from pydantic import BaseModel, Field

from rag_foundry.retrieval.models import (
    BoundingBox,
    RankedChunk,
    RetrievalQuery,
)


class LexicalRecord(BaseModel):
    """Container for indexed document chunk for full-text lexical search."""

    chunk_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    document_version_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    workspace_id: uuid.UUID
    text: str
    section_path: List[str] = Field(default_factory=list)
    page_numbers: List[int] = Field(default_factory=list)
    bounding_boxes: List[BoundingBox] = Field(default_factory=list)
    security_domain: str = "general"
    metadata: Dict[str, Any] = Field(default_factory=dict)


class LexicalRetriever:
    """Full-text lexical search retriever supporting phrase matching and BM25 ranking."""

    def __init__(self) -> None:
        """Initialize LexicalRetriever."""
        self._records: Dict[uuid.UUID, LexicalRecord] = {}

    async def index_records(self, records: List[LexicalRecord]) -> None:
        """Index records into memory for full-text searching.

        Args:
            records: List of LexicalRecord objects to index.
        """
        for rec in records:
            self._records[rec.chunk_id] = rec

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        """Tokenize text into lowercase alpha-numeric words."""
        return re.findall(r"\b\w+\b", text.lower())

    def _parse_query(self, query_text: str) -> Dict[str, Any]:
        """Parse query string for phrases and individual terms."""
        phrases = re.findall(r'"([^"]*)"', query_text)
        cleaned_text = re.sub(r'"[^"]*"', " ", query_text)
        terms = [t.lower() for t in self._tokenize(cleaned_text) if t.lower() not in {"or", "and"}]
        return {"phrases": [p.lower() for p in phrases if p.strip()], "terms": terms}

    def _score_text(self, text: str, parsed_query: Dict[str, Any]) -> float:
        """Score text based on term frequency and phrase presence."""
        text_lower = text.lower()
        score = 0.0

        # Exact phrase bonus
        for phrase in parsed_query["phrases"]:
            if phrase in text_lower:
                score += 3.0

        # Individual token match scoring
        doc_tokens = self._tokenize(text)
        if not doc_tokens:
            return 0.0

        token_freq: Dict[str, int] = {}
        for tok in doc_tokens:
            token_freq[tok] = token_freq.get(tok, 0) + 1

        for term in parsed_query["terms"]:
            if term in token_freq:
                # Sub-linear term frequency tf / (tf + 1.2)
                tf = token_freq[term]
                score += tf / (tf + 1.2)

        # Normalize score into [0.0, 1.0] using sigmoid-like curve
        if score <= 0.0:
            return 0.0
        normalized = 1.0 - math.exp(-score / 2.5)
        return min(1.0, max(0.0, normalized))

    async def retrieve(self, query: RetrievalQuery) -> List[RankedChunk]:
        """Execute full-text lexical search with workspace isolation and metadata filtering.

        Args:
            query: RetrievalQuery specification.

        Returns:
            List of RankedChunk objects ordered by lexical score descending.
        """
        parsed_query = self._parse_query(query.query_text)
        candidates: List[RankedChunk] = []

        for rec in self._records.values():
            # 1. Strict workspace isolation
            if rec.workspace_id != query.filter.workspace_id:
                continue

            # 2. Document IDs whitelist filter
            if query.filter.document_ids and rec.document_version_id not in query.filter.document_ids:
                continue

            # 3. Security domain filter
            if (
                query.filter.security_domains
                and rec.security_domain not in query.filter.security_domains
            ):
                continue

            # 4. Metadata filters
            if query.filter.metadata_filters:
                mismatch = False
                for k, v in query.filter.metadata_filters.items():
                    if rec.metadata.get(k) != v:
                        mismatch = True
                        break
                if mismatch:
                    continue

            score = self._score_text(rec.text, parsed_query)
            if score <= 0.0 or score < query.min_relevance_score:
                continue

            candidates.append(
                RankedChunk(
                    chunk_id=rec.chunk_id,
                    document_version_id=rec.document_version_id,
                    workspace_id=rec.workspace_id,
                    text=rec.text,
                    score=round(score, 4),
                    retrieval_sources=["lexical"],
                    section_path=rec.section_path,
                    page_numbers=rec.page_numbers,
                    bounding_boxes=rec.bounding_boxes,
                )
            )

        # Sort descending by score
        candidates.sort(key=lambda x: x.score, reverse=True)

        # Truncate to top_k and assign lexical_rank
        top_candidates = candidates[: query.top_k]
        for rank_idx, chunk in enumerate(top_candidates, start=1):
            chunk.lexical_rank = rank_idx

        return top_candidates
