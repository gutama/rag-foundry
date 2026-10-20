# RAG Foundry Architecture

**Status:** Proposed  
**Version:** 0.2  
**Date:** 2026-08-07  
**Audience:** Engineering, security, platform operations, knowledge management, data governance, product, and model-evaluation teams

## 1. Purpose

RAG Foundry is a governed, private, production-oriented retrieval-augmented generation platform for institutional document intelligence.

The project combines:

- modular ingestion, scheduling, observability, and evaluation patterns;
- document-centric user experience, hybrid retrieval, rich parsing, and citations;
- governed metadata, taxonomies, ontologies, and semantic enrichment;
- Open Knowledge Format (OKF) import, export, and Git-based curation;
- optional graph-enhanced retrieval through LightRAG;
- a small nano-GraphRAG adapter for experimentation and conformance testing.

The platform is a new implementation. It is not a direct merge or fork of RAG Blueprint, Kotaemon, LightRAG, or nano-GraphRAG.

## 2. Architectural Decision Summary

1. Build a framework-independent canonical domain core.
2. Start as a modular monolith with independently scalable workers.
3. Add a first-class **Knowledge Governance and Semantic Interoperability Plane**.
4. Parse documents once and distribute canonical elements and chunks to all downstream systems.
5. Govern metadata through versioned schemas, mappings, validation, quality rules, ownership, and stewardship.
6. Represent taxonomies as governed concept schemes with multilingual labels and SKOS-compatible semantics.
7. Represent ontologies as versioned classes, properties, constraints, identity rules, and mappings.
8. Treat extracted entities and relations as candidate assertions until validation and provenance checks succeed.
9. Use OKF as a portable authoring and exchange format, not as the transactional system of record.
10. Use lexical + dense + reranking as the default retrieval path.
11. Add LightRAG as an optional graph-evidence provider guided by approved taxonomies and ontologies.
12. Use nano-GraphRAG only for experiments, tests, and provider conformance.
13. Keep final generation, citations, authorization, and evaluation inside RAG Foundry.
14. Enforce access control before metadata disclosure, retrieval, reranking, graph traversal, or generation.
15. Preserve immutable document, semantic-profile, and index lineage.
16. Require evidence-linked structured answers and explicit abstention.
17. Run quality, semantic-governance, security, deletion, and OKF round-trip tests as release gates.
18. Support fully local and air-gapped deployments.

## 3. Goals

RAG Foundry must:

- ingest governed sources incrementally;
- preserve source versions, metadata, permissions, and lineage;
- parse native and scanned documents;
- support tables, figures, equations, and page coordinates;
- validate metadata against versioned institutional schemas;
- classify assets using governed taxonomies;
- resolve entities against an authoritative identity layer;
- validate graph assertions against approved ontologies and constraints;
- support exact-term, semantic, and relationship-oriented retrieval;
- use taxonomy labels and ontology mappings for multilingual query expansion;
- provide claim-level citations linked to source locations;
- warn or abstain when evidence is insufficient;
- import and export curated knowledge bundles using OKF;
- support local and approved remote models;
- trace and reproduce every answer and semantic transformation;
- evaluate retrieval, citations, faithfulness, semantic quality, and authorization;
- propagate source updates and deletions to every active index and semantic projection.

## 4. Non-Goals for the First Release

The first release will not provide:

- unrestricted autonomous agents;
- arbitrary MCP or external tool execution;
- user-supplied model endpoints;
- unrestricted public web search;
- one global graph spanning incompatible security domains;
- GraphRAG as the universal default;
- automated publication of unreviewed extracted assertions as authoritative knowledge;
- unrestricted ontology evolution by language models;
- OKF as the primary transactional database;
- a permanent dependency on Gradio, Chainlit, or another RAG UI framework;
- silent online fallback from local to external models.

## 5. Architectural Planes

RAG Foundry is organized into five logical planes.

```text
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
┌──────────────────────────────────────────────────────────────────┐
│ 5. Data, Observability, Evaluation, and Audit Plane              │
│ PostgreSQL │ Vector │ Lexical │ Graph │ Object Storage          │
│ Langfuse │ OpenTelemetry │ Golden Datasets │ Audit Events       │
└──────────────────────────────────────────────────────────────────┘
```

The semantic-governance plane is not a side utility. It governs ingestion, retrieval, graph extraction, user navigation, curation, and evaluation.

## 6. System Context

```text
┌──────────────────────────────────────────────────────────────┐
│                         End Users                            │
│ Analysts │ Researchers │ Curators │ Stewards │ Administrators│
└─────────────────────────────┬────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│                    RAG Foundry Web App                       │
│ Chat │ Collections │ Sources │ Viewer │ Catalog │ Evals     │
└─────────────────────────────┬────────────────────────────────┘
                              │ HTTPS / SSE
                              ▼
┌──────────────────────────────────────────────────────────────┐
│                     RAG Foundry API                          │
│ Identity │ Authorization │ Documents │ Semantics │ Answers  │
└──────────────┬───────────────────────────────┬───────────────┘
               │                               │
               ▼                               ▼
┌──────────────────────────────┐  ┌────────────────────────────┐
│ Interactive Query Pipeline   │  │ Background Workflows       │
│ Hybrid + graph retrieval     │  │ Sync │ Parse │ Enrich      │
│ Semantic expansion           │  │ Validate │ Index │ Publish │
│ Generation and citations     │  │ Delete │ Rebuild │ Evaluate│
└──────────────┬───────────────┘  └─────────────┬──────────────┘
               │                                │
               └───────────────┬────────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────┐
│                        Data Plane                            │
│ PostgreSQL │ Vector Index │ Lexical Index │ Object Storage  │
│ Taxonomy/Ontology Store │ Optional LightRAG and Graph Store │
└─────────────────────────────┬────────────────────────────────┘
                              ▼
┌──────────────────────────────────────────────────────────────┐
│             Observability, Evaluation, and Audit             │
│ Langfuse │ OpenTelemetry │ Semantic QA │ Audit Events       │
└──────────────────────────────────────────────────────────────┘
```

## 7. Deployment Model

### 7.1 Initial model

Use a modular monolith plus workers:

- `api`: synchronous application API;
- `worker`: ingestion, semantic enrichment, indexing, deletion, and evaluation jobs;
- `web`: independent TypeScript frontend;
- `semantic-worker`: optional isolated high-cost classification, extraction, and entity-resolution worker;
- `lightrag`: optional isolated graph provider service;
- `postgres`: metadata, transactions, taxonomies, ontology registry, full-text search, and optional vectors;
- `object-store`: original and derived artifacts;
- `langfuse`: traces and evaluation records.

Modules communicate through typed application interfaces and persisted jobs. They may be separated into services later without changing domain contracts.

### 7.2 Compact profile

- PostgreSQL;
- pgvector;
- PostgreSQL full-text search;
- PostgreSQL JSONB or RDF-compatible tables for semantic registries;
- local filesystem or MinIO;
- local reranker;
- Ollama or vLLM;
- optional LightRAG with isolated storage.

### 7.3 Scale profile

- PostgreSQL for metadata and governance registries;
- Qdrant or another approved dense-vector store;
- OpenSearch for lexical retrieval;
- a dedicated RDF/graph store when formal reasoning or large semantic graphs justify it;
- MinIO or enterprise object storage;
- Redis for caching and coordination;
- isolated LightRAG deployment;
- Kubernetes and Helm.

## 8. Knowledge Governance and Semantic Interoperability Plane

### 8.1 Responsibilities

The plane governs:

- metadata schemas and field definitions;
- source-to-canonical metadata mappings;
- taxonomy concept schemes;
- ontology classes and properties;
- semantic constraints and validation shapes;
- entity identity and resolution;
- curated versus extracted knowledge;
- OKF bundles;
- semantic-profile activation and versioning;
- stewardship and approval workflows;
- multilingual terminology;
- deprecation and migration.

### 8.2 Semantic profile

Every workspace or collection is bound to an immutable, versioned semantic profile.

```python
@dataclass(frozen=True)
class SemanticProfile:
    id: UUID
    name: str
    version: str
    metadata_schema_versions: tuple[str, ...]
    taxonomy_scheme_versions: tuple[str, ...]
    ontology_version: str | None
    validation_profile_version: str | None
    entity_resolution_profile_version: str
    query_expansion_profile_version: str
    okf_profile_version: str | None
    status: Literal["draft", "approved", "deprecated"]
    activated_at: datetime | None
```

The active semantic profile is recorded in:

- document versions;
- enrichment jobs;
- graph builds;
- retrieval traces;
- generated answers;
- evaluation runs.

A semantic-profile update does not mutate historical records. It creates a new enrichment and index version.

### 8.3 Metadata registry

The metadata registry defines asset types, fields, validation, mappings, and stewardship.

```python
@dataclass(frozen=True)
class MetadataFieldDefinition:
    id: UUID
    namespace: str
    name: str
    labels: dict[str, str]
    description: dict[str, str]
    value_type: str
    required: bool
    multivalued: bool
    controlled_vocabulary_uri: str | None
    validation_rule: dict[str, Any]
    sensitivity: str | None
    retention_class: str | None
    owner_role: str | None
    schema_version: str
```

Metadata values must preserve:

- source value;
- normalized value;
- transformation rule;
- confidence;
- validation status;
- steward decision;
- effective and expiry dates where relevant.

### 8.4 Taxonomy registry

A taxonomy is a governed concept scheme, not a free-form tag list.

```python
@dataclass(frozen=True)
class TaxonomyConcept:
    id: UUID
    scheme_id: UUID
    uri: str
    preferred_labels: dict[str, str]
    alternative_labels: dict[str, tuple[str, ...]]
    hidden_labels: dict[str, tuple[str, ...]]
    broader_uris: tuple[str, ...]
    related_uris: tuple[str, ...]
    scope_notes: dict[str, str]
    external_mappings: tuple[str, ...]
    status: Literal["draft", "approved", "deprecated"]
    version: str
```

Taxonomies support:

- faceted navigation;
- document classification;
- multilingual synonyms;
- query expansion;
- retrieval routing;
- collection policies;
- entity-extraction constraints;
- graph entity resolution.

The interchange representation should be SKOS-compatible even if the initial persistence model uses relational tables.

### 8.5 Ontology registry

The ontology registry defines formally governed types and relationships.

```python
@dataclass(frozen=True)
class OntologyClass:
    uri: str
    preferred_labels: dict[str, str]
    parent_class_uris: tuple[str, ...]
    description: dict[str, str]
    identity_rules: tuple[str, ...]
    status: Literal["draft", "approved", "deprecated"]
    ontology_version: str
```

```python
@dataclass(frozen=True)
class OntologyProperty:
    uri: str
    property_type: Literal["object", "data"]
    domain_class_uris: tuple[str, ...]
    range_class_uris: tuple[str, ...]
    inverse_property_uri: str | None
    temporal: bool
    provenance_required: bool
    status: Literal["draft", "approved", "deprecated"]
    ontology_version: str
```

The registry also stores:

- constraints;
- cardinalities;
- allowed values;
- aliases;
- mappings to external vocabularies;
- deprecation notices;
- migration rules.

An RDF/OWL-compatible export should be supported. SHACL-compatible validation is recommended for formal graph constraints.

### 8.6 Entity identity and resolution

Entity resolution separates surface mentions from authoritative entities.

```text
Mention
→ normalization
→ candidate generation
→ taxonomy and ontology constraints
→ deterministic identifiers
→ similarity and rule scoring
→ confidence threshold
→ automatic match or steward review
```

```python
@dataclass(frozen=True)
class ResolvedEntity:
    id: UUID
    canonical_uri: str
    ontology_class_uri: str
    preferred_labels: dict[str, str]
    aliases: dict[str, tuple[str, ...]]
    authoritative_identifiers: dict[str, str]
    status: str
    semantic_profile_id: UUID
```

The system must distinguish:

- an entity;
- a textual mention;
- an unresolved candidate;
- an alias;
- a deprecated or merged entity.

### 8.7 Semantic assertions

LLM- or rule-extracted statements are candidate assertions, not authoritative facts.

```python
@dataclass(frozen=True)
class SemanticAssertion:
    id: UUID
    subject_entity_id: UUID
    property_uri: str
    object_entity_id: UUID | None
    literal_value: Any | None
    source_chunk_ids: tuple[UUID, ...]
    extraction_method: str
    extraction_model: str | None
    extraction_prompt_version: str | None
    confidence: float
    validation_status: Literal[
        "candidate",
        "valid",
        "invalid",
        "needs_review",
        "approved",
        "rejected",
    ]
    semantic_profile_id: UUID
    valid_from: datetime | None
    valid_to: datetime | None
```

Candidate assertions pass through:

```text
extraction
→ entity resolution
→ taxonomy alignment
→ ontology mapping
→ constraint validation
→ provenance validation
→ confidence policy
→ approval policy
→ governed graph publication
```

### 8.8 Curated and extracted knowledge

Keep two logically distinct knowledge classes:

```text
Curated knowledge
- approved definitions
- institutional rules
- canonical terminology
- reviewed methodologies
- approved metrics
- signed OKF bundles

Extracted knowledge
- machine-extracted entities
- candidate relations
- document-derived summaries
- probabilistic classifications
```

Extracted knowledge may support retrieval, but it must not silently become authoritative curated knowledge.

### 8.9 Stewardship workflow

Semantic changes move through:

```text
draft
→ automated validation
→ domain steward review
→ security/privacy review when needed
→ approval
→ publication
→ deprecation or supersession
```

Required roles:

- metadata steward;
- taxonomy curator;
- ontology owner;
- domain reviewer;
- security reviewer;
- platform publisher.

## 9. OKF Knowledge Bundles

### 9.1 Role

OKF is the portable authoring, review, version-control, and exchange format for curated knowledge. PostgreSQL and the governed registries remain the operational system of record.

Use OKF for:

- canonical definitions;
- approved business rules;
- institutional terminology;
- metric definitions;
- data-product descriptions;
- methodologies;
- model assumptions;
- runbooks;
- reviewed policy interpretation notes.

### 9.2 Processing model

```text
OKF bundle
→ parse Markdown and frontmatter
→ validate required profile
→ resolve taxonomy and ontology references
→ validate provenance and lifecycle fields
→ create review item
→ approve and publish
→ expose direct-read artifact
→ index content into lexical/vector systems
→ optionally publish governed graph assertions
```

### 9.3 Provider interface

```python
class KnowledgeBundleProvider(Protocol):
    async def import_bundle(
        self,
        bundle: KnowledgeBundle,
    ) -> BundleImportResult: ...

    async def export_bundle(
        self,
        scope: KnowledgeScope,
    ) -> KnowledgeBundle: ...

    async def validate_bundle(
        self,
        bundle: KnowledgeBundle,
    ) -> BundleValidationResult: ...
```

### 9.4 Git-backed curation

Recommended workflow:

```text
Author or agent proposes OKF change
→ pull request
→ schema and semantic validation
→ steward review
→ approval
→ signed release
→ import to RAG Foundry
→ index refresh
```

Round-trip import/export must preserve identifiers, provenance, status, taxonomy references, ontology references, and lifecycle metadata.

## 10. Canonical Domain Model

Framework-specific objects must not cross into the domain layer.

### 10.1 Source and knowledge lineage

```text
Workspace
  ├── SemanticProfile
  ├── MetadataSchema
  ├── TaxonomyScheme
  ├── Ontology
  └── Source
       └── SourceItem
            └── RawArtifact
                 └── Document
                      └── DocumentVersion
                           ├── MetadataValue
                           ├── DocumentElement
                           ├── TaxonomyAssignment
                           ├── EntityMention
                           ├── SemanticAssertion
                           └── Chunk
                                ├── LexicalIndexRecord
                                ├── DenseIndexRecord
                                └── GraphIndexRecord
```

### 10.2 Core records

```python
@dataclass(frozen=True)
class DocumentVersion:
    id: UUID
    document_id: UUID
    workspace_id: UUID
    source_revision: str
    title: str | None
    mime_type: str
    language: str | None
    checksum: str
    page_count: int | None
    acl_policy_id: UUID
    parser_name: str
    parser_version: str
    semantic_profile_id: UUID
    created_at: datetime
```

```python
@dataclass(frozen=True)
class DocumentElement:
    id: UUID
    document_version_id: UUID
    element_type: str
    sequence_number: int
    text: str | None
    markdown: str | None
    page_number: int | None
    bounding_box: tuple[float, float, float, float] | None
    parent_element_id: UUID | None
    metadata: dict[str, Any]
```

```python
@dataclass(frozen=True)
class Chunk:
    id: UUID
    document_version_id: UUID
    workspace_id: UUID
    text: str
    section_path: tuple[str, ...]
    page_numbers: tuple[int, ...]
    element_ids: tuple[UUID, ...]
    taxonomy_concept_uris: tuple[str, ...]
    resolved_entity_ids: tuple[UUID, ...]
    acl_policy_id: UUID
    checksum: str
    chunker_name: str
    chunker_version: str
    semantic_profile_id: UUID
```

## 11. Ingestion, Semantic Enrichment, and Publication

### 11.1 Processing flow

```text
Discover source changes
→ Fetch raw artifact
→ Scan and classify
→ Resolve source permissions
→ Select parser
→ Parse canonical elements
→ Score parse quality
→ Trigger OCR fallback when required
→ Extract and normalize metadata
→ Validate metadata schema
→ Classify with approved taxonomies
→ Extract entity mentions
→ Resolve entities
→ Extract candidate relations/assertions
→ Validate against ontology and constraints
→ Create canonical chunks
→ Publish versioned lexical and dense indexes
→ Publish approved semantic projection
→ Submit canonical chunks and approved guidance to graph indexing
→ Validate counts, provenance, and security boundaries
→ Atomically activate index and semantic versions
```

### 11.2 Connector contract

```python
class SourceConnector(Protocol):
    async def discover(
        self,
        cursor: SyncCursor | None,
    ) -> DiscoveryResult: ...

    async def fetch(
        self,
        item: SourceItem,
    ) -> RawArtifact: ...

    async def permissions(
        self,
        item: SourceItem,
    ) -> list[ACLGrant]: ...

    async def checkpoint(self) -> SyncCursor: ...
```

Required connector behavior:

- incremental synchronization;
- deletion detection;
- retries and resumability;
- source checksums;
- metadata mapping;
- permission synchronization;
- stable source identifiers.

### 11.3 Parser routing

```text
Native PDF ─────────► native parser or Docling
Scanned PDF ────────► PaddleOCR
Complex layout ─────► Docling
DOCX/PPTX/XLSX ─────► native structured parser
HTML/Markdown ──────► semantic parser
OKF Markdown ───────► OKF-aware parser and validator
Images ─────────────► OCR and layout analysis
```

### 11.4 Parse-quality indicators

- valid character ratio;
- page coverage;
- OCR confidence;
- heading continuity;
- table preservation;
- reading-order consistency;
- detected language consistency.

### 11.5 Semantic-quality indicators

- metadata completeness;
- metadata validation rate;
- taxonomy assignment confidence;
- unresolved entity rate;
- duplicate entity rate;
- assertion validation rate;
- provenance coverage;
- steward-review backlog;
- ontology constraint failure rate.

## 12. Indexing and Semantic Publication

All index and semantic publication writes are versioned.

```text
PublicationBuild
  id
  workspace_id
  publication_type
  provider
  model_or_configuration
  source_snapshot
  semantic_profile_id
  status
  activated_at
```

Publication types include:

- lexical index;
- dense index;
- taxonomy assignment projection;
- resolved entity projection;
- governed assertion graph;
- LightRAG graph;
- OKF bundle release.

A build moves through:

```text
created
→ building
→ validating
→ steward_review_required
→ ready
→ active

Any stage may transition to failed or rejected.
```

Only one compatible build per publication type and workspace is active. Rollback changes the active pointer; it does not reconstruct previous data.

## 13. Retrieval Architecture

### 13.1 Default path

The default path is governed hybrid retrieval:

```text
Question
→ language and intent detection
→ taxonomy and terminology expansion
→ ontology-aware entity linking
→ authorization and metadata filters
→ lexical search
→ dense search
→ reciprocal-rank fusion
→ deduplication
→ reranking
→ parent-context expansion
→ diversity selection
→ evidence sufficiency check
```

### 13.2 Semantic query expansion

Query expansion may use:

- preferred labels;
- alternative labels;
- hidden labels;
- approved acronyms;
- multilingual equivalents;
- narrower or broader concepts according to policy;
- ontology aliases;
- resolved entity identifiers.

Expansion must be traceable and bounded. It must not indiscriminately add all related terms.

### 13.3 Graph-enhanced path

Graph retrieval is optional:

```text
Question
→ route classification
→ taxonomy and ontology interpretation
→ authorized graph namespace selection
→ LightRAG local/global retrieval
→ graph evidence normalization
→ provenance resolution to canonical chunks
→ ontology and authorization revalidation
→ merge with conventional evidence
→ final reranking and context budgeting
```

### 13.4 Retrieval routes

```python
class RetrievalRoute(str, Enum):
    HYBRID = "hybrid"
    GRAPH_LOCAL = "graph_local"
    GRAPH_GLOBAL = "graph_global"
    HYBRID_PLUS_GRAPH = "hybrid_plus_graph"
    CURATED_KNOWLEDGE = "curated_knowledge"
```

Routing guidance:

- exact quotes, article numbers, dates, definitions, and tables: `HYBRID`;
- approved institutional definitions or rules: `CURATED_KNOWLEDGE`;
- entity relationships and local networks: `GRAPH_LOCAL`;
- corpus themes and broad cross-document synthesis: `GRAPH_GLOBAL`;
- mixed exact and relational questions: `HYBRID_PLUS_GRAPH`.

### 13.5 Provider interfaces

```python
class LexicalRetriever(Protocol):
    async def search(
        self,
        query: SearchQuery,
    ) -> list[RetrievedEvidence]: ...
```

```python
class DenseRetriever(Protocol):
    async def search(
        self,
        query: SearchQuery,
    ) -> list[RetrievedEvidence]: ...
```

```python
class TaxonomyService(Protocol):
    async def expand_query(
        self,
        query: str,
        semantic_profile_id: UUID,
    ) -> QueryExpansion: ...

    async def classify(
        self,
        content: str,
        semantic_profile_id: UUID,
    ) -> list[TaxonomyAssignment]: ...
```

```python
class OntologyService(Protocol):
    async def validate_assertions(
        self,
        assertions: list[SemanticAssertion],
        semantic_profile_id: UUID,
    ) -> AssertionValidationResult: ...

    async def resolve_schema(
        self,
        semantic_profile_id: UUID,
    ) -> ActiveOntologySchema: ...
```

```python
class Reranker(Protocol):
    async def rerank(
        self,
        query: str,
        evidence: list[RetrievedEvidence],
    ) -> list[RetrievedEvidence]: ...
```

```python
class GraphRetrievalProvider(Protocol):
    async def index_document(
        self,
        document: DocumentVersion,
        chunks: list[GraphIndexChunk],
        semantic_guidance: GraphSemanticGuidance,
    ) -> GraphIndexResult: ...

    async def delete_document(
        self,
        document_version_id: UUID,
    ) -> GraphDeleteResult: ...

    async def retrieve(
        self,
        query: GraphQuery,
    ) -> list[GraphEvidence]: ...

    async def rebuild(
        self,
        scope: GraphScope,
    ) -> GraphBuildResult: ...

    async def health(self) -> GraphProviderHealth: ...
```

### 13.6 Evidence normalization

```python
@dataclass(frozen=True)
class RetrievedEvidence:
    evidence_id: str
    source: Literal[
        "lexical",
        "dense",
        "graph",
        "curated_knowledge",
    ]
    chunk_ids: tuple[UUID, ...]
    document_version_ids: tuple[UUID, ...]
    content: str
    taxonomy_concept_uris: tuple[str, ...]
    entity_ids: tuple[UUID, ...]
    lexical_score: float | None
    dense_score: float | None
    graph_score: float | None
    reranker_score: float | None
    page_numbers: tuple[int, ...]
    bounding_boxes: tuple[tuple[float, float, float, float], ...]
    acl_policy_ids: tuple[UUID, ...]
    semantic_profile_id: UUID
```

## 14. LightRAG Integration Boundary

LightRAG is an optional evidence provider.

RAG Foundry remains authoritative for:

- identity and authorization;
- source synchronization;
- canonical parsing;
- metadata schemas;
- taxonomies and ontologies;
- entity identity;
- chunk identifiers;
- document, semantic-profile, and index lineage;
- final answer generation;
- citations and source viewing;
- OKF lifecycle;
- evaluation;
- audit logs.

LightRAG owns only:

- graph-oriented entity and relation extraction;
- graph construction;
- local and global graph retrieval;
- graph maintenance;
- graph-specific storage.

Use context-only retrieval. Do not expose LightRAG-generated final answers directly to users.

### 14.1 Ontology-guided extraction

LightRAG receives a constrained semantic guidance package:

```python
@dataclass(frozen=True)
class GraphSemanticGuidance:
    allowed_entity_types: tuple[str, ...]
    allowed_relation_types: tuple[str, ...]
    taxonomy_labels: dict[str, tuple[str, ...]]
    ontology_aliases: dict[str, tuple[str, ...]]
    prohibited_relations: tuple[str, ...]
    provenance_required: bool
    semantic_profile_id: UUID
```

LightRAG outputs remain candidate graph evidence until RAG Foundry validates provenance, ontology compatibility, and authorization.

### 14.2 Graph namespace strategy

The pilot must create graph namespaces by workspace, semantic profile, and compatible security domain.

```text
workspace-a/profile-v3/public
workspace-a/profile-v3/research
workspace-a/profile-v3/restricted
workspace-b/profile-v2/public
```

A graph summary built from restricted content must never be placed in a namespace visible to a less privileged user.

### 14.3 Graph provenance

Every entity, edge, relation description, and generated graph context must retain:

- source chunk IDs;
- document version IDs;
- workspace ID;
- security-domain identifier;
- semantic-profile ID;
- extraction model and prompt version;
- graph build ID;
- ontology class/property mappings;
- validation status.

Graph evidence without resolvable provenance is discarded.

### 14.4 nano-GraphRAG role

nano-GraphRAG is used for:

- provider-interface conformance;
- small deterministic fixtures;
- prompt experiments;
- ontology-guided extraction tests;
- graph algorithm research;
- LightRAG comparison;
- debugging multi-hop retrieval.

It is not part of the standard production deployment.

## 15. Generation and Citations

### 15.1 Generation flow

```text
Authorized evidence
→ curated-versus-extracted knowledge labeling
→ semantic context formatting
→ prompt policy
→ model gateway
→ structured answer
→ claim-evidence alignment
→ citation validation
→ semantic consistency check
→ sufficiency gate
→ final rendering
```

### 15.2 Output contract

```python
@dataclass(frozen=True)
class AnswerClaim:
    text: str
    evidence_ids: tuple[str, ...]
    concept_uris: tuple[str, ...]
    entity_ids: tuple[UUID, ...]
```

```python
@dataclass(frozen=True)
class GroundedAnswer:
    answer: str
    claims: tuple[AnswerClaim, ...]
    limitations: tuple[str, ...]
    sufficient_evidence: bool
    semantic_profile_id: UUID
```

Citation validation verifies:

- the evidence was supplied to the model;
- it remains authorized;
- the source location resolves;
- the cited passage supports the claim;
- ontology terms are used consistently;
- curated and extracted claims are not misrepresented;
- no unsupported factual claims remain.

If evidence is inadequate, return an explicit abstention rather than a plausible answer.

## 16. Model Gateway

All models are selected through server-controlled profiles.

Provider categories:

- chat generation;
- embeddings;
- reranking;
- metadata extraction;
- taxonomy classification;
- entity and relation extraction;
- entity resolution assistance;
- multimodal extraction;
- evaluation judges.

Example approved profiles:

- `fast-local`;
- `balanced-local`;
- `high-accuracy-private`;
- `approved-remote`;
- `semantic-enrichment-local`;
- `evaluation-judge`.

Users may choose approved answer profiles but may not submit arbitrary API keys or endpoints.

## 17. Authorization Model

Authorization applies before every evidence-producing or semantic-disclosure operation.

```text
Identity
→ workspace membership
→ collection authorization
→ source/document policy
→ metadata field visibility
→ taxonomy and ontology visibility
→ chunk filters
→ graph namespace selection
→ retrieval
→ reranking
→ generation
```

Required controls:

- OIDC authentication;
- workspace and collection roles;
- metadata field-level sensitivity;
- chunk-level ACL metadata;
- authorization filters in lexical and vector queries;
- graph namespace isolation;
- semantic registry visibility rules;
- authorization revalidation after evidence normalization;
- immutable audit events;
- deletion propagation;
- adversarial leakage tests.

Sensitive taxonomy concepts, entity identities, relationship labels, and community summaries are treated as potentially disclosive data.

## 18. Observability and Audit

Trace:

- user and workspace identifiers;
- retrieval route;
- active semantic profile;
- normalized and expanded query;
- taxonomy concepts and entity resolutions;
- authorization and metadata filters;
- candidate evidence and scores;
- reranker results;
- graph query mode;
- ontology validation decisions;
- prompt and model profile;
- citations;
- latency and token usage;
- abstention decision;
- user feedback;
- active publication versions.

Document text in traces must be configurable:

- full;
- redacted;
- metadata only;
- disabled.

Audit events are distinct from model traces and must cover:

- source configuration;
- membership changes;
- metadata schema publication;
- taxonomy and ontology changes;
- entity merge and split decisions;
- steward approvals;
- OKF imports and exports;
- document access and deletion;
- model-profile changes;
- index and semantic publication activation or rollback;
- graph rebuilds;
- administrative exports.

## 19. Evaluation

### 19.1 Metadata metrics

- required-field completeness;
- normalization accuracy;
- source-mapping success rate;
- invalid-value rate;
- sensitivity-label accuracy;
- steward override rate.

### 19.2 Taxonomy metrics

- classification precision and recall;
- concept coverage;
- synonym expansion precision;
- multilingual label coverage;
- orphan concept rate;
- deprecated concept usage.

### 19.3 Ontology and entity metrics

- entity-resolution precision;
- unresolved entity rate;
- duplicate entity rate;
- relation extraction precision;
- ontology constraint pass rate;
- assertion provenance coverage;
- invalid assertion rejection rate;
- steward-review agreement.

### 19.4 Retrieval metrics

- Recall@k;
- MRR;
- nDCG;
- context precision;
- source diversity;
- exact-term success rate;
- taxonomy-expansion uplift;
- authorization leakage rate.

### 19.5 Generation and citation metrics

- faithfulness;
- unsupported-claim rate;
- citation precision;
- citation recall;
- answer completeness;
- abstention accuracy;
- terminology consistency;
- curated-versus-extracted knowledge labeling accuracy.

### 19.6 Graph metrics

- graph entity precision;
- graph relation precision;
- graph provenance coverage;
- multi-hop accuracy;
- graph evidence citation precision;
- deletion completeness;
- graph ACL leakage;
- graph indexing cost;
- graph query latency.

### 19.7 OKF metrics

- schema validation success;
- import/export round-trip fidelity;
- unresolved semantic reference rate;
- provenance completeness;
- bundle-signature or release verification success;
- stale or superseded bundle usage.

### 19.8 Operational metrics

- ingestion throughput;
- parser failure rate;
- enrichment throughput;
- steward-review backlog;
- index freshness;
- p50 and p95 latency;
- job retry rate;
- model cost;
- trace completeness.

### 19.9 Release gates

A release is blocked when:

- any ACL or semantic-disclosure leakage test fails;
- critical golden cases fail;
- citation precision regresses beyond tolerance;
- unsupported claims exceed threshold;
- deletion tests fail;
- metadata completeness falls below the approved threshold;
- taxonomy or ontology migrations leave unresolved active references;
- entity-resolution precision falls below the approved threshold;
- graph or semantic assertion provenance falls below target;
- OKF round-trip tests fail;
- p95 latency exceeds the approved budget without an explicit waiver.

## 20. Repository Layout

```text
rag-foundry/
├── apps/
│   ├── api/
│   ├── web/
│   ├── worker/
│   ├── semantic-worker/
│   └── developer-ui/
├── packages/
│   ├── domain/
│   ├── application/
│   ├── auth/
│   ├── connectors/
│   ├── parsing/
│   ├── chunking/
│   ├── metadata/
│   │   ├── registry/
│   │   ├── schemas/
│   │   ├── mappings/
│   │   └── validation/
│   ├── taxonomy/
│   │   ├── models/
│   │   ├── classification/
│   │   ├── query-expansion/
│   │   └── lifecycle/
│   ├── ontology/
│   │   ├── registry/
│   │   ├── models/
│   │   ├── resolution/
│   │   ├── validation/
│   │   └── migrations/
│   ├── semantic-enrichment/
│   │   ├── metadata-extraction/
│   │   ├── classification/
│   │   ├── entity-extraction/
│   │   ├── relation-extraction/
│   │   └── entity-resolution/
│   ├── knowledge-bundles/
│   │   ├── domain/
│   │   ├── importers/
│   │   ├── exporters/
│   │   └── validation/
│   ├── stewardship/
│   ├── indexing/
│   ├── retrieval/
│   ├── generation/
│   ├── citations/
│   ├── evaluation/
│   ├── observability/
│   ├── model-gateway/
│   └── persistence/
├── providers/
│   ├── connector-filesystem/
│   ├── connector-sharepoint/
│   ├── connector-confluence/
│   ├── parser-docling/
│   ├── parser-paddleocr/
│   ├── taxonomy-skos/
│   ├── ontology-rdf/
│   ├── ontology-owl/
│   ├── validation-shacl/
│   ├── knowledge-okf/
│   ├── vector-pgvector/
│   ├── vector-qdrant/
│   ├── lexical-postgres/
│   ├── lexical-opensearch/
│   ├── graph-lightrag/
│   ├── graph-nano/
│   ├── models-litellm/
│   └── tracing-langfuse/
├── migrations/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── security/
│   ├── semantic/
│   ├── evaluation/
│   └── fixtures/
├── knowledge/
│   ├── metadata-schemas/
│   ├── taxonomies/
│   ├── ontologies/
│   ├── validation-shapes/
│   └── okf/
├── evaluation/
│   ├── datasets/
│   ├── baselines/
│   └── experiments/
├── deployments/
│   ├── docker-compose/
│   ├── helm/
│   └── airgap/
└── docs/
    ├── architecture/
    ├── adr/
    ├── operations/
    ├── semantics/
    └── security/
```

## 21. Revised Implementation Roadmap

Planning assumption: one technical lead, two backend engineers, one frontend engineer, one shared knowledge engineer or data steward, and shared platform/security support.

### Phase 0 — Foundation and architecture decisions  
**Duration:** 1 week

Deliverables:

- repository scaffold;
- licensing and attribution policy;
- architecture decision records;
- coding standards and CI;
- dependency and container scanning;
- local Docker Compose environment;
- canonical domain model draft;
- semantic-governance charter.

Exit criterion:

- core modules compile without importing Kotaemon, LlamaIndex, LightRAG, or nano-GraphRAG domain types.

### Phase 1 — Metadata and semantic-profile foundation  
**Duration:** 2 weeks

Deliverables:

- semantic profile model;
- metadata registry;
- asset types and field definitions;
- source-to-canonical mappings;
- validation and quality reports;
- stewardship ownership fields;
- PostgreSQL schema and repositories.

Exit criteria:

- metadata schemas are versioned;
- invalid records are quarantined or flagged;
- every document version records its semantic profile;
- metadata changes are auditable.

### Phase 2 — Source ingestion, parsing, and canonical documents  
**Duration:** 2 weeks

Deliverables:

- file upload and filesystem connectors;
- source synchronization jobs;
- object storage;
- parser interface and router;
- native PDF parser;
- Docling and OCR providers;
- canonical document elements;
- parsing diagnostics.

Exit criteria:

- native and scanned PDF fixtures pass;
- every element resolves to a source location;
- source metadata and permissions are preserved.

### Phase 3 — Taxonomy MVP and semantic classification  
**Duration:** 2 weeks

Deliverables:

- concept schemes;
- broader, narrower, and related relationships;
- multilingual labels and synonyms;
- taxonomy import/export;
- document and chunk classification;
- taxonomy browser;
- query expansion service.

Exit criteria:

- taxonomy assignments are versioned and explainable;
- deprecated concepts are detected;
- query expansion improves a designated terminology benchmark without unacceptable precision loss.

### Phase 4 — Ontology, entity identity, and semantic validation  
**Duration:** 2–3 weeks

Deliverables:

- ontology registry;
- classes and properties;
- ontology import/export;
- entity mention model;
- entity resolution;
- candidate semantic assertions;
- constraint validation;
- curator review queue.

Exit criteria:

- duplicate entities are measurable and controlled;
- assertions cannot be published without provenance;
- invalid domain/range relationships are rejected;
- entity merges and splits are auditable.

### Phase 5 — Chunking, indexing, and governed hybrid retrieval  
**Duration:** 2 weeks

Deliverables:

- structural chunker;
- page and bounding-box metadata;
- embedding provider;
- PostgreSQL/pgvector;
- PostgreSQL full-text search;
- lexical and dense retrieval;
- rank fusion;
- reranking;
- taxonomy and ontology query expansion;
- ACL-filtered search.

Exit criteria:

- unauthorized chunks never enter the candidate set;
- hybrid retrieval has a reproducible baseline;
- semantic expansion is traceable;
- exact-term retrieval does not regress.

### Phase 6 — Grounded generation and citations  
**Duration:** 2 weeks

Deliverables:

- model gateway;
- structured answer schema;
- evidence formatter;
- citation alignment;
- citation validation;
- terminology consistency checks;
- sufficiency and abstention rules;
- standard, curated-knowledge, and decomposed QA modes.

Exit criteria:

- every supported claim links to supplied evidence;
- invalid citation identifiers are rejected;
- low-evidence questions trigger warning or abstention;
- curated and extracted knowledge are visibly distinguished.

### Phase 7 — Product interface and stewardship tools  
**Duration:** 2–3 weeks

Deliverables:

- authentication;
- chat and collection interface;
- PDF citation viewer;
- metadata and taxonomy browsing;
- ontology and entity inspection;
- curator review queue;
- OKF bundle review;
- feedback controls;
- administrative model profiles.

Exit criteria:

- users query only authorized collections;
- selecting a citation opens the correct page and region;
- stewards can review semantic changes with provenance.

### Phase 8 — Evaluation and observability  
**Duration:** 2 weeks

Deliverables:

- Langfuse;
- OpenTelemetry;
- audit events;
- golden datasets;
- retrieval and generation metrics;
- semantic quality metrics;
- CI evaluation gates;
- online feedback datasets.

Exit criteria:

- every answer records the active semantic profile;
- baseline and candidate configurations can be compared;
- semantic and security regressions block releases.

### Phase 9 — Graph retrieval spike  
**Duration:** 1–2 weeks

Deliverables:

- `GraphRetrievalProvider`;
- nano-GraphRAG conformance adapter;
- LightRAG proof-of-concept adapter;
- ontology-guided graph extraction;
- canonical chunk-to-graph mapping;
- context-only graph retrieval;
- graph provenance schema;
- multi-hop evaluation dataset.

Decision gate:

- graph retrieval materially improves designated analytical questions;
- every graph result resolves to source chunks;
- deletion is reliable;
- ontology and ACL boundaries are preserved.

### Phase 10 — LightRAG production adapter and secure graph partitioning  
**Duration:** 2–3 weeks

Deliverables:

- isolated LightRAG service;
- semantic-guidance package;
- graph index jobs;
- local/global retrieval;
- graph namespaces by security domain and semantic profile;
- document deletion;
- graph version tracking;
- retry and rebuild workflows;
- trace correlation;
- graph leakage tests.

Exit criteria:

- graph ACL leakage is zero;
- graph assertion provenance meets target;
- deleted facts disappear;
- graph builds are reproducible;
- graph retrieval passes the multi-hop decision gate.

### Phase 11 — OKF import, export, and Git curation  
**Duration:** 2 weeks

Deliverables:

- OKF importer and exporter;
- bundle validation;
- semantic-reference resolution;
- Git-based review workflow;
- direct-read endpoint;
- indexing and governed-graph publication;
- round-trip conformance suite.

Exit criteria:

- approved bundles round-trip without loss of identifiers or provenance;
- unresolved concepts or ontology references block publication;
- superseded bundles are not served as current knowledge.

### Phase 12 — Enterprise source integration and pilot hardening  
**Duration:** 3 weeks

Deliverables:

- enterprise OIDC;
- SharePoint connector;
- source permission synchronization;
- malware scanning;
- retention and deletion jobs;
- secrets-manager integration;
- backup and restore;
- load and resilience testing;
- air-gapped deployment;
- operating and semantic-governance runbooks.

Exit criteria:

- source permission changes propagate;
- deleted documents disappear from all active projections;
- ACL and semantic-disclosure penetration tests pass;
- offline deployment makes no unintended external calls.

Estimated delivery under the stated staffing assumption:

- **Core MVP without production graph or OKF:** 12–15 weeks.
- **Governed institutional pilot including semantics, LightRAG, and OKF:** 20–24 weeks.

## 22. Initial Pull Request Sequence

1. `chore: scaffold monorepo and development environment`
2. `feat(domain): add canonical source document and semantic profile models`
3. `feat(metadata): add registry schemas mappings and validation`
4. `feat(persistence): add PostgreSQL schema and repositories`
5. `feat(connectors): add local upload and filesystem connectors`
6. `feat(workflows): add versioned ingestion pipeline`
7. `feat(parsing): add parser router and native PDF parser`
8. `feat(parsing): add Docling and OCR providers`
9. `feat(taxonomy): add concept schemes and multilingual labels`
10. `feat(taxonomy): add classification and query expansion`
11. `feat(ontology): add class property and constraint registry`
12. `feat(semantics): add entity mentions and entity resolution`
13. `feat(semantics): add assertion extraction and validation`
14. `feat(chunking): add structural and page-aware chunking`
15. `feat(indexing): add pgvector and full-text indexing`
16. `feat(retrieval): add hybrid retrieval and rank fusion`
17. `feat(retrieval): add semantic expansion reranking and traces`
18. `feat(generation): add model gateway and grounded output`
19. `feat(citations): add citation and terminology validation`
20. `feat(api): add chat source catalog and semantic endpoints`
21. `feat(web): add chat citation viewer and taxonomy browser`
22. `feat(stewardship): add metadata entity and assertion review`
23. `feat(auth): add OIDC workspaces and ACL enforcement`
24. `feat(observability): add Langfuse OpenTelemetry and audit`
25. `feat(evaluation): add semantic datasets metrics and CI gates`
26. `feat(graph): add nano GraphRAG conformance adapter`
27. `feat(graph): add isolated LightRAG provider`
28. `feat(graph): add secure namespaces and evidence fusion`
29. `feat(okf): add bundle import export and validation`
30. `feat(okf): add Git curation and direct-read publishing`
31. `feat(connectors): add SharePoint synchronization`
32. `chore(deployment): add pilot and air-gapped profiles`

## 23. Acceptance Criteria for the First Governed Pilot

### Security and lifecycle

- ACL leakage: zero.
- Semantic-disclosure leakage: zero.
- Deletion propagation: 100 percent across active indexes, graphs, and curated projections.
- Critical golden-case pass rate: 100 percent.

### Metadata and semantics

- Required metadata completeness: at least 0.95.
- Metadata validation success: at least 0.97.
- Taxonomy classification F1 on approved benchmark: at least 0.85.
- Entity-resolution precision: at least 0.95.
- Duplicate active entity rate: no more than 0.02.
- Ontology constraint pass rate for published assertions: 1.00.
- Semantic assertion provenance coverage: at least 0.99.

### Retrieval and answers

- Retrieval Recall@10: at least 0.85.
- Citation precision: at least 0.95.
- Citation recall: at least 0.90.
- Unsupported-claim rate: no more than 0.03.
- Correct abstention on unanswerable cases: at least 0.85.
- Successful parsing: at least 0.95.
- Trace completeness: at least 0.99.

### Graph and OKF

- Graph provenance coverage: at least 0.99.
- Graph-enhanced retrieval must materially improve the designated multi-hop benchmark before becoming enabled for eligible routes.
- OKF round-trip fidelity for required fields and identifiers: 1.00.
- Unresolved references in published OKF bundles: zero.
- Superseded OKF bundle served as current: zero.

## 24. Required Architecture Decision Records

Create these ADRs before their corresponding implementation begins:

1. Modular monolith and worker topology.
2. Canonical document, evidence, and semantic models.
3. Index and semantic publication versioning.
4. Compact and scale storage profiles.
5. Authorization-before-retrieval and semantic-disclosure policy.
6. Model gateway and approved profiles.
7. Frontend independence from RAG frameworks.
8. Parser routing and OCR fallback.
9. Metadata registry and schema governance.
10. Taxonomy representation and SKOS interoperability.
11. Ontology representation, constraints, and versioning.
12. Entity identity, merge, split, and resolution strategy.
13. Curated versus extracted knowledge.
14. Semantic assertion validation and approval.
15. Hybrid retrieval and rank-fusion policy.
16. Taxonomy and ontology query expansion.
17. LightRAG provider boundary.
18. Security-domain and semantic-profile graph partitioning.
19. Graph provenance and deletion semantics.
20. Citation validation, terminology consistency, and abstention.
21. OKF import, export, Git curation, and publication.
22. Stewardship and approval workflow.
23. Observability redaction policy.
24. Semantic migration and backward compatibility.
25. Third-party code and license policy.

## 25. Architectural Invariants

The following are non-negotiable:

1. A user must never retrieve or infer content outside their authorization.
2. Sensitive metadata, taxonomy labels, entity identities, and graph summaries are subject to authorization.
3. Every answer claim must resolve to authorized evidence or be removed.
4. Every citation must resolve to an immutable document version and source location.
5. Every graph result must resolve to canonical chunks.
6. Every published semantic assertion must have provenance and pass the active validation profile.
7. Extracted knowledge must not silently become authoritative curated knowledge.
8. Documents are parsed once per parser version, not independently by retrieval providers.
9. No framework-specific document type appears in the domain package.
10. All metadata schemas, taxonomies, ontologies, indexes, graphs, and OKF releases are versioned.
11. Historical answers retain the semantic profile under which they were generated.
12. Deleting a source document removes it from every active retrieval and semantic projection.
13. Ontology or taxonomy migrations cannot leave unresolved active references.
14. Local-only profiles must not produce unintended external network calls.
15. Advanced reasoning and tools are disabled unless explicitly approved, scoped, and evaluated.
16. Language models may propose semantic changes but cannot autonomously approve or publish governed knowledge.
17. OKF import/export must preserve required identifiers, provenance, and lifecycle status.
18. Rollback must be possible for indexes, graph builds, semantic profiles, and curated knowledge releases.
