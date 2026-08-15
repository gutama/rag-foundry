"""Reciprocal Rank Fusion (RRF) algorithm for multi-source hybrid search (ADR-0016)."""

import uuid
from typing import Dict, List, Optional

from rag_foundry.retrieval.models import RankedChunk


class ReciprocalRankFusion:
    """Combines multiple ranked candidate lists into a unified ranking using RRF."""

    def __init__(self, k: int = 60) -> None:
        """Initialize Reciprocal Rank Fusion.

        Args:
            k: Smoothing constant parameter (default 60).
        """
        if k < 1:
            raise ValueError("RRF constant k must be >= 1.")
        self.k = k

    def fuse(
        self,
        ranked_lists: Dict[str, List[RankedChunk]],
        weights: Optional[Dict[str, float]] = None,
        top_k: int = 10,
    ) -> List[RankedChunk]:
        """Fuse multiple ranked lists across search modalities (lexical, dense, graph).

        Args:
            ranked_lists: Dictionary mapping source names (e.g. 'dense', 'lexical', 'graph') to ranked chunks.
            weights: Optional weighting multiplier per source (default 1.0).
            top_k: Number of unified top candidates to return.

        Returns:
            List of merged RankedChunk objects ordered by RRF score descending.
        """
        weights = weights or {}
        merged_chunks: Dict[uuid.UUID, RankedChunk] = {}
        rrf_scores: Dict[uuid.UUID, float] = {}

        for source_name, chunk_list in ranked_lists.items():
            source_weight = weights.get(source_name, 1.0)
            for rank_idx, chunk in enumerate(chunk_list, start=1):
                chunk_id = chunk.chunk_id
                contribution = source_weight / float(self.k + rank_idx)
                rrf_scores[chunk_id] = rrf_scores.get(chunk_id, 0.0) + contribution

                if chunk_id not in merged_chunks:
                    # Create copy of chunk
                    merged_chunks[chunk_id] = chunk.model_copy(deep=True)
                    if source_name not in merged_chunks[chunk_id].retrieval_sources:
                        merged_chunks[chunk_id].retrieval_sources.append(source_name)
                else:
                    existing = merged_chunks[chunk_id]
                    if source_name not in existing.retrieval_sources:
                        existing.retrieval_sources.append(source_name)
                    # Merge rank attributes if present
                    if chunk.lexical_rank is not None:
                        existing.lexical_rank = chunk.lexical_rank
                    if chunk.dense_rank is not None:
                        existing.dense_rank = chunk.dense_rank
                    if chunk.graph_rank is not None:
                        existing.graph_rank = chunk.graph_rank
                    # Merge bounding boxes and page numbers if missing
                    for pb in chunk.page_numbers:
                        if pb not in existing.page_numbers:
                            existing.page_numbers.append(pb)
                    for bbox in chunk.bounding_boxes:
                        if bbox not in existing.bounding_boxes:
                            existing.bounding_boxes.append(bbox)

        # Update scores on merged chunks
        candidate_list: List[RankedChunk] = []
        for chunk_id, chunk in merged_chunks.items():
            chunk.score = round(rrf_scores[chunk_id], 6)
            candidate_list.append(chunk)

        # Sort descending by RRF score
        candidate_list.sort(key=lambda c: c.score, reverse=True)

        return candidate_list[:top_k]
