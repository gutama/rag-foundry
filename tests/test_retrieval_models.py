"""Unit tests for retrieval domain models (ADR-0016 / Spec-Driven Development)."""

import uuid
from typing import List

import pytest
from pydantic import ValidationError


def test_bounding_box_model():
    """Test BoundingBox validation and coordinate properties."""
    from rag_foundry.retrieval.models import BoundingBox

    bbox = BoundingBox(page=1, l=0.1, t=0.2, r=0.8, b=0.9)
    assert bbox.page == 1
    assert bbox.l == 0.1
    assert bbox.t == 0.2
    assert bbox.r == 0.8
    assert bbox.b == 0.9

    # Coordinate boundary checks
    with pytest.raises(ValidationError):
        BoundingBox(page=0, l=0.1, t=0.2, r=0.8, b=0.9)  # Page must be >= 1

    with pytest.raises(ValidationError):
        BoundingBox(page=1, l=-0.1, t=0.2, r=0.8, b=0.9)  # Coordinates must be >= 0.0


def test_retrieval_filter_model():
    """Test RetrievalFilter with workspace isolation and metadata predicates."""
    from rag_foundry.retrieval.models import RetrievalFilter

    ws_id = uuid.uuid4()
    doc_id = uuid.uuid4()
    r_filter = RetrievalFilter(
        workspace_id=ws_id,
        document_ids=[doc_id],
        metadata_filters={"category": "governance"},
        security_domains=["finance", "compliance"],
    )
    assert r_filter.workspace_id == ws_id
    assert r_filter.document_ids == [doc_id]
    assert r_filter.metadata_filters["category"] == "governance"
    assert "compliance" in r_filter.security_domains


def test_retrieval_query_model():
    """Test RetrievalQuery validation, defaults, and parameters."""
    from rag_foundry.retrieval.models import RetrievalFilter, RetrievalQuery

    ws_id = uuid.uuid4()
    query = RetrievalQuery(
        query_text="What are the capital requirements?",
        filter=RetrievalFilter(workspace_id=ws_id),
        top_k=10,
        enable_lexical=True,
        enable_dense=True,
        enable_graph=True,
        enable_expansion=True,
        min_relevance_score=0.4,
    )
    assert query.query_text == "What are the capital requirements?"
    assert query.top_k == 10
    assert query.enable_graph is True
    assert query.min_relevance_score == 0.4

    # Top-k bounds
    with pytest.raises(ValidationError):
        RetrievalQuery(
            query_text="invalid top_k",
            filter=RetrievalFilter(workspace_id=ws_id),
            top_k=0,
        )


def test_ranked_chunk_and_evidence_item():
    """Test RankedChunk and EvidenceItem citation formatting."""
    from rag_foundry.retrieval.models import (
        BoundingBox,
        EvidenceItem,
        RankedChunk,
    )

    chunk_id = uuid.uuid4()
    doc_version_id = uuid.uuid4()
    ws_id = uuid.uuid4()

    ranked = RankedChunk(
        chunk_id=chunk_id,
        document_version_id=doc_version_id,
        workspace_id=ws_id,
        text="Institutional regulatory compliance guidelines.",
        score=0.89,
        retrieval_sources=["dense", "lexical"],
        lexical_rank=2,
        dense_rank=1,
        section_path=["Section 3", "Capital Adequacy"],
        page_numbers=[12, 13],
    )
    assert ranked.score == 0.89
    assert ranked.lexical_rank == 2
    assert ranked.dense_rank == 1

    bbox = BoundingBox(page=12, l=0.1, t=0.2, r=0.5, b=0.6)
    evidence = EvidenceItem(
        chunk_id=chunk_id,
        document_id=doc_version_id,
        document_title="Basel III Guidelines",
        snippet="Institutional regulatory compliance guidelines.",
        confidence_score=0.89,
        page_numbers=[12, 13],
        section_path=["Section 3", "Capital Adequacy"],
        bounding_boxes=[bbox],
        attribution_tag="[Doc: Basel III Guidelines, p.12-13]",
    )
    assert evidence.attribution_tag == "[Doc: Basel III Guidelines, p.12-13]"
    assert len(evidence.bounding_boxes) == 1


def test_abstention_result_and_retrieval_result():
    """Test AbstentionResult and complete RetrievalResult containers."""
    from rag_foundry.retrieval.models import (
        AbstentionResult,
        EvidenceItem,
        RankedChunk,
        RetrievalResult,
    )

    abstention = AbstentionResult(
        abstained=True,
        reason="Maximum chunk relevance score (0.21) is below threshold (0.40).",
        threshold=0.40,
        highest_score=0.21,
    )
    assert abstention.abstained is True
    assert abstention.threshold == 0.40

    result = RetrievalResult(
        query_text="Unmatched query",
        ranked_chunks=[],
        evidence_items=[],
        abstention=abstention,
        execution_metrics={"duration_ms": 45.2, "fusion_strategy": "rrf"},
    )
    assert result.is_abstained is True
    assert result.execution_metrics["fusion_strategy"] == "rrf"
