"""Unit tests for DenseVectorRetriever and semantic vector search (ADR-0016)."""

import uuid
import pytest

from rag_foundry.retrieval.embeddings import MockDeterministicEmbeddingService
from rag_foundry.retrieval.models import (
    RankedChunk,
    RetrievalFilter,
    RetrievalQuery,
)


@pytest.mark.asyncio
async def test_dense_retriever_indexing_and_search():
    """Test DenseVectorRetriever indexes chunk vectors and retrieves ranked candidates."""
    from rag_foundry.retrieval.dense import DenseVectorRecord, DenseVectorRetriever

    embedding_service = MockDeterministicEmbeddingService(dimension=64)
    retriever = DenseVectorRetriever(embedding_service=embedding_service)

    ws_id = uuid.uuid4()
    doc_id = uuid.uuid4()

    chunks = [
        DenseVectorRecord(
            chunk_id=uuid.uuid4(),
            document_version_id=doc_id,
            workspace_id=ws_id,
            text="The Basel III regulatory capital framework defines Tier 1 capital ratios.",
            section_path=["Capital Standards", "Tier 1"],
            page_numbers=[4],
            security_domain="finance",
        ),
        DenseVectorRecord(
            chunk_id=uuid.uuid4(),
            document_version_id=doc_id,
            workspace_id=ws_id,
            text="Guidelines for workplace ergonomics and desk lighting.",
            section_path=["Facilities", "Ergonomics"],
            page_numbers=[12],
            security_domain="general",
        ),
        DenseVectorRecord(
            chunk_id=uuid.uuid4(),
            document_version_id=doc_id,
            workspace_id=ws_id,
            text="Credit risk mitigation techniques and collateral valuation rules under Basel III.",
            section_path=["Credit Risk", "Collateral"],
            page_numbers=[8],
            security_domain="finance",
        ),
    ]

    await retriever.index_records(chunks)

    query = RetrievalQuery(
        query_text="What are the capital requirements under Basel III?",
        filter=RetrievalFilter(
            workspace_id=ws_id,
            security_domains=["finance"],
        ),
        top_k=2,
    )

    results = await retriever.retrieve(query)
    assert len(results) == 2
    assert all(r.workspace_id == ws_id for r in results)
    assert results[0].dense_rank == 1
    assert results[1].dense_rank == 2
    assert "dense" in results[0].retrieval_sources
    assert results[0].score >= results[1].score


@pytest.mark.asyncio
async def test_dense_retriever_workspace_isolation():
    """Test DenseVectorRetriever strictly respects workspace isolation."""
    from rag_foundry.retrieval.dense import DenseVectorRecord, DenseVectorRetriever

    embedding_service = MockDeterministicEmbeddingService(dimension=32)
    retriever = DenseVectorRetriever(embedding_service=embedding_service)

    target_ws = uuid.uuid4()
    foreign_ws = uuid.uuid4()

    await retriever.index_records(
        [
            DenseVectorRecord(
                chunk_id=uuid.uuid4(),
                document_version_id=uuid.uuid4(),
                workspace_id=foreign_ws,
                text="Foreign secret document on capital allocation.",
            ),
            DenseVectorRecord(
                chunk_id=uuid.uuid4(),
                document_version_id=uuid.uuid4(),
                workspace_id=target_ws,
                text="Target workspace public compliance report.",
            ),
        ]
    )

    query = RetrievalQuery(
        query_text="capital allocation",
        filter=RetrievalFilter(workspace_id=target_ws),
        top_k=5,
    )

    results = await retriever.retrieve(query)
    assert len(results) == 1
    assert results[0].workspace_id == target_ws
    assert "Target workspace" in results[0].text


@pytest.mark.asyncio
async def test_dense_retriever_min_score_filter():
    """Test DenseVectorRetriever drops chunks below min_relevance_score."""
    from rag_foundry.retrieval.dense import DenseVectorRecord, DenseVectorRetriever

    embedding_service = MockDeterministicEmbeddingService(dimension=32)
    retriever = DenseVectorRetriever(embedding_service=embedding_service)

    ws_id = uuid.uuid4()
    await retriever.index_records(
        [
            DenseVectorRecord(
                chunk_id=uuid.uuid4(),
                document_version_id=uuid.uuid4(),
                workspace_id=ws_id,
                text="Completely unrelated recipes for baking sourdough bread.",
            )
        ]
    )

    query = RetrievalQuery(
        query_text="High frequency algorithmic trading risk",
        filter=RetrievalFilter(workspace_id=ws_id),
        min_relevance_score=0.99,  # Very high threshold
    )

    results = await retriever.retrieve(query)
    assert len(results) == 0
