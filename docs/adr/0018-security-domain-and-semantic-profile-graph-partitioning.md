# ADR-0018: Security-domain and semantic-profile graph partitioning

- **Status:** Proposed
- **Date:** 2026-08-07

## Context

Graph traversal can infer sensitive relationships even when the final returned
nodes are filtered. Mixing incompatible ontology/taxonomy releases can also give
edges different meanings inside one traversal.

## Decision

Partition graph namespaces by at least workspace, semantic-profile publication,
and compatible security domain. Traversal operates only inside namespaces the
caller is authorized to query.

Cross-domain or cross-profile relationships are represented as governed mappings
outside ordinary traversal and require an explicit authorized federation policy
before use. Post-traversal filtering is not an acceptable substitute for
partition-aware authorization.

Physical database partitioning is optional; the isolation semantics are
mandatory and must be enforceable by the provider adapter.

## Consequences

Some facts may be duplicated between namespaces and cross-domain analytics become
more deliberate. In return, graph retrieval has a defensible confidentiality and
semantic-consistency boundary.

## Verification

- Security tests prove graph traversal cannot discover node/edge existence in an
  unauthorized partition.
- A query never mixes incompatible semantic-profile versions silently.
- Provider conformance tests enforce namespace isolation.
