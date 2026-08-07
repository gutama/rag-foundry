# ADR-0019: Graph provenance and deletion semantics

- **Status:** Accepted
- **Date:** 2026-08-07

## Context

Extracted graph edges can outlive the source text that justified them. Without
source-linked provenance and deterministic deletion propagation, corrected or
deleted documents can leave ghost knowledge in graph retrieval.

## Decision

Every graph node/edge assertion derived from content must reference canonical
semantic assertions/evidence. Graph materialization is a rebuildable projection,
not the source of truth.

Document deletion, revision withdrawal, assertion rejection/supersession, or
security/profile retirement emits projection updates that remove or tombstone
dependent graph material. Shared entities/edges remain only while at least one
eligible provenance path supports them. Graph evidence whose canonical provenance
cannot be resolved is discarded from retrieval.

Deletion operations and rebuilds are audited and idempotent.

## Consequences

Graph maintenance needs reverse provenance indexes and lifecycle jobs, but stale
semantic facts become detectable and recoverable rather than permanent.

## Verification

- Deleting the only supporting evidence removes the derived edge from eligible
  graph retrieval.
- Rebuilding a graph publication from canonical sources yields equivalent
  provenance-bearing content.
- No citation can point only to provider-internal graph state.
