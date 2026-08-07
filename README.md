# RAG Foundry

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Code Style: Google](https://img.shields.io/badge/code%20style-google-000000.svg)](https://google.github.io/styleguide/pyguide.html)
[![Test Coverage: 95%](https://img.shields.io/badge/coverage-95%25-brightgreen.svg)]()

> A governed, private, production-oriented Retrieval-Augmented Generation (RAG) platform for institutional document intelligence.

---

## 🌟 Overview

**RAG Foundry** delivers enterprise-grade knowledge discovery by combining modular document ingestion, hybrid retrieval (lexical + dense + reranking), versioned metadata governance, SKOS taxonomy registries, OWL-lite ontology management, LightRAG graph integration, and Open Knowledge Format (OKF) interoperability—all backed by claim-level citations and full support for local, air-gapped deployments.

The platform is designed around a **framework-independent canonical domain core**, preventing tight coupling to any third-party framework (e.g., LlamaIndex or LangChain).

---

## ✨ Key Capabilities

1. **Governed Knowledge Plane**
   - **MetadataRegistry:** Versioned metadata schemas with Pydantic v2 and JSON Schema (Draft 2020-12) validation.
   - **SKOS Taxonomy Service:** Concept schemes with multilingual labels (`prefLabel`, `altLabel`), `broader`/`narrower` hierarchical relationships, and candidate entity resolution.
   - **Ontology & Assertion Validation:** OWL-lite ontologies with SHACL constraint enforcement and candidate assertion approval gates.
   - **Stewardship Workflows:** Role-based change management, entity resolution review, and audit logging.

2. **Hybrid & Graph-Enhanced Retrieval**
   - **Default Path:** Governed lexical (PostgreSQL FTS / OpenSearch) + dense vector (pgvector / Qdrant) retrieval fused with Reciprocal Rank Fusion (RRF) and Cross-Encoder reranking.
   - **Graph Retrieval:** Optional LightRAG service adapter for entity/relation graph traversal, isolated behind a strict `GraphRetrievalProvider` boundary.
   - **Semantic Expansion:** Traceable query expansion using SKOS taxonomy labels and ontology mappings.

3. **Institutional Document Intelligence**
   - Single-parse distribution of canonical document elements and structural chunks.
   - OCR fallback routing (PaddleOCR/Docling) for scanned and complex-layout documents.
   - Claim-level citations linked directly to source locations, page numbers, and bounding boxes.
   - Explicit abstention when evidence is insufficient.

4. **Open Knowledge Format (OKF)**
   - Portable, Git-backed authoring and exchange format for institutional knowledge bundles without database lock-in.

5. **Security & Authorization**
   - "Authorization-before-retrieval" policy: ACL checks occur prior to metadata disclosure, vector search, graph traversal, or generation.
   - Multi-tenant security domain graph partitioning.

6. **Air-Gapped Local Execution**
   - Native support for local deployments using PostgreSQL, pgvector, Ollama/vLLM, MinIO, and local rerankers.

---

## 🏗️ Architecture & Storage Profiles

RAG Foundry is structured as a **modular monolith with asynchronous background workers**, designed for deployment under two operational profiles:

```
┌──────────────────────────────────────────────────────────────────┐
│ 1. Experience and Application Plane                              │
│ Chat │ Collections │ Sources │ Viewer │ Catalog │ Admin │ Evals │
└───────────────────────────────┬──────────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────────┐
│ 2. Knowledge Governance and Semantic Interoperability Plane      │
│ Metadata Registry │ Taxonomy Registry │ Ontology Registry        │
│ Entity Resolution │ Semantic Validation │ Stewardship │ OKF      │
└───────────────┬───────────────────────────────┬──────────────────┘
                │                               │
┌───────────────▼────────────────┐  ┌──────────▼───────────────────┐
│ 3. Retrieval and Generation   │  │ 4. Ingestion and Processing  │
│ Hybrid retrieval              │  │ Connectors and synchronization│
│ Graph retrieval               │  │ Parsing and OCR              │
│ Evidence fusion               │  │ Metadata extraction          │
│ Grounded generation           │  │ Semantic enrichment          │
│ Citations and abstention      │  │ Indexing and publication     │
└───────────────┬────────────────┘  └──────────┬───────────────────┘
                │                               │
                └───────────────┬───────────────┘
                                ▼
┌──────────────────────────────────────────────────────────────┐
│ 5. Data, Observability, Evaluation, and Audit Plane          │
│ PostgreSQL │ Vector │ Lexical │ Graph │ Object Storage      │
│ Langfuse │ OpenTelemetry │ Ragas │ DeepEval │ Audit Events      │
└──────────────────────────────────────────────────────────────┘
```

- **Compact Profile (Single-Node / Air-Gapped):** PostgreSQL, pgvector, PostgreSQL Full-Text Search, local filesystem / MinIO, Ollama / vLLM, local rerankers.
- **Scale Profile (Distributed / Cloud):** PostgreSQL (metadata & governance), Qdrant (dense vector), OpenSearch (lexical), Redis (caching & queues), isolated LightRAG cluster, Kubernetes & Helm.

---

## 🛠️ Technology Stack

| Layer | Technologies |
|---|---|
| **Core Architecture** | Framework-independent modular monolith + Celery background workers |
| **Backend API** | Python 3.11+, FastAPI, Pydantic v2, Async SQLAlchemy 2.0, asyncpg |
| **Database & ORM** | PostgreSQL 16+, Async SQLAlchemy 2.0, Alembic migrations |
| **Vector & Search** | `pgvector` (compact), Qdrant (scale), PostgreSQL FTS (compact), OpenSearch (scale) |
| **Metadata & Governance** | Pydantic v2, `jsonschema` (Draft 2020-12), SKOS, RDF/OWL/SHACL, OKF |
| **Models & Gateway** | LiteLLM gateway, Ollama / vLLM, `sentence-transformers`, HF Cross-Encoder |
| **Graph Provider** | LightRAG (behind provider boundary adapter), nano-GraphRAG (conformance) |
| **Evaluation & Tracing** | Langfuse, OpenTelemetry, Ragas (RAG metrics engine), DeepEval (CI release gates) |

---

## 📁 Repository Structure

```text
rag-foundry/
├── src/rag_foundry/
│   ├── core/           # Core configuration, settings & security guardrails
│   ├── db/             # SQLAlchemy 2.0 ORM models, async session & engine
│   ├── metadata/       # MetadataRegistry & JSON Schema validation service
│   └── taxonomy/       # SKOS TaxonomyService & candidate entity resolution
├── migrations/         # Alembic async database migration scripts
├── tests/              # pytest async unit & integration test suites
├── docs/
│   ├── adr/            # 26 Accepted Architecture Decision Records (ADRs)
│   └── architecture/   # Comprehensive ARCHITECTURE.md specification
├── pyproject.toml      # Build system and dependencies configuration
└── alembic.ini         # Alembic database migration configuration
```

---

## 🚀 Quickstart Guide

### Prerequisites
- **Python 3.11+**
- **PostgreSQL 16+** (with `pgvector` extension) or SQLite (for local testing)

### Installation

1. **Clone repository and set up environment:**
   ```bash
   git clone https://github.com/gutama/rag-foundry.git
   cd rag-foundry
   python3 -m venv .venv
   source .venv/bin/activate
   ```

2. **Install dependencies:**
   ```bash
   pip install -e .[dev]
   ```

3. **Configure Environment:**
   Create a `.env` file in the root directory:
   ```env
   ENVIRONMENT=development
   STORAGE_PROFILE=compact
   POSTGRES_DSN=postgresql+asyncpg://user:password@localhost:5432/rag_foundry
   SECRET_KEY=your-secure-secret-key-here
   LOG_LEVEL=INFO
   ```

4. **Run Database Migrations:**
   ```bash
   alembic upgrade head
   ```

5. **Run Test Suite & Coverage:**
   ```bash
   pytest tests/ --cov=src/rag_foundry --cov-report=term-missing
   ```

---

## 📜 Architecture Decision Records (ADRs)

The design of RAG Foundry is governed by **26 Accepted Architecture Decision Records** located in [`docs/adr/`](docs/adr/README.md):

- [ADR-0001](docs/adr/0001-modular-monolith-and-worker-topology.md): Modular monolith and worker topology
- [ADR-0002](docs/adr/0002-canonical-document-evidence-and-semantic-models.md): Canonical document, evidence, and semantic models
- [ADR-0004](docs/adr/0004-compact-and-scale-storage-profiles.md): Compact and scale storage profiles
- [ADR-0005](docs/adr/0005-authorization-before-retrieval-and-semantic-disclosure.md): Authorization before retrieval policy
- [ADR-0006](docs/adr/0006-model-gateway-and-approved-profiles.md): Model gateway and approved profiles
- [ADR-0010](docs/adr/0010-taxonomy-representation-and-skos-interoperability.md): Taxonomy representation and SKOS interoperability
- [ADR-0017](docs/adr/0017-lightrag-provider-boundary.md): LightRAG provider boundary
- [ADR-0021](docs/adr/0021-okf-import-export-git-curation-and-publication.md): OKF import/export & Git curation
- [ADR-0026](docs/adr/0026-ragas-and-deepeval-evaluation-framework-adoption.md): Ragas and DeepEval evaluation framework adoption
- *(See [docs/adr/README.md](docs/adr/README.md) for the full index of ADRs 0001–0026).*

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
