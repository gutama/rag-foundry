# Implementation Plan: Phase 5 Completion — Structural Chunking, PostgreSQL/pgvector/FTS Indexing & Ontology Query Expansion

## Phase 1: Structure-Aware Hierarchical Chunker & Provenance Preservation [checkpoint: 6992399]

- [x] Task: Build chunking domain models and heading-hierarchy tracking 0e751a9
  - [x] Write failing unit tests in `tests/test_structural_chunker.py` for `ChunkingConfig`, `DocumentChunk`, deterministic SHA-256 checksums, `chunker_name`/`chunker_version`, and heading stack (`section_path`) transitions across heading levels and `parent_element_id`
  - [x] Implement `src/rag_foundry/chunking/__init__.py`, `src/rag_foundry/chunking/models.py`, and heading/section buffer management in `src/rag_foundry/chunking/structural.py` to pass tests
  - [x] Refactor and verify >80% module coverage
- [x] Task: Implement atomic tables/figures, oversized table row splitting, and prose overlap 394d550
  - [x] Write failing unit tests covering atomic `table` and `figure` chunks, oversized table splitting on row boundaries with repeated headers, configurable `target_chars`/`max_chars`/`overlap_chars` for prose and list items, and sentence/word-boundary splitting of oversized paragraphs
  - [x] Implement table/figure atomicity, header-repeating row splitting, and configurable prose packing/overlap in `src/rag_foundry/chunking/structural.py`
  - [x] Refactor and verify edge cases (empty elements, single long tokens, tables without markdown headers)
- [x] Task: Preserve page numbers, normalized bounding boxes, and parser fixture integration 6992399
  - [x] Write failing tests verifying sorted unique 1-based `page_numbers`, conversion of element `(x0, y0, x1, y1)` tuples into validated `BoundingBox` objects, graceful handling of missing coordinates, and end-to-end parsing -> chunking across `sample_pdf_bytes`, `sample_docx_bytes`, and `sample_xlsx_bytes`
  - [x] Implement provenance aggregation in `src/rag_foundry/chunking/structural.py` and confirm all chunker unit and fixture integration tests pass
- [x] Task: Phase Verification & Checkpoint (Refer to workflow.md)

## Phase 2: PostgreSQL/pgvector & FTS Schema, Migration & Compact-Profile Retrievers [checkpoint: 5cca335]

- [x] Task: Add dialect-aware pgvector/tsvector types, extend Chunk ORM model, and write Alembic migration 76b1bef
  - [x] Write failing tests in `tests/test_chunk_schema.py` verifying `Chunk` new columns (`chunk_index`, `bounding_boxes`, `security_domain`, `chunk_metadata`, `embedding`, `embedding_model`, `embedding_dim`, `search_vector`), PostgreSQL DDL compilation (`vector(N)`, `TSVECTOR`, HNSW/GIN/ACL indexes), SQLite round-trip persistence, and Alembic upgrade/downgrade from revision `e2b84f6c9a31`
  - [x] Implement dialect-aware SQLAlchemy column types in `src/rag_foundry/db/types.py`, extend `Chunk` in `src/rag_foundry/db/models.py`, and add Alembic migration in `migrations/versions/`
  - [x] Run tests and verify clean Alembic upgrade/downgrade and >80% coverage
- [x] Task: Implement retriever protocols and compact-profile `PostgresDenseRetriever` 2760502
  - [x] Write failing tests in `tests/test_postgres_dense_retriever.py` covering `DenseRetrieverProtocol` conformance, workspace isolation, `security_domain` pre-retrieval filtering, fail-closed empty allowed domains, `document_ids` and `metadata_filters`, deterministic tie-breaking by `chunk_id`, cosine similarity scoring on SQLite, and PostgreSQL `<=>` SQL compilation with `WHERE` predicates pushed before `ORDER BY`/`LIMIT`
  - [x] Implement `src/rag_foundry/retrieval/protocols.py` and `PostgresDenseRetriever` in `src/rag_foundry/retrieval/postgres_dense.py` (ensuring existing `DenseVectorRetriever` satisfies the protocol)
  - [x] Refactor and verify >80% coverage
- [x] Task: Implement compact-profile `PostgresLexicalRetriever` with PostgreSQL FTS and ACL pushdown 5cca335
  - [x] Write failing tests in `tests/test_postgres_lexical_retriever.py` covering `LexicalRetrieverProtocol` conformance, phrase and token search, workspace/domain/document/metadata pre-retrieval ACL filters, fail-closed empty allowed domains, deterministic tie-breaking, SQLite lexical scoring fallback, and PostgreSQL `websearch_to_tsquery`/`ts_rank_cd` SQL compilation with `WHERE` predicates pushed before ranking
  - [x] Implement `PostgresLexicalRetriever` in `src/rag_foundry/retrieval/postgres_lexical.py` (ensuring existing `LexicalRetriever` satisfies the protocol)
  - [x] Refactor and verify >80% coverage
- [x] Task: Phase Verification & Checkpoint (Refer to workflow.md)

## Phase 3: Governed Ontology & Entity Query Expansion (ADR-0016)

- [x] Task: Build `ExpansionPolicy`, provenance trace models, and approved-ontology expansion 2b61a98
  - [x] Write failing tests in `tests/test_ontology_query_expansion.py` covering `ExpansionPolicy` bounds (`max_depth`, relation weights, `max_expanded_terms`), matching active classes by `preferred_labels`, traversing `parent_class_uris`/subclasses and active property labels/inverses, strictly ignoring `draft`/`deprecated` releases and terms, and recording semantic source URIs and release IDs in traces
  - [x] Implement `ExpansionPolicy`, `SemanticExpansionTerm`, `SemanticExpansionTrace`, and `OntologyQueryExpander` in `src/rag_foundry/retrieval/ontology_expansion.py`
  - [x] Refactor and verify deterministic ordering, deduplication, and >80% coverage
- [ ] Task: Add workspace-scoped entity alias/redirect expansion with caller authorization
  - [ ] Write failing tests in `tests/test_entity_query_expansion.py` verifying expansion over active `EntityRecord` preferred labels and aliases, resolution of merged entity aliases via `merged_into_id` redirects, strict workspace/`semantic_profile_id` isolation, caller `SecurityContext` authorization before loading vocabulary, and strict non-use of unapproved extracted `SemanticAssertion` records
  - [ ] Implement authorized entity expansion in `src/rag_foundry/retrieval/ontology_expansion.py`
  - [ ] Refactor and verify zero cross-workspace vocabulary leakage
- [ ] Task: Build unified `SemanticQueryExpansionService` with exact-term protection and pipeline integration
  - [ ] Write failing tests in `tests/test_semantic_expansion_pipeline.py` verifying composition of SKOS taxonomy + ontology + entity expanders, full provenance output in `RetrievalResult.execution_metrics["expansion_trace"]`, backward compatibility with `TaxonomyExpansionBridge`, terminology recall gains on alias/hierarchy queries, and exact-term/identifier top-1 non-regression
  - [ ] Implement `SemanticQueryExpansionService` in `src/rag_foundry/retrieval/expansion.py` and integrate exact-term preservation and unified expansion into `RetrievalPipeline` and `LexicalRetriever` / `PostgresLexicalRetriever`
  - [ ] Refactor and confirm all existing and new retrieval tests pass
- [ ] Task: Phase Verification & Checkpoint (Refer to workflow.md)

## Phase 4: Ingestion-to-Index Wiring, Optional Model Adapters & End-to-End Reproducibility

- [ ] Task: Implement `IndexerService` and wire `IngestionPipeline` to chunking and DB indexing
  - [ ] Write failing tests in `tests/test_indexer_service.py` covering `IndexerService.index_document`, atomic chunk persistence with embeddings, bounding boxes, `security_domain`, and metadata, re-indexing/idempotency behavior, and `IngestionPipeline` end-to-end `ingest_and_index` flow
  - [ ] Implement `src/rag_foundry/ingestion/indexer.py` (`IndexerService`, `IndexingResult`) and extend `IngestionPipeline` with optional `indexer` / `ingest_and_index` support (preserving full backward compatibility for `process_file`)
  - [ ] Refactor and verify >80% coverage
- [ ] Task: Implement optional local/air-gapped embedding and cross-encoder reranker adapters
  - [ ] Write failing tests in `tests/test_model_adapters.py` covering `HttpEmbeddingService` (Ollama `/api/embed` and OpenAI-compatible `/v1/embeddings` payloads, error handling, dimension checks), lazy `SentenceTransformerEmbeddingService` (mocked backend and clear `ImportError` when uninstalled), and `CrossEncoderReranker` (custom/lazy scorer normalization to `[0.0, 1.0]`, deterministic tie-breaking, explicit fallback behavior)
  - [ ] Implement `HttpEmbeddingService` and `SentenceTransformerEmbeddingService` in `src/rag_foundry/retrieval/embeddings.py`, complete `CrossEncoderReranker` in `src/rag_foundry/retrieval/reranking.py`, and add optional extras (`[ml]` / `[pgvector]`) in `pyproject.toml` without adding heavy mandatory dependencies
  - [ ] Refactor and verify >80% coverage
- [ ] Task: End-to-end Phase 5 exit-criteria integration & regression suite
  - [ ] Write failing integration tests in `tests/test_phase5_end_to_end.py` validating all four Phase 5 exit criteria end-to-end (`IngestionPipeline` -> `IndexerService` -> `RetrievalPipeline` with DB-backed dense + lexical retrievers + unified semantic expansion): (1) zero unauthorized chunk entry across workspaces/domains, (2) identical reproducible ranking across repeated runs, (3) complete semantic expansion provenance trace, and (4) zero exact-term top-1 regression when semantic expansion is enabled
  - [ ] Ensure deterministic tie-breaking across `ReciprocalRankFusion`, `RerankerService`, and DB retrievers, and verify the full `pytest` suite and coverage gates pass
- [ ] Task: Phase Verification & Checkpoint (Refer to workflow.md)
