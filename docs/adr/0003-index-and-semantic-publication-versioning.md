# ADR-0003: Index and semantic publication versioning

- **Status:** Proposed
- **Date:** 2026-08-07

## Context

Changing chunks, embeddings, taxonomies, ontologies, entity mappings, or graph
extraction can change what an unchanged query retrieves. In-place mutation would
make answers impossible to reproduce or audit.

## Decision

Treat published document revisions, semantic profiles, and index publications as
immutable versioned artifacts.

- A semantic profile pins the applicable metadata schema, taxonomy, ontology,
  mapping, normalization, and semantic-expansion versions.
- An index publication pins its source document revisions, canonical processing
  profile, semantic profile, embedding/index configuration, and graph build when
  applicable.
- Builds occur in staging and become visible through an atomic publication
  switch; published artifacts are never edited in place.
- Queries and answer traces record the publication IDs that produced evidence.

## Consequences

Rollback, comparison, reproducibility, and audits become first-class operations.
Storage use grows because multiple publications may coexist, so retention and
garbage-collection policies are required.

## Verification

- A recorded answer can identify the exact document, semantic, and index
  versions used.
- Failed publication cannot leave a partially updated visible index.
- Replacing a semantic version creates a new publication rather than mutating an
  existing one.
