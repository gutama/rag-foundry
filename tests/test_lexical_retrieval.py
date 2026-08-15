"""Unit tests for LexicalRetriever and PostgreSQL FTS / BM25 search (ADR-0016)."""

import uuid
import pytest

from rag_foundry.retrieval.models import RetrievalFilter, RetrievalQuery


@pytest.mark.asyncio
async def test_lexical_retriever_indexing_and_search():
    """Test LexicalRetriever indexing records and executing full-text lexical search."""
    from rag_foundry.retrieval.lexical import LexicalRecord, LexicalRetriever

    retriever = LexicalRetriever()
    ws_id = uuid.uuid4()
    doc_id = uuid.uuid4()

    records = [
        LexicalRecord(
            chunk_id=uuid.uuid4(),
            document_version_id=doc_id,
            workspace_id=ws_id,
            text="The capital adequacy ratio is calculated using Tier 1 and Tier 2 capital divided by risk-weighted assets.",
            section_path=["Capital Standards"],
            page_numbers=[3],
            security_domain="finance",
        ),
        LexicalRecord(
            chunk_id=uuid.uuid4(),
            document_version_id=doc_id,
            workspace_id=ws_id,
            text="General guidelines for corporate office security badges and visitor registration.",
            section_path=["Security", "Badges"],
            page_numbers=[10],
            security_domain="facilities",
        ),
        LexicalRecord(
            chunk_id=uuid.uuid4(),
            document_version_id=doc_id,
            workspace_id=ws_id,
            text="Detailed risk-weighted assets measurement methodology for market risk exposures.",
            section_path=["Market Risk"],
            page_numbers=[7],
            security_domain="finance",
        ),
    ]

    await retriever.index_records(records)

    query = RetrievalQuery(
        query_text="capital adequacy risk-weighted assets",
        filter=RetrievalFilter(
            workspace_id=ws_id,
            security_domains=["finance"],
        ),
        top_k=2,
    )

    results = await retriever.retrieve(query)
    assert len(results) == 2
    assert all(r.workspace_id == ws_id for r in results)
    assert results[0].lexical_rank == 1
    assert results[1].lexical_rank == 2
    assert "lexical" in results[0].retrieval_sources
    assert "capital adequacy" in results[0].text.lower()


@pytest.mark.asyncio
async def test_lexical_retriever_exact_phrase_and_or_query():
    """Test LexicalRetriever handling exact phrases and OR-separated search terms."""
    from rag_foundry.retrieval.lexical import LexicalRecord, LexicalRetriever

    retriever = LexicalRetriever()
    ws_id = uuid.uuid4()

    await retriever.index_records(
        [
            LexicalRecord(
                chunk_id=uuid.uuid4(),
                document_version_id=uuid.uuid4(),
                workspace_id=ws_id,
                text="The entity shall maintain common equity tier 1 capital exceeding 4.5%.",
            ),
            LexicalRecord(
                chunk_id=uuid.uuid4(),
                document_version_id=uuid.uuid4(),
                workspace_id=ws_id,
                text="The institution shall maintain liquidity coverage ratio exceeding 100%.",
            ),
        ]
    )

    query = RetrievalQuery(
        query_text='"common equity tier 1" OR "liquidity coverage ratio"',
        filter=RetrievalFilter(workspace_id=ws_id),
        top_k=5,
    )

    results = await retriever.retrieve(query)
    assert len(results) == 2


@pytest.mark.asyncio
async def test_lexical_retriever_workspace_and_domain_isolation():
    """Test LexicalRetriever strictly blocks cross-workspace and unauthorized domain candidates."""
    from rag_foundry.retrieval.lexical import LexicalRecord, LexicalRetriever

    retriever = LexicalRetriever()
    target_ws = uuid.uuid4()
    forbidden_ws = uuid.uuid4()

    await retriever.index_records(
        [
            LexicalRecord(
                chunk_id=uuid.uuid4(),
                document_version_id=uuid.uuid4(),
                workspace_id=forbidden_ws,
                text="Secret audit report containing capital reserves.",
                security_domain="audit",
            ),
            LexicalRecord(
                chunk_id=uuid.uuid4(),
                document_version_id=uuid.uuid4(),
                workspace_id=target_ws,
                text="Public audit report containing capital reserves.",
                security_domain="public",
            ),
        ]
    )

    query = RetrievalQuery(
        query_text="capital reserves",
        filter=RetrievalFilter(
            workspace_id=target_ws,
            security_domains=["public"],
        ),
        top_k=5,
    )

    results = await retriever.retrieve(query)
    assert len(results) == 1
    assert results[0].workspace_id == target_ws
    assert "Public audit" in results[0].text
