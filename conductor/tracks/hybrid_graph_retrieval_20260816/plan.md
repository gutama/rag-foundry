# Implementation Plan: Hybrid & Graph Retrieval Engine with Claim-Level Citations & Governance

## Phase 1: Core Interfaces, Data Models & Security Guard [checkpoint: efcf3c6]
- [x] Task: Define Retrieval Data Models & Query Structures 21b40b9
  - [x] Write unit tests for `RetrievalQuery`, `RetrievalResult`, `RankedChunk`, `EvidenceItem`, and `AbstentionResult` in `tests/test_retrieval_models.py`
  - [x] Implement Pydantic v2 domain models and interfaces in `src/rag_foundry/retrieval/models.py`
  - [x] Verify test suite passes and meets coverage standards
- [x] Task: Implement Authorization-Before-Retrieval Security Guard efcf3c6
  - [x] Write unit tests for `SecurityContext`, `WorkspaceGuard`, and ACL permission rules in `tests/test_retrieval_security.py`
  - [x] Implement security validator in `src/rag_foundry/retrieval/security.py`
  - [x] Verify security rejection on cross-workspace/unauthorized queries
- [x] Task: Phase Verification & Checkpoint (Refer to workflow.md) efcf3c6

## Phase 2: Dense Vector Retrieval & Embedding Abstraction [checkpoint: c64bd5f]
- [x] Task: Implement Embedding Service & Mock Provider f04c8ee
  - [x] Write unit tests for `EmbeddingService` interface and deterministic test provider in `tests/test_embedding_service.py`
  - [x] Implement `EmbeddingService` abstraction in `src/rag_foundry/retrieval/embeddings.py`
  - [x] Verify embedding generation and vector dimensionality validation
- [x] Task: Implement pgvector Dense Retriever c64bd5f
  - [x] Write unit and integration tests for `DenseVectorRetriever` with cosine similarity in `tests/test_dense_retrieval.py`
  - [x] Implement `DenseVectorRetriever` in `src/rag_foundry/retrieval/dense.py`
  - [x] Verify metadata and workspace filtering during dense vector search
- [x] Task: Phase Verification & Checkpoint (Refer to workflow.md) c64bd5f

## Phase 3: Governed Lexical Search & SKOS Query Expansion
- [ ] Task: Implement PostgreSQL Full-Text Search Retriever
  - [ ] Write unit and integration tests for `LexicalRetriever` (tsvector/tsquery, rank weighting, dictionary configs) in `tests/test_lexical_retrieval.py`
  - [ ] Implement `LexicalRetriever` in `src/rag_foundry/retrieval/lexical.py`
  - [ ] Verify exact phrase matching and FTS ranking performance
- [ ] Task: Implement SKOS Query Expansion Pipeline Integration
  - [ ] Write unit tests for query expansion bridge connecting `TaxonomyQueryExpander` to lexical searches in `tests/test_expansion_retrieval.py`
  - [ ] Implement expansion bridge and term tracing in `src/rag_foundry/retrieval/expansion.py`
  - [ ] Verify relationship decay weights and term lineage preservation
- [ ] Task: Phase Verification & Checkpoint (Refer to workflow.md)

## Phase 4: Hybrid Fusion, Reranking & Graph Provider
- [ ] Task: Implement Reciprocal Rank Fusion (RRF) Engine
  - [ ] Write unit tests for RRF algorithm with configurable $k$, weights, and multi-source list fusion in `tests/test_fusion.py`
  - [ ] Implement `ReciprocalRankFusion` in `src/rag_foundry/retrieval/fusion.py`
  - [ ] Verify rank merging, tie-breaking, and score normalization
- [ ] Task: Implement Cross-Encoder & Scoring Reranker Service
  - [ ] Write unit tests for `RerankerService` and fallback scoring re-rankers in `tests/test_reranker.py`
  - [ ] Implement reranker classes in `src/rag_foundry/retrieval/reranking.py`
  - [ ] Verify top-k candidate scoring and ordering
- [ ] Task: Implement Graph Retrieval Provider Interface & Conformance Provider
  - [ ] Write unit tests for `GraphRetrievalProvider` interface and `ConformanceGraphProvider` in `tests/test_graph_retrieval.py`
  - [ ] Implement graph provider and subgraph evidence formatters in `src/rag_foundry/retrieval/graph.py`
  - [ ] Verify entity linking and relationship attribution formatting
- [ ] Task: Phase Verification & Checkpoint (Refer to workflow.md)

## Phase 5: Citation Assembly, Abstention Engine & End-to-End Orchestrator
- [ ] Task: Implement Grounded Evidence Assembly & Abstention Engine
  - [ ] Write unit tests for claim-level citations, coordinate linking, and low-confidence abstention in `tests/test_evidence_abstention.py`
  - [ ] Implement evidence assembler and abstention evaluator in `src/rag_foundry/retrieval/evidence.py`
  - [ ] Verify abstention trigger when confidence is below configured threshold
- [ ] Task: Implement End-to-End Hybrid Retrieval Orchestrator
  - [ ] Write end-to-end integration tests for `RetrievalPipeline` in `tests/test_retrieval_pipeline.py`
  - [ ] Implement `RetrievalPipeline` orchestrator unifying all stages in `src/rag_foundry/retrieval/pipeline.py`
  - [ ] Verify full lifecycle: Auth -> Expansion -> Parallel Retrieval -> RRF -> Reranking -> Citations/Abstention
- [ ] Task: Phase Verification & Checkpoint (Refer to workflow.md)
