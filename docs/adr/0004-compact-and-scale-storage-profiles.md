# ADR-0004: Compact and scale storage profiles

- **Status:** Proposed
- **Date:** 2026-08-07

## Context

Air-gapped teams need a small operational footprint, while larger deployments
may need specialized search infrastructure. Making specialized systems mandatory
would undermine local deployment; coding directly to the compact stack would
block later scale-out.

## Decision

Support two behaviorally equivalent storage profiles behind repository/index
interfaces.

- **Compact:** PostgreSQL for canonical metadata/governance, PostgreSQL full-text
  search for lexical retrieval, pgvector for dense retrieval, and MinIO or
  compatible S3 storage for raw/canonical artifacts.
- **Scale:** PostgreSQL remains the canonical governance store while Qdrant may
  provide dense retrieval and OpenSearch may provide lexical retrieval. Object
  artifacts remain in S3-compatible storage.

Redis may be used for cache/job infrastructure but is not a canonical store.
Switching profiles must not change authorization, provenance, citation, or
semantic-governance behavior.

## Consequences

Small deployments remain practical and large installations gain specialized
scaling options. Provider conformance tests are required to prevent semantic
drift between profiles.

## Verification

- The same golden retrieval cases pass on compact and scale profiles within
  documented ranking tolerances.
- Canonical governance records never depend on Qdrant, OpenSearch, or Redis for
  durability.
