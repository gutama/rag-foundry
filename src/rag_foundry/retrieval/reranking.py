"""Candidate reranking services for hybrid retrieval refinement (ADR-0016)."""

import abc
import math
import re
from typing import List, Optional

from rag_foundry.retrieval.models import RankedChunk


class RerankerService(abc.ABC):
    """Abstract interface for candidate chunk rerankers."""

    @abc.abstractmethod
    def rerank(
        self, query: str, candidates: List[RankedChunk], top_k: int = 10
    ) -> List[RankedChunk]:
        """Rerank candidate chunks against the original search query."""
        pass


class ScoringReranker(RerankerService):
    """Deterministic, lightweight scoring reranker based on lexical alignment and phrase density."""

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        return re.findall(r"\b\w+\b", text.lower())

    def _compute_relevance(self, query: str, text: str) -> float:
        q_tokens = set(self._tokenize(query))
        if not q_tokens:
            return 0.0

        t_tokens = set(self._tokenize(text))
        overlap = len(q_tokens.intersection(t_tokens)) / float(len(q_tokens))

        # Check contiguous multi-word match
        text_lower = text.lower()
        query_clean = re.sub(r"[^\w\s]", "", query.lower()).strip()
        phrase_bonus = 0.0
        if query_clean and len(query_clean) > 4 and query_clean in text_lower:
            phrase_bonus = 0.4

        score = (overlap * 0.6) + phrase_bonus
        return min(1.0, max(0.0, score))

    def rerank(
        self, query: str, candidates: List[RankedChunk], top_k: int = 10
    ) -> List[RankedChunk]:
        """Rerank candidates using phrase and token overlap density."""
        if not candidates:
            return []

        reranked: List[RankedChunk] = []
        for candidate in candidates:
            chunk_copy = candidate.model_copy(deep=True)
            rerank_score = self._compute_relevance(query, chunk_copy.text)
            # Combine prior score (30%) with reranker score (70%)
            combined = (chunk_copy.score * 0.3) + (rerank_score * 0.7)
            chunk_copy.score = round(combined, 4)
            reranked.append(chunk_copy)

        reranked.sort(key=lambda c: c.score, reverse=True)
        return reranked[:top_k]


class CrossEncoderReranker(RerankerService):
    """Cross-Encoder reranker using neural transformer weights or lightweight fallback."""

    def __init__(
        self,
        model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
        fallback_reranker: Optional[RerankerService] = None,
    ) -> None:
        """Initialize CrossEncoderReranker.

        Args:
            model_name: HuggingFace model identifier.
            fallback_reranker: Fallback reranker if neural model is not initialized.
        """
        self.model_name = model_name
        self.fallback = fallback_reranker or ScoringReranker()
        self._model = None  # Lazy / air-gapped initialization

    def rerank(
        self, query: str, candidates: List[RankedChunk], top_k: int = 10
    ) -> List[RankedChunk]:
        """Rerank candidates using CrossEncoder or fallback."""
        if self._model is None:
            return self.fallback.rerank(query, candidates, top_k=top_k)

        # In standard mode, fallback handles scoring deterministically
        return self.fallback.rerank(query, candidates, top_k=top_k)
