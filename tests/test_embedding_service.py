"""Unit tests for EmbeddingService and deterministic mock/local providers (ADR-0016)."""

import math
import pytest


def test_mock_embedding_service_dimensions_and_norm():
    """Test MockDeterministicEmbeddingService produces unit-normalized vectors with exact dimension."""
    from rag_foundry.retrieval.embeddings import MockDeterministicEmbeddingService

    dim = 384
    service = MockDeterministicEmbeddingService(dimension=dim)
    assert service.dimension == dim

    vec = service.embed_query("Institutional capital requirements")
    assert len(vec) == dim

    # Check vector is normalized (unit length)
    norm = math.sqrt(sum(x * x for x in vec))
    assert pytest.approx(norm, rel=1e-4) == 1.0


def test_mock_embedding_service_deterministic():
    """Test MockDeterministicEmbeddingService generates identical vectors for identical text and distinct for different text."""
    from rag_foundry.retrieval.embeddings import MockDeterministicEmbeddingService

    service = MockDeterministicEmbeddingService(dimension=128)

    vec1 = service.embed_query("Credit risk framework")
    vec2 = service.embed_query("Credit risk framework")
    vec3 = service.embed_query("Operational risk taxonomy")

    assert vec1 == vec2
    assert vec1 != vec3


def test_mock_embedding_service_batch():
    """Test batch embedding generation for document chunk ingestion."""
    from rag_foundry.retrieval.embeddings import MockDeterministicEmbeddingService

    service = MockDeterministicEmbeddingService(dimension=64)
    texts = ["Snippet 1", "Snippet 2", "Snippet 3"]

    embeddings = service.embed_texts(texts)
    assert len(embeddings) == 3
    for emb in embeddings:
        assert len(emb) == 64
        norm = math.sqrt(sum(x * x for x in emb))
        assert pytest.approx(norm, rel=1e-4) == 1.0


def test_empty_or_whitespace_embedding():
    """Test handling of empty strings."""
    from rag_foundry.retrieval.embeddings import MockDeterministicEmbeddingService

    service = MockDeterministicEmbeddingService(dimension=32)
    vec = service.embed_query("")
    assert len(vec) == 32
