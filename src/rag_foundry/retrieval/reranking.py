"""Candidate reranking services for hybrid retrieval refinement (ADR-0016)."""

import abc
import math
import re
from typing import Any, Callable, List, Optional, Sequence, Tuple

from rag_foundry.retrieval.models import RankedChunk

PairScorer = Callable[[List[Tuple[str, str]]], Sequence[float]]


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
        if not candidates or top_k <= 0:
            return []

        reranked: List[RankedChunk] = []
        for candidate in candidates:
            chunk_copy = candidate.model_copy(deep=True)
            rerank_score = self._compute_relevance(query, chunk_copy.text)
            # Combine prior score (30%) with reranker score (70%)
            combined = (chunk_copy.score * 0.3) + (rerank_score * 0.7)
            chunk_copy.score = round(combined, 4)
            reranked.append(chunk_copy)

        reranked.sort(key=lambda c: (-c.score, str(c.chunk_id)))
        return reranked[:top_k]


def _sigmoid(value: float) -> float:
    """Compute an overflow-safe logistic sigmoid in `[0.0, 1.0]`."""
    if value >= 0.0:
        return 1.0 / (1.0 + math.exp(-value))
    exp_val = math.exp(value)
    return exp_val / (1.0 + exp_val)


def _normalize_scores(raw_scores: Sequence[float], mode: str) -> List[float]:
    """Normalize raw cross-encoder scores into `[0.0, 1.0]`.

    Args:
        raw_scores: Raw float scores or logits from a cross-encoder.
        mode: Normalization strategy (`"sigmoid"` or `"minmax"`).

    Returns:
        Normalized scores strictly within `[0.0, 1.0]`.
    """
    values = [float(s) for s in raw_scores]
    if not values:
        return []

    if mode == "sigmoid":
        return [_sigmoid(v) for v in values]

    low = min(values)
    high = max(values)
    if high == low:
        return [0.5 for _ in values]
    span = high - low
    return [(v - low) / span for v in values]


class CrossEncoderReranker(RerankerService):
    """Cross-encoder reranker with lazy neural loading or explicit fallback.

    Scores `(query, chunk.text)` pairs via an injected `scorer`, pre-loaded
    `model`, or lazily imported `sentence_transformers.CrossEncoder`, maps raw
    logits into `[0.0, 1.0]`, and tie-breaks deterministically by `chunk_id`.
    """

    _SUPPORTED_NORMALIZATIONS = frozenset({"sigmoid", "minmax"})

    def __init__(
        self,
        model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
        fallback_reranker: Optional[RerankerService] = None,
        scorer: Optional[PairScorer] = None,
        model: Optional[Any] = None,
        allow_fallback: bool = True,
        normalization: str = "sigmoid",
        device: Optional[str] = None,
    ) -> None:
        """Initialize CrossEncoderReranker.

        Args:
            model_name: Local path or HuggingFace identifier for CrossEncoder.
            fallback_reranker: Fallback reranker used when `allow_fallback` is
                `True` and neural scoring is unavailable.
            scorer: Optional custom callable scoring `(query, text)` pairs.
            model: Optional pre-loaded CrossEncoder-like object exposing
                `.predict(pairs)`.
            allow_fallback: When `True`, falls back to `fallback_reranker` if
                `sentence_transformers` or the model cannot be loaded. When
                `False`, raises `ImportError` or model loading errors.
            normalization: Score normalization mode (`"sigmoid"` or `"minmax"`).
            device: Optional torch device string passed to `CrossEncoder`.

        Raises:
            ValueError: If `normalization` is not supported.
        """
        norm_mode = normalization.strip().lower()
        if norm_mode not in self._SUPPORTED_NORMALIZATIONS:
            raise ValueError(
                f"Unsupported normalization mode: {normalization!r}. "
                "Expected 'sigmoid' or 'minmax'."
            )

        self.model_name = model_name
        self.fallback = (
            fallback_reranker
            if fallback_reranker is not None
            else ScoringReranker()
        )
        self._scorer = scorer
        self._model = model
        self.allow_fallback = allow_fallback
        self.normalization = norm_mode
        self.device = device

    def _resolve_model(self) -> Optional[Any]:
        """Lazily load `sentence_transformers.CrossEncoder` if needed.

        Returns:
            Loaded model object, or `None` when falling back is permitted.

        Raises:
            ImportError: If `sentence_transformers` is missing and
                `allow_fallback` is `False`.
        """
        if self._model is not None:
            return self._model

        try:
            from sentence_transformers import CrossEncoder
        except ImportError as exc:
            if self.allow_fallback:
                return None
            raise ImportError(
                "CrossEncoderReranker requires optional ML dependencies. "
                "Install with: pip install 'rag-foundry[ml]'"
            ) from exc

        kwargs: dict[str, Any] = {}
        if self.device is not None:
            kwargs["device"] = self.device
        try:
            self._model = CrossEncoder(self.model_name, **kwargs)
        except Exception:
            if self.allow_fallback:
                return None
            raise
        return self._model

    def rerank(
        self, query: str, candidates: List[RankedChunk], top_k: int = 10
    ) -> List[RankedChunk]:
        """Rerank candidates using CrossEncoder scoring or explicit fallback.

        Args:
            query: User search query string.
            candidates: Candidate chunks to score and reorder.
            top_k: Maximum number of reranked chunks to return.

        Returns:
            Reranked chunks ordered by descending score and ascending
            `str(chunk_id)`.

        Raises:
            ImportError: If neural dependencies are unavailable and
                `allow_fallback` is `False`.
            ValueError: If scorer output count does not match `candidates`.
        """
        if not candidates or top_k <= 0:
            return []

        pairs: List[Tuple[str, str]] = [
            (query, candidate.text) for candidate in candidates
        ]
        raw_scores: Any
        if self._scorer is not None:
            raw_scores = self._scorer(pairs)
        else:
            model = self._resolve_model()
            if model is None:
                return self.fallback.rerank(query, candidates, top_k=top_k)
            raw_scores = model.predict(pairs)

        score_list = (
            raw_scores.tolist()
            if hasattr(raw_scores, "tolist")
            else list(raw_scores)
        )
        if len(score_list) != len(candidates):
            raise ValueError(
                f"CrossEncoder score count mismatch: expected "
                f"{len(candidates)}, got {len(score_list)}."
            )

        normalized = _normalize_scores(score_list, self.normalization)
        reranked: List[RankedChunk] = []
        for candidate, norm_score in zip(candidates, normalized):
            chunk_copy = candidate.model_copy(deep=True)
            clamped = min(1.0, max(0.0, norm_score))
            chunk_copy.score = round(clamped, 4)
            reranked.append(chunk_copy)

        reranked.sort(key=lambda c: (-c.score, str(c.chunk_id)))
        return reranked[:top_k]
