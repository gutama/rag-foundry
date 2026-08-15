"""Unit tests for RerankerService and scoring re-rankers (ADR-0016)."""

import uuid
import pytest

from rag_foundry.retrieval.models import RankedChunk


def test_scoring_reranker_reorders_candidates():
    """Test ScoringReranker refines candidate ranking based on query relevance."""
    from rag_foundry.retrieval.reranking import ScoringReranker

    reranker = ScoringReranker()
    doc_id = uuid.uuid4()
    ws_id = uuid.uuid4()

    chunk_1 = RankedChunk(
        chunk_id=uuid.uuid4(),
        document_version_id=doc_id,
        workspace_id=ws_id,
        text="General corporate overview of office facilities and cafeterias.",
        score=0.5,
    )
    chunk_2 = RankedChunk(
        chunk_id=uuid.uuid4(),
        document_version_id=doc_id,
        workspace_id=ws_id,
        text="Prudential capital adequacy requirements and minimum CET1 ratio of 4.5%.",
        score=0.4,
    )

    query = "What is the minimum CET1 capital adequacy ratio?"
    reranked = reranker.rerank(query=query, candidates=[chunk_1, chunk_2], top_k=2)

    assert len(reranked) == 2
    assert reranked[0].chunk_id == chunk_2.chunk_id
    assert reranked[0].score > reranked[1].score


def test_cross_encoder_reranker_fallback():
    """Test CrossEncoderReranker handles mock / fallback mode gracefully."""
    from rag_foundry.retrieval.reranking import CrossEncoderReranker

    reranker = CrossEncoderReranker(model_name="mock-cross-encoder")
    doc_id = uuid.uuid4()
    ws_id = uuid.uuid4()

    chunk = RankedChunk(
        chunk_id=uuid.uuid4(),
        document_version_id=doc_id,
        workspace_id=ws_id,
        text="Liquidity coverage ratio buffer requirements.",
        score=0.3,
    )

    results = reranker.rerank(
        query="Liquidity coverage ratio", candidates=[chunk], top_k=1
    )
    assert len(results) == 1
    assert results[0].score >= 0.0
