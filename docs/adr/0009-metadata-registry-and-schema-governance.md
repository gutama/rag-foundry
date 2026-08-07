# ADR-0009: Metadata registry and schema governance

- **Status:** Accepted
- **Date:** 2026-08-07

## Context

Free-form metadata becomes inconsistent across ingestion pipelines and cannot
reliably support filtering, authorization, retention, or semantic expansion.

## Decision

Make metadata schemas first-class, versioned governance artifacts managed by a
Metadata Registry.

Schemas have stable identities and immutable published versions, machine-readable
validation (JSON Schema/Pydantic v2), ownership/stewardship, field semantics, and
compatibility metadata. Ingestion validates required and typed fields before a
document revision is eligible for publication. Invalid values are rejected or
quarantined according to policy; they are never silently coerced into a published
record.

Schema evolution follows ADR-0024. Retrieval filters refer to registered field
identities rather than uncontrolled display labels.

## Consequences

Ingestion becomes stricter and schema changes require governance work, but
metadata gains the consistency needed for secure institutional retrieval.

## Verification

- Published documents identify the exact metadata schema version used.
- Invalid required metadata cannot reach a published index.
- Field additions/deprecations follow explicit compatibility rules and audit
  history.
