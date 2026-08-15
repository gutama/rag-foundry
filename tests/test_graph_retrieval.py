"""Unit tests for GraphRetrievalProvider and ConformanceGraphProvider (ADR-0016)."""

import uuid
import pytest

from rag_foundry.retrieval.models import RetrievalFilter, RetrievalQuery


@pytest.mark.asyncio
async def test_conformance_graph_provider_indexing_and_traversal():
    """Test ConformanceGraphProvider extracts entity subgraphs and emits ranked chunks."""
    from rag_foundry.retrieval.graph import (
        ConformanceGraphProvider,
        GraphEntity,
        GraphRelation,
    )

    ws_id = uuid.uuid4()
    doc_id = uuid.uuid4()
    chunk_1 = uuid.uuid4()
    chunk_2 = uuid.uuid4()

    provider = ConformanceGraphProvider()

    # Index graph entities and relations
    e_basel = GraphEntity(
        entity_id="entity_basel_iii",
        workspace_id=ws_id,
        name="Basel III",
        entity_type="RegulatoryFramework",
        description="International regulatory accord for banks.",
        source_chunk_ids=[chunk_1],
    )
    e_cet1 = GraphEntity(
        entity_id="entity_cet1",
        workspace_id=ws_id,
        name="Common Equity Tier 1",
        entity_type="CapitalComponent",
        description="Highest quality regulatory capital consisting of common shares and retained earnings.",
        source_chunk_ids=[chunk_2],
    )
    rel = GraphRelation(
        relation_id="rel_1",
        workspace_id=ws_id,
        source_entity="Basel III",
        target_entity="Common Equity Tier 1",
        relation_type="mandates_minimum_ratio",
        description="Basel III mandates a minimum 4.5% CET1 ratio.",
        source_chunk_ids=[chunk_1, chunk_2],
    )

    await provider.index_graph_elements(
        entities=[e_basel, e_cet1], relations=[rel]
    )

    query = RetrievalQuery(
        query_text="What does Basel III mandate for Common Equity Tier 1?",
        filter=RetrievalFilter(workspace_id=ws_id),
        enable_graph=True,
        top_k=5,
    )

    ranked_chunks, evidence = await provider.query_graph(query)

    assert len(ranked_chunks) >= 1
    assert ranked_chunks[0].workspace_id == ws_id
    assert "graph" in ranked_chunks[0].retrieval_sources
    assert ranked_chunks[0].graph_rank == 1

    assert evidence is not None
    assert len(evidence.entities) >= 1
    assert len(evidence.relations) >= 1
    assert "Basel III" in evidence.subgraph_text
    assert "Common Equity Tier 1" in evidence.subgraph_text


@pytest.mark.asyncio
async def test_conformance_graph_provider_workspace_isolation():
    """Test Graph provider strictly isolates entities by workspace."""
    from rag_foundry.retrieval.graph import (
        ConformanceGraphProvider,
        GraphEntity,
    )

    provider = ConformanceGraphProvider()
    target_ws = uuid.uuid4()
    foreign_ws = uuid.uuid4()

    await provider.index_graph_elements(
        entities=[
            GraphEntity(
                entity_id="e_foreign",
                workspace_id=foreign_ws,
                name="Confidential M&A Project",
                entity_type="Project",
                description="Secret acquisition project.",
            ),
            GraphEntity(
                entity_id="e_target",
                workspace_id=target_ws,
                name="Public Liquidity Framework",
                entity_type="Framework",
                description="Public standard.",
            ),
        ]
    )

    query = RetrievalQuery(
        query_text="Project and framework details",
        filter=RetrievalFilter(workspace_id=target_ws),
        enable_graph=True,
    )

    ranked_chunks, evidence = await provider.query_graph(query)
    assert len(ranked_chunks) == 1
    assert ranked_chunks[0].workspace_id == target_ws
    assert "Public Liquidity" in ranked_chunks[0].text
