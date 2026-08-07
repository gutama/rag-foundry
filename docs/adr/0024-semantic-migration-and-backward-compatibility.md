# ADR-0024: Semantic migration and backward compatibility

- **Status:** Accepted
- **Date:** 2026-08-07

## Context

Metadata, taxonomy, ontology, and identity models evolve. In-place semantic edits
can change the meaning of old indexes, saved queries, graph edges, and cited
answers without leaving evidence of what changed.

## Decision

Semantic evolution is versioned and migration-driven, never an in-place rewrite
of a published semantic profile.

Each change class declares compatibility and its required action: no-op for
consumers, translation/mapping, revalidation, re-extraction, or reindex/rebuild.
Deprecations retain stable aliases/mappings for a documented compatibility window.
Breaking changes create a new semantic profile/publication and can run beside the
old one until migration gates pass. Rollback restores a previous publication; it
does not reverse-mutate history.

Migration tooling records source/target versions and deterministic results.

## Consequences

Deployments may temporarily maintain parallel indexes and mappings, increasing
storage/operational cost. In return, historical answers and consumers retain
defined semantics throughout change.

## Verification

- Breaking semantic changes cannot publish without a declared migration plan.
- Old publication IDs remain resolvable during their retention window.
- Migration tests cover forward conversion, rollback-by-publication, and required
  reindex/revalidation effects.
