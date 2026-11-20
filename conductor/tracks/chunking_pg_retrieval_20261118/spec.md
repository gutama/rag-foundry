# Specification: Phase 5 Completion — Structural Chunking, PostgreSQL/pgvector/FTS Indexing & Ontology Query Expansion

## 1. Overview

Complete Roadmap **Phase 5 (Chunking, Indexing, and Governed Hybrid Retrieval)** by connecting document parsing to durable, governed hybrid search and ontology-aware query expansion. Currently, `IngestionPipeline` persists parsed `Document` rows without chunking or indexing them, `DenseVectorRetriever` and `LexicalRetriever` operate only in memory, and `TaxonomyExpansionBridge` expands queries using SKOS taxonomies alone.

This track delivers:
1. A **structure-aware hierarchical chunker** preserving section hierarchy, atomic tables/figures, page numbers, and normalized bounding boxes (ADR-0002).
2. **Direct PostgreSQL/pgvector and PostgreSQL Full-Text Search (FTS) chunk persistence** behind compact-profile repository/retriever interfaces with pre-retrieval ACL enforcement (ADR-0004, ADR-0005, ADR-0015).
3. **Governed ontology and entity query expansion** integrated alongside SKOS taxonomy expansion with provenance tracing and exact-term protection (ADR-0016).
4. **Ingestion-to-index wiring (`IndexerService`)** and optional local/air-gapped embedding and cross-encoder reranker adapters.

---

## 2. Functional Requirements

### FR-1: Structure-Aware Hierarchical Chunker (`src/rag_foundry/chunking/`)
- **FR-1.1 Input & Output:** Consume a parsed `CanonicalDocument` (ordered `DocumentElement` items) and emit deterministic, ordered `DocumentChunk` domain models carrying `text`, `section_path`, `page_numbers`, `bounding_boxes` (`BoundingBox`), `element_ids`, `element_types`, `checksum` (SHA-256), `chunker_name`, `chunker_version`, and chunk-level metadata.
- **FR-1.2 Heading & Section Hierarchy:** Detect heading boundaries (using `element_type == "heading"`, heading level metadata / markdown `#` prefix, and `parent_element_id` fallback), maintain an active hierarchical `section_path` stack, and flush open prose buffers at heading transitions so chunks never bleed across unrelated sections.
- **FR-1.3 Atomic Tables & Figures:** Keep `table` and `figure` elements intact as dedicated atomic chunks with their active `section_path`. If a table exceeds the configured maximum chunk size, split it strictly on row boundaries while repeating the table header row(s) on every split chunk.
- **FR-1.4 Configurable Prose Sizing & Overlap:** Pack sequential prose/list elements up to configurable `target_chars` / `max_chars` limits with configurable `overlap_chars` (splitting oversized single paragraphs on sentence/word boundaries without mid-word truncation unless a single token exceeds `max_chars`).
- **FR-1.5 Provenance Preservation:** Aggregate sorted unique 1-based `page_numbers` and convert every contributing element's `(x0, y0, x1, y1)` tuple into validated normalized `BoundingBox` objects (`page`, `l`, `t`, `r`, `b`), skipping elements with missing coordinates gracefully without failing chunk creation.

### FR-2: PostgreSQL/pgvector & FTS Chunk Schema and Persistence (`src/rag_foundry/db/`, `migrations/`, `src/rag_foundry/retrieval/`)
- **FR-2.1 ORM & Alembic Migration:** Extend `Chunk` in `src/rag_foundry/db/models.py` and create a new Alembic migration (revising `e2b84f6c9a31`) adding:
  - `chunk_index` (integer order within document version)
  - `bounding_boxes` (JSON list of serialized `BoundingBox` dicts)
  - `security_domain` (indexed `String(128)`, non-null, default `"general"`)
  - `chunk_metadata` (JSON dict for governed metadata filtering)
  - `embedding` (dialect-aware column: PostgreSQL `vector(N)` via `pgvector` DDL + HNSW cosine index; JSON float list fallback on SQLite)
  - `embedding_model` and `embedding_dim` (string + integer recording the model/dimension pinned at index time)
  - `search_vector` (dialect-aware column: PostgreSQL `TSVECTOR` + GIN index; nullable text fallback on SQLite)
  - Composite index on `(workspace_id, security_domain)` to accelerate ACL-filtered queries.
- **FR-2.2 Retriever Protocols & Compact-Profile SQLAlchemy Backends:**
  - Define clean async `DenseRetrieverProtocol` and `LexicalRetrieverProtocol` interfaces shared by the existing in-memory retrievers and the new database-backed compact-profile implementations (`PostgresDenseRetriever` and `PostgresLexicalRetriever`).
  - **PostgreSQL path:** Execute native `pgvector` cosine distance (`<=>`) and native PostgreSQL FTS (`websearch_to_tsquery` / `to_tsquery` + `ts_rank_cd`) with `WHERE` predicates pushed into SQL *before* similarity/rank scoring and `LIMIT`.
  - **SQLite test compatibility:** Provide deterministic SQL-filtered execution on `sqlite+aiosqlite` (filtering workspace, document IDs, security domains, and metadata in the query/store before computing cosine similarity or lexical BM25/phrase scores) so full unit and integration suites run cleanly without requiring a live PostgreSQL instance, supplemented by PostgreSQL SQL compilation and DDL verification tests.
- **FR-2.3 Pre-Retrieval Authorization Enforcement (ADR-0005):** Every database query MUST filter by `workspace_id`, `security_domain IN allowed_domains`, optional `document_ids`, and `metadata_filters` *before* candidate retrieval, fusion, or reranking. When `security_domains` is empty under a `SecurityContext` with no allowed domains, return zero candidates (fail closed).

### FR-3: Governed Ontology & Entity Query Expansion (ADR-0016)
- **FR-3.1 Approved Semantic Sources Only:** Build an `OntologyQueryExpander` (and unified `SemanticQueryExpansionService` composing SKOS taxonomy + ontology + entity expansion) that reads:
  - Only **approved** `OntologyReleaseRecord` releases (`status == "approved"`), matching active classes (`status == "active"`) by `preferred_labels`, traversing bounded `parent_class_uris` / subclass hierarchy, and active properties (`preferred_labels` and `inverse_property_uri` labels). Draft and deprecated releases/terms are ignored.
  - Only **active** `EntityRecord` records scoped to the caller's authorized `workspace_id` and pinned `semantic_profile_id` (plus resolving merged entity aliases via `merged_into_id` redirects to their active canonical survivor).
  - **Strict exclusion:** Unapproved or extracted `SemanticAssertion` records MUST NOT generate expansion terms.
- **FR-3.2 Authorization Before Semantic Disclosure:** Check caller `SecurityContext` authorization for `workspace_id` (and allowed semantic/security scopes) *before* loading or emitting any entity or ontology vocabulary terms so restricted terms cannot leak into expanded queries or traces.
- **FR-3.3 Bounded & Deterministic Expansion Policy:** Support a configurable `ExpansionPolicy` specifying enabled relation types (`preferred_label`, `entity_alias`, `entity_redirect`, `ontology_parent`, `ontology_child`, `ontology_property`, `ontology_inverse`), `max_depth` (default `1`), per-relation decay weights, and `max_expanded_terms` budget (default `12`), with deterministic ordering and deduplication.
- **FR-3.4 Provenance Traces:** Return structured expansion traces recording original query terms, every expanded term, its weight, relationship type, and exact semantic source (`source_type`, `source_uri`, `release_id` / `entity_id`), surfaced in `RetrievalResult.execution_metrics["expansion_trace"]`.
- **FR-3.5 Exact-Term Precision Protection:** Preserve the exact original query in retrieval and scoring (weighting original/exact phrase matches strictly above expanded synonyms so expanded terms cannot demote exact lexical matches below an equivalent non-exact expanded match).

### FR-4: Ingestion-to-Index Wiring & Optional Model Adapters (`src/rag_foundry/ingestion/`, `src/rag_foundry/retrieval/`)
- **FR-4.1 `IndexerService`:** Provide an async `IndexerService` that takes a `CanonicalDocument` (and integrates with `IngestionPipeline` via optional `indexer` / `ingest_and_index`), runs `StructuralChunker`, computes chunk embeddings via `EmbeddingService`, and persists `Chunk` records (including `bounding_boxes`, `security_domain`, `chunk_metadata`, `embedding`, and PostgreSQL FTS vector) atomically within the DB session, returning an `IndexingResult` (document ID, chunk count, chunk IDs, duration).
- **FR-4.2 Optional Local/Air-Gapped Embedding Adapters:** Add:
  - `HttpEmbeddingService` (supporting Ollama `/api/embed` and OpenAI-compatible `/v1/embeddings` endpoints using stdlib/async-safe HTTP with timeout and dimension validation).
  - `SentenceTransformerEmbeddingService` (lazy import of `sentence_transformers` with clear actionable error if optional extra is not installed).
  - Keep `MockDeterministicEmbeddingService` as the deterministic default for tests.
- **FR-4.3 Optional Cross-Encoder Reranker Implementation:** Complete `CrossEncoderReranker` so it can lazily load `sentence_transformers.CrossEncoder` (or accept an injected scorer callable) to score `(query, chunk.text)` pairs and normalize scores to `[0.0, 1.0]`, falling back cleanly to `ScoringReranker` only when explicitly configured for fallback mode.
- **FR-4.4 Pipeline Reproducibility & Backward Compatibility:** Update `RetrievalPipeline` to accept both in-memory and DB-backed dense/lexical retrievers and the unified `SemanticQueryExpansionService` (remaining backward-compatible with `TaxonomyExpansionBridge`), ensuring deterministic tie-breaking on equal scores (by `chunk_id`).

---

## 3. Non-Functional Requirements

- **Determinism & Reproducibility:** Given identical documents, chunking config, embedding provider, and retrieval profile, chunk checksums, expanded terms, and ranked retrieval outputs MUST be deterministic across runs (explicit secondary sort keys on ties).
- **Zero Unauthorized Leakage:** Unauthorized workspace or security-domain chunks MUST NEVER be loaded into candidate lists, fused, reranked, or exposed via query expansion traces.
- **Lightweight Core Dependencies:** Do not add heavy ML packages (`torch`, `sentence-transformers`) as mandatory core dependencies in `pyproject.toml`; expose them as optional extras or lazy runtime imports.
- **Code Style & Quality Gates:** Conform to `conductor/code_styleguides/python.md` (Google Python style, full type hints, Google-style docstrings) and `conductor/workflow.md` (TDD red-green-refactor, >80% coverage on all new modules).

---

## 4. Acceptance Criteria

1. **Structural Chunking & Provenance:** Parsing sample PDF/DOCX/XLSX fixtures and running `StructuralChunker` produces chunks with accurate `section_path`, intact tables (or header-repeated row splits when oversized), valid `page_numbers`, normalized `BoundingBox` coordinates, and deterministic checksums.
2. **Database Persistence & PostgreSQL Compatibility:** Alembic migration upgrades and downgrades cleanly; `IndexerService` persists chunks with embeddings, bounding boxes, and ACL fields; `PostgresDenseRetriever` and `PostgresLexicalRetriever` execute end-to-end on SQLite in tests and compile valid PostgreSQL `pgvector` (`<=>`) and FTS (`to_tsvector` / `websearch_to_tsquery` / `ts_rank_cd`) SQL with pre-retrieval `WHERE` ACL filters.
3. **Authorization-Before-Retrieval:** Automated security tests prove that chunks from another workspace or disallowed `security_domain` never enter dense, lexical, fused, or reranked candidate sets, and an actor with zero allowed security domains receives zero results.
4. **Traceable Ontology & Entity Expansion:** Queries matching approved ontology classes/properties or active/merged workspace entities expand deterministically within configured depth and budget limits, record complete semantic source URIs in `execution_metrics["expansion_trace"]`, exclude draft releases and unapproved extracted assertions, and never leak cross-workspace entity aliases.
5. **Exact-Term Non-Regression:** A benchmark test suite verifies that enabling taxonomy/ontology expansion improves recall on synonym/alias/hierarchy queries while exact-term and identifier queries maintain top-1 rank parity with expansion disabled.
6. **Reproducible Hybrid Baseline & Optional Adapters:** End-to-end `IngestionPipeline` -> `IndexerService` -> `RetrievalPipeline` runs reproducibly with identical ranking across repeated executions, and optional HTTP/CrossEncoder adapters pass unit tests with mocked transport/model callables.

---

## 5. Out of Scope

- **ADR-0003 `IndexPublication` staged builds & atomic publication switching** (deferred per track scope; chunks persist directly against document versions and semantic profiles).
- **Scale-profile distributed stores** (Qdrant, OpenSearch, Redis workers/queues).
- **Grounded LLM answer generation, citation alignment, and QA modes** (Phase 6).
- **FastAPI HTTP routes and Assay web UI screens** (Phase 7).
- **LightRAG production graph adapter & graph partitioning** (Phases 9–10).
- **Ragas / DeepEval CI release gates** (Phase 8).
