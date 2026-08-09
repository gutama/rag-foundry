# Implementation Plan: SKOS Taxonomy MVP, Classification, and Query Expansion

## Phase 1: SKOS Concept Management & Multi-Format Serialization (ADR-0010)
- [x] Task: Implement SKOS Concept Scheme Models and Importer/Exporter (dc4ba1c)
  - [x] Write failing unit tests for SKOS scheme registration, concept relationships, and deprecation governance
  - [x] Write failing unit tests for RDF/Turtle (.ttl), JSON-LD, and CSV concept scheme importers & exporters
  - [x] Implement `SKOSConceptScheme` schema, deprecation check, and audit event logger
  - [x] Implement `SKOSImporter` and `SKOSExporter` supporting Turtle, JSON-LD, and CSV
- [x] Task: Phase Verification & Checkpoint (Refer to workflow.md)

## Phase 2: SKOS Browser Service & Concept Hierarchy Navigation
- [x] Task: Implement SKOS Browser Service (602da92)
  - [x] Write failing unit tests for `TaxonomyBrowserService` (root concepts, broader/narrower tree traversals, search by label)
  - [x] Implement `TaxonomyBrowserService` and URI lookups
- [x] Task: Phase Verification & Checkpoint (Refer to workflow.md)

## Phase 3: Semantic Classification Engine & Metadata Tagging
- [x] Task: Implement Document & Chunk Semantic Classifier (a23346d)
  - [x] Write failing unit tests for `SemanticClassifier` (surface label matching + fuzzy distance + zero-shot classification)
  - [x] Write failing unit tests for `taxonomy_version_id` tagging and audit log emission on deprecated concepts
  - [x] Implement `SemanticClassifier` service and document/chunk metadata tagging
- [x] Task: Phase Verification & Checkpoint (Refer to workflow.md)

## Phase 4: Taxonomy Query Expansion Service & Pipeline Integration (ADR-0016)
- [x] Task: Implement SKOS Query Expansion Service (059d386)
  - [x] Write failing unit tests for `TaxonomyQueryExpander` (prefLabel, altLabel synonyms, broader & narrower terms with weight decay)
  - [x] Write failing unit tests for `TaxonomyQueryExpander` service (sub-15ms execution)
  - [x] Verify test suite passes with ≥80% code coverage across taxonomy packages
- [x] Task: Phase Verification & Checkpoint (Refer to workflow.md)
