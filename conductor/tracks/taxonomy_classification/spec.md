# Track Specification: SKOS Taxonomy MVP, Classification, and Query Expansion

## Overview
- **Track ID:** `taxonomy_classification`
- **Type:** Feature
- **Architectural Reference:** Phase 3 of Architecture Roadmap, ADR-0010 (SKOS Taxonomy), ADR-0016 (Query Expansion)

This track implements the SKOS Taxonomy management plane, automated document/chunk semantic classification, SKOS concept scheme import/export (Turtle, JSON-LD, CSV), SKOS browser service, and a taxonomy-driven query expansion service for hybrid retrieval.

## Functional Requirements
1. **SKOS Scheme & Concept Management:**
   - Extend `TaxonomyService` to support SKOS concept schemes, concept creation, concept updates, and concept deprecation.
   - Maintain hierarchical relationships (`skos:broader`, `skos:narrower`, `skos:related`) and multilingual labels (`skos:prefLabel`, `skos:altLabel`, `skos:hiddenLabel`).
2. **Taxonomy Import & Export:**
   - Importers and exporters for RDF/Turtle (`.ttl`), SKOS JSON-LD, and CSV concept dictionaries.
3. **Semantic Classification Service:**
   - Automated classifier analyzing document and chunk text against active SKOS concept schemes.
   - Candidate entity resolution using surface label matching + fuzzy distance + zero-shot classification.
   - Attach assigned concept URIs and `taxonomy_version_id` to document/chunk metadata.
4. **SKOS Browser Service:**
   - Query concept hierarchies, root concepts, child concepts, and concept metadata by URI or scheme ID.
5. **Taxonomy Query Expansion Service (ADR-0016):**
   - Given an incoming search query string, extract matched SKOS concepts.
   - Expand query terms using synonyms (`altLabel`), broader concepts, and narrower concepts with decay weights.
   - Generate expanded lexical and vector search parameters for hybrid retrieval.

## Non-Functional Requirements
- **Performance:** Query expansion execution time < 15ms per search query.
- **Style Compliance:** Strict adherence to Google Python Style Guide (max line length ≤ 80 characters).
- **Test Coverage:** Minimum 80% code coverage across `src/rag_foundry/taxonomy/` and expansion packages.

## Acceptance Criteria
- [ ] SKOS concept schemes can be created, updated, and exported/imported via Turtle, JSON-LD, and CSV.
- [ ] Document/chunk classification accurately maps surface text mentions to SKOS concept URIs.
- [ ] Deprecated concepts emit governance audit events when referenced.
- [ ] Query expansion service generates weighted expanded search queries preserving precision.
- [ ] Test suite passes with ≥80% code coverage.

## Out of Scope
- Full OWL Ontology class hierarchy validation (reserved for Phase 4 track).
- LightRAG graph integration (reserved for Phase 9 track).
