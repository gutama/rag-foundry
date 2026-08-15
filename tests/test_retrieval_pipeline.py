"""End-to-end integration tests for RetrievalPipeline orchestrator (ADR-0016)."""

import uuid
import pytest

from rag_foundry.retrieval.dense import DenseVectorRecord, DenseVectorRetriever
from rag_foundry.retrieval.embeddings import MockDeterministicEmbeddingService
from rag_foundry.retrieval.evidence import AbstentionEngine, EvidenceAssembler
from rag_foundry.retrieval.expansion import TaxonomyExpansionBridge
from rag_foundry.retrieval.fusion import ReciprocalRankFusion
from rag_foundry.retrieval.graph import (
    ConformanceGraphProvider,
    GraphEntity,
    GraphRelation,
)
from rag_foundry.retrieval.lexical import LexicalRecord, LexicalRetriever
from rag_foundry.retrieval.models import (
    BoundingBox,
    RetrievalFilter,
    RetrievalQuery,
)
from rag_foundry.retrieval.reranking import ScoringReranker
from rag_foundry.retrieval.security import (
    SecurityAuthorizationError,
    SecurityContext,
    WorkspaceGuard,
)
from rag_foundry.taxonomy.models import SKOSConceptModel, SKOSConceptSchemeModel


@pytest.fixture
def retrieval_environment():
    """Setup a populated retrieval environment with dense, lexical, graph, and taxonomy elements."""
    ws_id = uuid.uuid4()
    doc_id = uuid.uuid4()
    chunk_1 = uuid.uuid4()
    chunk_2 = uuid.uuid4()

    # 1. Taxonomy
    scheme = SKOSConceptSchemeModel(
        scheme_id=str(uuid.uuid4()),
        uri="urn:scheme:prudential",
        title="Prudential Standards",
        concepts=[
            SKOSConceptModel(
                scheme_uri="urn:scheme:prudential",
                uri="urn:concept:cet1",
                pref_label="Common Equity Tier 1",
                alt_labels=["CET1", "Core Equity Tier 1"],
            )
        ],
    )

    # 2. Embedding & Dense
    emb_service = MockDeterministicEmbeddingService(dimension=64)
    dense_retriever = DenseVectorRetriever(embedding_service=emb_service)

    # 3. Lexical
    lexical_retriever = LexicalRetriever()

    # 4. Graph
    graph_provider = ConformanceGraphProvider()

    # Populate records
    bbox_1 = BoundingBox(page=10, l=0.1, t=0.1, r=0.9, b=0.5)
    c1_text = "The Basel III framework requires institutions to hold a minimum CET1 ratio of 4.5% of risk-weighted assets."
    c2_text = "Countercyclical capital buffer requires an additional 0% to 2.5% of CET1 capital during periods of high credit growth."

    dense_records = [
        DenseVectorRecord(
            chunk_id=chunk_1,
            document_version_id=doc_id,
            workspace_id=ws_id,
            text=c1_text,
            page_numbers=[10],
            section_path=["Capital Adequacy", "CET1"],
            bounding_boxes=[bbox_1],
            security_domain="finance",
        ),
        DenseVectorRecord(
            chunk_id=chunk_2,
            document_version_id=doc_id,
            workspace_id=ws_id,
            text=c2_text,
            page_numbers=[14],
            section_path=["Capital Buffers", "CCyB"],
            security_domain="finance",
        ),
    ]

    lexical_records = [
        LexicalRecord(
            chunk_id=chunk_1,
            document_version_id=doc_id,
            workspace_id=ws_id,
            text=c1_text,
            page_numbers=[10],
            section_path=["Capital Adequacy", "CET1"],
            bounding_boxes=[bbox_1],
            security_domain="finance",
        ),
        LexicalRecord(
            chunk_id=chunk_2,
            document_version_id=doc_id,
            workspace_id=ws_id,
            text=c2_text,
            page_numbers=[14],
            section_path=["Capital Buffers", "CCyB"],
            security_domain="finance",
        ),
    ]

    graph_entities = [
        GraphEntity(
            entity_id="e_basel",
            workspace_id=ws_id,
            name="Basel III",
            entity_type="Standard",
            description="Global bank regulatory standard.",
            source_chunk_ids=[chunk_1],
        ),
        GraphEntity(
            entity_id="e_cet1",
            workspace_id=ws_id,
            name="CET1",
            entity_type="CapitalMetric",
            description="Common Equity Tier 1 capital ratio.",
            source_chunk_ids=[chunk_1, chunk_2],
        ),
    ]
    graph_relations = [
        GraphRelation(
            relation_id="rel_1",
            workspace_id=ws_id,
            source_entity="Basel III",
            target_entity="CET1",
            relation_type="defines_minimum",
            description="Basel III defines minimum 4.5% CET1 ratio.",
            source_chunk_ids=[chunk_1],
        )
    ]

    return {
        "workspace_id": ws_id,
        "doc_id": doc_id,
        "doc_titles": {doc_id: "Basel III Capital Rules"},
        "scheme": scheme,
        "emb_service": emb_service,
        "dense_retriever": dense_retriever,
        "dense_records": dense_records,
        "lexical_retriever": lexical_retriever,
        "lexical_records": lexical_records,
        "graph_provider": graph_provider,
        "graph_entities": graph_entities,
        "graph_relations": graph_relations,
    }


@pytest.mark.asyncio
async def test_retrieval_pipeline_full_lifecycle(retrieval_environment):
    """Test full end-to-end retrieval pipeline execution."""
    from rag_foundry.retrieval.pipeline import RetrievalPipeline

    env = retrieval_environment
    ws_id = env["workspace_id"]

    await env["dense_retriever"].index_records(env["dense_records"])
    await env["lexical_retriever"].index_records(env["lexical_records"])
    await env["graph_provider"].index_graph_elements(
        entities=env["graph_entities"], relations=env["graph_relations"]
    )

    pipeline = RetrievalPipeline(
        dense_retriever=env["dense_retriever"],
        lexical_retriever=env["lexical_retriever"],
        graph_provider=env["graph_provider"],
        expansion_bridge=TaxonomyExpansionBridge(scheme=env["scheme"]),
        fusion_engine=ReciprocalRankFusion(k=60),
        reranker=ScoringReranker(),
        evidence_assembler=EvidenceAssembler(doc_titles=env["doc_titles"]),
        abstention_engine=AbstentionEngine(),
        guard=WorkspaceGuard(),
    )

    sec_ctx = SecurityContext(
        user_id="analyst_user",
        allowed_workspaces=[ws_id],
        allowed_security_domains=["finance"],
    )

    query = RetrievalQuery(
        query_text="What are the minimum Core Equity Tier 1 requirements?",
        filter=RetrievalFilter(workspace_id=ws_id, security_domains=["finance"]),
        enable_dense=True,
        enable_lexical=True,
        enable_graph=True,
        enable_expansion=True,
        top_k=5,
        min_relevance_score=0.1,
    )

    result = await pipeline.execute(query=query, security_context=sec_ctx)

    assert result.is_abstained is False
    assert len(result.ranked_chunks) >= 1
    assert len(result.evidence_items) >= 1
    assert result.evidence_items[0].document_title == "Basel III Capital Rules"
    assert result.evidence_items[0].attribution_tag == "[Doc: Basel III Capital Rules, p.10]"
    assert "duration_ms" in result.execution_metrics


@pytest.mark.asyncio
async def test_retrieval_pipeline_security_rejection(retrieval_environment):
    """Test RetrievalPipeline rejects unauthorized workspace queries before retrieval."""
    from rag_foundry.retrieval.pipeline import RetrievalPipeline

    env = retrieval_environment
    ws_id = env["workspace_id"]
    unauthorized_ws = uuid.uuid4()

    pipeline = RetrievalPipeline(
        dense_retriever=env["dense_retriever"],
        lexical_retriever=env["lexical_retriever"],
        guard=WorkspaceGuard(),
    )

    sec_ctx = SecurityContext(
        user_id="guest_user",
        allowed_workspaces=[ws_id],
    )

    query = RetrievalQuery(
        query_text="Confidential data",
        filter=RetrievalFilter(workspace_id=unauthorized_ws),
    )

    with pytest.raises(SecurityAuthorizationError):
        await pipeline.execute(query=query, security_context=sec_ctx)
