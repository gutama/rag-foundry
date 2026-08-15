"""Unit tests for Reciprocal Rank Fusion (RRF) algorithm (ADR-0016)."""

import uuid
import pytest

from rag_foundry.retrieval.models import RankedChunk


def test_rrf_combines_dense_and_lexical_lists():
    """Test RRF fuses two ranked lists and correctly orders overlapping items."""
    from rag_foundry.retrieval.fusion import ReciprocalRankFusion

    ws_id = uuid.uuid4()
    doc_id = uuid.uuid4()

    chunk_a = uuid.uuid4()
    chunk_b = uuid.uuid4()
    chunk_c = uuid.uuid4()

    dense_list = [
        RankedChunk(
            chunk_id=chunk_a,
            document_version_id=doc_id,
            workspace_id=ws_id,
            text="Chunk A",
            score=0.9,
            dense_rank=1,
            retrieval_sources=["dense"],
        ),
        RankedChunk(
            chunk_id=chunk_b,
            document_version_id=doc_id,
            workspace_id=ws_id,
            text="Chunk B",
            score=0.8,
            dense_rank=2,
            retrieval_sources=["dense"],
        ),
    ]

    lexical_list = [
        RankedChunk(
            chunk_id=chunk_b,
            document_version_id=doc_id,
            workspace_id=ws_id,
            text="Chunk B",
            score=0.85,
            lexical_rank=1,
            retrieval_sources=["lexical"],
        ),
        RankedChunk(
            chunk_id=chunk_c,
            document_version_id=doc_id,
            workspace_id=ws_id,
            text="Chunk C",
            score=0.75,
            lexical_rank=2,
            retrieval_sources=["lexical"],
        ),
    ]

    fusion = ReciprocalRankFusion(k=60)
    fused_results = fusion.fuse(
        ranked_lists={"dense": dense_list, "lexical": lexical_list},
        top_k=3,
    )

    # Chunk B appeared in both lists (rank 2 in dense, rank 1 in lexical)
    # RRF(B) = 1/(60+2) + 1/(60+1) = 0.016129 + 0.016393 = 0.032522
    # RRF(A) = 1/(60+1) = 0.016393
    # RRF(C) = 1/(60+2) = 0.016129
    # Chunk B should rank #1
    assert len(fused_results) == 3
    assert fused_results[0].chunk_id == chunk_b
    assert "dense" in fused_results[0].retrieval_sources
    assert "lexical" in fused_results[0].retrieval_sources
    assert fused_results[0].dense_rank == 2
    assert fused_results[0].lexical_rank == 1

    assert fused_results[1].chunk_id == chunk_a
    assert fused_results[2].chunk_id == chunk_c


def test_rrf_with_custom_weights_and_empty_lists():
    """Test RRF with custom source weights and handling of empty result sets."""
    from rag_foundry.retrieval.fusion import ReciprocalRankFusion

    ws_id = uuid.uuid4()
    chunk_a = uuid.uuid4()

    dense_list = [
        RankedChunk(
            chunk_id=chunk_a,
            document_version_id=uuid.uuid4(),
            workspace_id=ws_id,
            text="Chunk A",
            score=0.9,
            dense_rank=1,
            retrieval_sources=["dense"],
        )
    ]

    fusion = ReciprocalRankFusion(k=60)
    fused = fusion.fuse(
        ranked_lists={"dense": dense_list, "lexical": [], "graph": []},
        weights={"dense": 2.0, "lexical": 1.0, "graph": 1.0},
        top_k=5,
    )

    assert len(fused) == 1
    assert fused[0].chunk_id == chunk_a
    # Score is 2.0 / (60 + 1)
    assert pytest.approx(fused[0].score, rel=1e-3) == (2.0 / 61.0)
