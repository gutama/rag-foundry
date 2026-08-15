"""End-to-end governed hybrid and graph retrieval pipeline orchestrator (ADR-0016)."""

import asyncio
import time
from typing import Any, Dict, List, Optional, Tuple

from rag_foundry.retrieval.dense import DenseVectorRetriever
from rag_foundry.retrieval.evidence import AbstentionEngine, EvidenceAssembler
from rag_foundry.retrieval.expansion import TaxonomyExpansionBridge
from rag_foundry.retrieval.fusion import ReciprocalRankFusion
from rag_foundry.retrieval.graph import (
    GraphEvidence,
    GraphRetrievalProvider,
)
from rag_foundry.retrieval.lexical import LexicalRetriever
from rag_foundry.retrieval.models import (
    RankedChunk,
    RetrievalQuery,
    RetrievalResult,
)
from rag_foundry.retrieval.reranking import RerankerService, ScoringReranker
from rag_foundry.retrieval.security import (
    SecurityContext,
    WorkspaceGuard,
)


class RetrievalPipeline:
    """Orchestrates governed hybrid search across lexical, dense, graph, and taxonomy planes."""

    def __init__(
        self,
        dense_retriever: Optional[DenseVectorRetriever] = None,
        lexical_retriever: Optional[LexicalRetriever] = None,
        graph_provider: Optional[GraphRetrievalProvider] = None,
        expansion_bridge: Optional[TaxonomyExpansionBridge] = None,
        fusion_engine: Optional[ReciprocalRankFusion] = None,
        reranker: Optional[RerankerService] = None,
        evidence_assembler: Optional[EvidenceAssembler] = None,
        abstention_engine: Optional[AbstentionEngine] = None,
        guard: Optional[WorkspaceGuard] = None,
    ) -> None:
        """Initialize RetrievalPipeline with modular retrieval components."""
        self.dense_retriever = dense_retriever
        self.lexical_retriever = lexical_retriever
        self.graph_provider = graph_provider
        self.expansion_bridge = expansion_bridge
        self.fusion_engine = fusion_engine or ReciprocalRankFusion(k=60)
        self.reranker = reranker or ScoringReranker()
        self.evidence_assembler = evidence_assembler or EvidenceAssembler()
        self.abstention_engine = abstention_engine or AbstentionEngine()
        self.guard = guard or WorkspaceGuard()

    async def execute(
        self,
        query: RetrievalQuery,
        security_context: Optional[SecurityContext] = None,
    ) -> RetrievalResult:
        """Execute complete retrieval workflow with security enforcement and fusion.

        Args:
            query: RetrievalQuery specification.
            security_context: Actor SecurityContext for authorization verification.

        Returns:
            RetrievalResult containing ranked chunks, citations, abstention, and metrics.
        """
        start_time = time.time()

        # Step 1: Authorization-Before-Retrieval Guard
        if security_context is not None:
            query = self.guard.validate_and_sanitize_query(query, security_context)

        # Step 2: SKOS Taxonomy Query Expansion
        expansion_trace: Dict[str, Any] = {}
        lexical_query = query
        if self.expansion_bridge and query.enable_expansion:
            lexical_query, expansion_trace = self.expansion_bridge.expand_retrieval_query(
                query
            )

        # Step 3: Multi-modal Parallel Candidate Retrieval
        tasks = []
        source_keys = []

        if query.enable_dense and self.dense_retriever:
            tasks.append(self.dense_retriever.retrieve(query))
            source_keys.append("dense")

        if query.enable_lexical and self.lexical_retriever:
            tasks.append(self.lexical_retriever.retrieve(lexical_query))
            source_keys.append("lexical")

        if query.enable_graph and self.graph_provider:
            tasks.append(self.graph_provider.query_graph(query))
            source_keys.append("graph")

        ranked_lists: Dict[str, List[RankedChunk]] = {}
        graph_evidence: Optional[GraphEvidence] = None

        if tasks:
            raw_results = await asyncio.gather(*tasks)
            for key, result_item in zip(source_keys, raw_results):
                if key == "graph":
                    chunks, g_ev = result_item
                    ranked_lists["graph"] = chunks
                    graph_evidence = g_ev
                else:
                    ranked_lists[key] = result_item

        # Step 4: Reciprocal Rank Fusion
        fused_candidates = self.fusion_engine.fuse(
            ranked_lists=ranked_lists,
            top_k=query.top_k * 2,
        )

        # Step 5: Candidate Reranking
        reranked_chunks = self.reranker.rerank(
            query=query.query_text,
            candidates=fused_candidates,
            top_k=query.top_k,
        )

        # Step 6: Grounded Evidence Citation Assembly
        evidence_items = self.evidence_assembler.assemble_evidence(reranked_chunks)

        # Step 7: Abstention Evaluation
        abstention = self.abstention_engine.evaluate_abstention(
            ranked_chunks=reranked_chunks,
            threshold=query.min_relevance_score,
        )

        duration_ms = round((time.time() - start_time) * 1000.0, 3)

        execution_metrics: Dict[str, Any] = {
            "duration_ms": duration_ms,
            "sources_queried": source_keys,
            "dense_candidate_count": len(ranked_lists.get("dense", [])),
            "lexical_candidate_count": len(ranked_lists.get("lexical", [])),
            "graph_candidate_count": len(ranked_lists.get("graph", [])),
            "fused_count": len(fused_candidates),
            "reranked_count": len(reranked_chunks),
            "expansion_trace": expansion_trace,
        }
        if graph_evidence:
            execution_metrics["graph_evidence_subgraph"] = graph_evidence.subgraph_text

        return RetrievalResult(
            query_text=query.query_text,
            ranked_chunks=reranked_chunks,
            evidence_items=evidence_items,
            abstention=abstention,
            execution_metrics=execution_metrics,
        )
