# Specification: Hybrid & Graph Retrieval Engine with Claim-Level Citations & Governance

## 1. Overview & Strategic Intent
The **Hybrid & Graph Retrieval Engine** is the core retrieval subsystem of RAG Foundry. It unifies dense semantic search (`pgvector`), governed lexical search (PostgreSQL Full-Text Search), graph entity/relationship traversal (`GraphRetrievalProvider`), and SKOS taxonomy query expansion into a cohesive, high-precision retrieval pipeline. 

It enforces an **Authorization-Before-Retrieval** security model, fuses multi-modal signals via **Reciprocal Rank Fusion (RRF)**, refines candidates via **Cross-Encoder Reranking**, and emits structured **Claim-Level Citations** with explicit evidence abstention when confidence thresholds are unmet.

---

## 2. Functional Requirements

- **FR-1: Dense Vector Retrieval & Embedding Abstraction**
  - Define an abstract `EmbeddingService` interface with support for local `sentence-transformers` and deterministic mock/test embeddings.
  - Implement a `pgvector` dense retriever supporting cosine similarity, L2 distance, and HNSW index querying.
  - Support chunk filtering by `workspace_id`, `document_version_id`, and metadata constraints.

- **FR-2: Governed Lexical Full-Text Search (FTS)**
  - Implement a PostgreSQL FTS retriever utilizing `to_tsvector` and `plainto_tsquery` / `to_tsquery` with English/multilingual dictionary configurations.
  - Support exact phrase matching and weighted text ranking (`ts_rank_cd`).
  - Seamlessly consume expanded OR queries produced by SKOS taxonomy expansion.

- **FR-3: SKOS Taxonomy Semantic Query Expansion**
  - Integrate `TaxonomyQueryExpander` to enrich incoming queries with `prefLabel`, `altLabel`, `broader`, and `narrower` terms.
  - Apply relationship decay weights (e.g. broader=0.7, narrower=0.5).
  - Trace expanded terms in query execution metadata.

- **FR-4: Reciprocal Rank Fusion (RRF) & Candidate Reranking**
  - Implement RRF algorithm combining ranked lists from lexical, dense, and graph retrievers using constant $k=60$.
  - Implement a modular `RerankerService` interface with a `CrossEncoderReranker` implementation and fallback scoring reranker.
  - Output unified, calibrated ranking scores.

- **FR-5: Graph Retrieval Provider Interface & Conformance Provider**
  - Implement a strict, decoupled `GraphRetrievalProvider` interface.
  - Provide an in-memory/mock `ConformanceGraphProvider` for graph queries, entity extraction, and subgraph evidence synthesis.
  - Structure evidence subgraphs with entities, relations, and source chunk attribution.

- **FR-6: Authorization-Before-Retrieval Security Guard**
  - Enforce workspace isolation, user roles, and security domain ACLs prior to executing vector, lexical, or graph searches.
  - Reject unauthorized query contexts before executing data queries or revealing metadata.

- **FR-7: Claim-Level Citations & Grounded Evidence Assembly**
  - Assemble `EvidenceItem` objects containing chunk IDs, document titles, page numbers, section paths, and confidence scores.
  - Implement an **Evidence Abstention Engine** that evaluates combined retrieval confidence against a configurable threshold; returns an explicit `AbstentionResult` when confidence is insufficient.

- **FR-8: End-to-End Orchestrator Pipeline**
  - Orchestrate the complete query flow: `Auth Guard` -> `SKOS Query Expander` -> `Parallel (Lexical + Dense + Graph)` -> `RRF Fusion` -> `Reranking` -> `Citation & Abstention Assembly`.
  - Provide execution metrics (timings per phase, term expansion trace, fusion scores).

---

## 3. Non-Functional Requirements
- **Test Coverage & TDD:** Strict >85% code coverage with unit and integration tests across all modules.
- **Latency & Performance:** Hybrid retrieval execution < 150ms (non-graph) and < 350ms (with graph) for top-k=20 chunks.
- **Air-Gapped & Framework-Independent:** No dependencies on external SaaS APIs; runs fully on local PostgreSQL/pgvector and local models.

---

## 4. Acceptance Criteria
- [ ] All dense, lexical, graph, fusion, reranking, and citation components have comprehensive unit tests.
- [ ] RRF correctly merges disparate ranking lists with configurable $k$.
- [ ] Security guard prevents unauthorized retrieval across workspace boundaries.
- [ ] Low-confidence queries trigger clear abstention signals.
- [ ] End-to-end integration tests confirm full query lifecycle execution with zero database leaks.

---

## 5. Out of Scope for this Track
- REST API endpoint routing (will be implemented in a dedicated FastAPI track).
- LightRAG remote cluster deployment/network orchestration (interface adapter hook only).
- Generation & LLM response synthesis (will consume this retrieval engine in the generation track).
