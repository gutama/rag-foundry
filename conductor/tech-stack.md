# Technology Stack: RAG Foundry

## Core Architecture
- **Architecture Pattern:** Framework-independent modular monolith with asynchronous background workers.

## Application Layers
- **Backend API & Processing:** Python 3.11+ (FastAPI, Pydantic, Celery/Task queue)
- **Frontend Application:** TypeScript, React, TailwindCSS, Vite
- **Data & Storage Plane:**
  - PostgreSQL 16+ (Metadata, Governance, Taxonomies/Ontologies)
  - `pgvector` (Vector Similarity Search)
  - PostgreSQL Full-Text Search (Lexical Search)
  - MinIO / Enterprise S3 (Object Storage for raw & canonical artifacts)
- **Graph & Semantic Plane:**
  - LightRAG Service Adapter (Isolated Graph Retrieval)
  - nano-GraphRAG (Experimentation & Conformance Testing)
  - Open Knowledge Format (OKF) JSON/YAML Schema Validation
- **Scale / Enterprise Options:** Qdrant (Dense Vector), OpenSearch (Lexical Search), Redis (Caching & Job Queue)

## Models & AI Services
- **LLM Serving:** Ollama / vLLM (Local / Air-gapped execution)
- **Embeddings & Reranking:** sentence-transformers, HuggingFace Cross-Encoder Reranker

## Observability & Evaluation
- **Tracing & Monitoring:** Langfuse, OpenTelemetry
- **RAG Metric Engine:** Ragas (faithfulness, context precision, answer relevancy, synthetic test generation)
- **CI/CD Release Gates:** DeepEval (pytest-native LLM assertions, regression testing, quality thresholds)
- **Domain-Specific Evaluation:** Custom Golden Dataset Evaluator (authorization leakage, taxonomy, ontology, graph, OKF metrics)
