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


def score_expanded_lexical_text(
    text: str,
    original_query_text: str,
    expanded_term_weights: Dict[str, float],
) -> float:
    """Score text for expanded queries while strictly protecting exact matches.

    Exact matches against ``original_query_text`` receive a dominant floor
    above the hard cap on auxiliary expanded-term matches so synonym-stuffed
    chunks cannot outrank an exact original-query hit.

    Args:
        text: Candidate chunk text.
        original_query_text: Unmodified user query prior to expansion.
        expanded_term_weights: Lowercase expanded term -> decay weight mapping.

    Returns:
        Normalized relevance score in ``[0.0, 1.0]``.
    """
    text_lower = text.lower()
    doc_tokens = re.findall(r"\b\w+\b", text_lower)
    if not doc_tokens:
        return 0.0

    token_freq: Dict[str, int] = {}
    for tok in doc_tokens:
        token_freq[tok] = token_freq.get(tok, 0) + 1

    orig_score = 0.0
    orig_clean = original_query_text.strip().lower()
    if orig_clean:
        orig_boundary = rf"(?<!\w){re.escape(orig_clean)}(?!\w)"
        if re.search(orig_boundary, text_lower) is not None:
            orig_score += 8.0

        quoted_phrases = [
            p.strip().lower()
            for p in re.findall(r'"([^"]*)"', original_query_text)
            if p.strip()
        ]
        for phrase in quoted_phrases:
            if phrase in text_lower:
                orig_score += 3.0

        orig_tokens = [
            t
            for t in re.findall(r"\b\w+\b", orig_clean)
            if t not in {"or", "and"}
        ]
        unique_orig_tokens = list(dict.fromkeys(orig_tokens))
        matched_orig_tokens = 0
        for tok in unique_orig_tokens:
            if tok in token_freq:
                matched_orig_tokens += 1
                tf = token_freq[tok]
                orig_score += tf / (tf + 1.2)
        if unique_orig_tokens and matched_orig_tokens == len(
            unique_orig_tokens
        ):
            orig_score += 3.0

    expanded_score = 0.0
    for term_key, weight in expanded_term_weights.items():
        term_clean = term_key.strip().lower()
        if not term_clean or term_clean == orig_clean:
            continue
        term_boundary = rf"(?<!\w){re.escape(term_clean)}(?!\w)"
        if re.search(term_boundary, text_lower) is not None:
            expanded_score += 1.0 * weight
        else:
            term_tokens = re.findall(r"\b\w+\b", term_clean)
            if term_tokens and all(tok in token_freq for tok in term_tokens):
                expanded_score += 0.5 * weight

    bounded_expanded = min(1.5, expanded_score)
    raw_score = orig_score + bounded_expanded
    if raw_score <= 0.0:
        return 0.0
    normalized = 1.0 - math.exp(-raw_score / 3.0)
    return min(1.0, max(0.0, normalized))


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
        terms = [
            t.lower()
            for t in self._tokenize(cleaned_text)
            if t.lower() not in {"or", "and"}
        ]
        return {
            "phrases": [p.lower() for p in phrases if p.strip()],
            "terms": terms,
        }

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
        use_expanded_scoring = bool(
            query.original_query_text or query.expanded_term_weights
        )
        parsed_query = (
            {} if use_expanded_scoring else self._parse_query(query.query_text)
        )
        orig_text = query.original_query_text or query.query_text
        candidates: List[RankedChunk] = []

        for rec in self._records.values():
            # 1. Strict workspace isolation
            if rec.workspace_id != query.filter.workspace_id:
                continue

            # 2. Document IDs whitelist filter
            if (
                query.filter.document_ids
                and rec.document_version_id not in query.filter.document_ids
            ):
                continue

            # 3. Security domain filter
            if (
                query.filter.security_domains
                and rec.security_domain not in query.filter.security_domains
            ):
                continue

            # 4. Metadata filters
            if query.filter.metadata_filters:
                from rag_foundry.retrieval.postgres_filters import (
                    matches_metadata_filters,
                )

                if not matches_metadata_filters(
                    rec.metadata, query.filter.metadata_filters
                ):
                    continue

            if use_expanded_scoring:
                score = score_expanded_lexical_text(
                    rec.text, orig_text, query.expanded_term_weights
                )
            else:
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

        # Sort descending by score with deterministic chunk_id tie-break
        candidates.sort(key=lambda x: (-x.score, str(x.chunk_id)))

        # Truncate to top_k and assign lexical_rank
        top_candidates = candidates[: query.top_k]
        for rank_idx, chunk in enumerate(top_candidates, start=1):
            chunk.lexical_rank = rank_idx

        return top_candidates
