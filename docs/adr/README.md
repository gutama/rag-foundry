# RAG Foundry Architecture Decision Records

These Architecture Decision Records (ADRs) capture the decisions required by the
RAG Foundry Architecture v0.2 (2026-08-07). They turn the proposed architecture
into reviewable contracts for implementation.

## Status convention

- **Proposed**: the decision is the current design direction but may still be
  refined before the dependent implementation is released.
- **Accepted**: the decision is approved and implementations must conform to it.
- **Superseded**: a newer ADR replaces the decision; the replacement must be
  linked from the older record.
- **Deprecated**: the decision is retained for history but must not guide new
  work.

Changing an accepted decision requires a new ADR. Do not silently rewrite the
reasoning of an accepted record.

## Decision index

| ADR | Decision | Status |
| --- | --- | --- |
| [0001](./0001-modular-monolith-and-worker-topology.md) | Modular monolith and worker topology | Accepted |
| [0002](./0002-canonical-document-evidence-and-semantic-models.md) | Canonical document, evidence, and semantic models | Accepted |
| [0003](./0003-index-and-semantic-publication-versioning.md) | Index and semantic publication versioning | Accepted |
| [0004](./0004-compact-and-scale-storage-profiles.md) | Compact and scale storage profiles | Accepted |
| [0005](./0005-authorization-before-retrieval-and-semantic-disclosure.md) | Authorization-before-retrieval and semantic-disclosure policy | Accepted |
| [0006](./0006-model-gateway-and-approved-profiles.md) | Model gateway and approved profiles | Accepted |
| [0007](./0007-frontend-independence-from-rag-frameworks.md) | Frontend independence from RAG frameworks | Accepted |
| [0008](./0008-parser-routing-and-ocr-fallback.md) | Parser routing and OCR fallback | Accepted |
| [0009](./0009-metadata-registry-and-schema-governance.md) | Metadata registry and schema governance | Accepted |
| [0010](./0010-taxonomy-representation-and-skos-interoperability.md) | Taxonomy representation and SKOS interoperability | Accepted |
| [0011](./0011-ontology-representation-constraints-and-versioning.md) | Ontology representation, constraints, and versioning | Accepted |
| [0012](./0012-entity-identity-merge-split-and-resolution.md) | Entity identity, merge, split, and resolution strategy | Accepted |
| [0013](./0013-curated-versus-extracted-knowledge.md) | Curated versus extracted knowledge | Accepted |
| [0014](./0014-semantic-assertion-validation-and-approval.md) | Semantic assertion validation and approval | Accepted |
| [0015](./0015-hybrid-retrieval-and-rank-fusion-policy.md) | Hybrid retrieval and rank-fusion policy | Accepted |
| [0016](./0016-taxonomy-and-ontology-query-expansion.md) | Taxonomy and ontology query expansion | Accepted |
| [0017](./0017-lightrag-provider-boundary.md) | LightRAG provider boundary | Accepted |
| [0018](./0018-security-domain-and-semantic-profile-graph-partitioning.md) | Security-domain and semantic-profile graph partitioning | Accepted |
| [0019](./0019-graph-provenance-and-deletion-semantics.md) | Graph provenance and deletion semantics | Accepted |
| [0020](./0020-citation-validation-terminology-consistency-and-abstention.md) | Citation validation, terminology consistency, and abstention | Accepted |
| [0021](./0021-okf-import-export-git-curation-and-publication.md) | OKF import, export, Git curation, and publication | Accepted |
| [0022](./0022-stewardship-and-approval-workflow.md) | Stewardship and approval workflow | Accepted |
| [0023](./0023-observability-redaction-policy.md) | Observability redaction policy | Accepted |
| [0024](./0024-semantic-migration-and-backward-compatibility.md) | Semantic migration and backward compatibility | Accepted |
| [0025](./0025-third-party-code-and-license-policy.md) | Third-party code and license policy | Accepted |
| [0026](./0026-ragas-and-deepeval-evaluation-framework-adoption.md) | Ragas and DeepEval evaluation framework adoption | Accepted |

## Cross-cutting invariants

The records preserve five architecture-wide rules:

1. RAG Foundry owns canonical data, authorization, generation, citations, and
   evaluation; retrieval frameworks are providers behind interfaces.
2. Authorization occurs before metadata disclosure, retrieval, reranking, graph
   traversal, and generation.
3. Extracted knowledge remains evidence-backed candidate knowledge until it
   passes governance; it never silently becomes curated truth.
4. Published document, semantic-profile, and index lineage is immutable and
   reproducible.
5. OKF is the portable authoring/exchange format, not the transactional system
   of record.
