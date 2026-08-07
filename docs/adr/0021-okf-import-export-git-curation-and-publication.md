# ADR-0021: OKF import, export, Git curation, and publication

- **Status:** Accepted
- **Date:** 2026-08-07

## Context

Knowledge assets should be portable, diffable, and curatable without database
lock-in. A file format alone, however, is not suitable as the transactional store
for concurrent workflow, authorization, and publication state.

## Decision

Use Open Knowledge Format (OKF) as a portable import/export and Git-curation
boundary, not as RAG Foundry's transactional system of record.

OKF bundles can carry governed metadata schemas, taxonomies, ontologies, mappings,
and related semantic artifacts with stable identifiers and versions. Import first
validates schema, references, constraints, provenance, and compatibility into a
staging change set. Publication occurs only through the registry/stewardship
workflow. Export produces deterministic bundles suitable for review and Git diff.

PostgreSQL remains the canonical transactional registry; raw/canonical document
artifacts remain in object storage.

## Consequences

Teams gain portable, reviewable knowledge packages without weakening runtime
consistency. Import/export must maintain careful mapping between OKF identities
and canonical registry identities.

## Verification

- Export -> import -> export passes a semantic round-trip conformance test.
- Import cannot bypass approval/publication controls.
- Canonical operation continues when no Git or OKF working tree is mounted.
