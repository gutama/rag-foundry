# Product Definition: RAG Foundry

## Vision & Core Concept
RAG Foundry is a governed, private, production-oriented retrieval-augmented generation (RAG) platform for institutional document intelligence. It delivers enterprise-grade knowledge discovery by combining modular document ingestion, hybrid retrieval (lexical + dense + reranking), versioned metadata governance, taxonomy/ontology registries, LightRAG graph integration, and Open Knowledge Format (OKF) interoperability—all with claim-level citations and full support for local, air-gapped deployments.

## Key Features & Capabilities
1. **Governed Knowledge Plane:** Metadata registries, taxonomy/ontology management, entity resolution, and stewardship to ensure metadata schema compliance before retrieval or generation.
2. **Hybrid & Graph Retrieval:** Lexical + dense vector search combined with cross-encoder reranking and optional LightRAG graph-enhanced retrieval.
3. **Institutional Document Intelligence:** Deep document parsing for tables, figures, equations, and page-coordinate citations.
4. **Open Knowledge Format (OKF):** Portable import/export and Git-based curation for knowledge bundles without database lock-in.
5. **Security & Access Control:** Fine-grained authorization enforced prior to retrieval, reranking, graph traversal, or generation.
6. **Air-Gapped Local Execution:** Native support for PostgreSQL, pgvector, Ollama/vLLM, MinIO, and local rerankers.

## Target Audience & Use Cases
- **Audience:** Analysts, researchers, knowledge stewards, data governance teams, and platform operators.
- **Use Cases:** Institutional document Q&A, policy & regulatory compliance analysis, structured knowledge extraction, and governed semantic search.
