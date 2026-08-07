# ADR-0005: Authorization-before-retrieval and semantic-disclosure policy

- **Status:** Accepted
- **Date:** 2026-08-07

## Context

Post-filtering unauthorized search hits is insufficient: restricted titles,
metadata, taxonomy memberships, graph neighbors, embeddings, or generated text
can leak before the final result is filtered.

## Decision

Authorization is a precondition for every information-bearing stage.

Enforce policy before metadata disclosure, lexical/dense retrieval, reranking,
semantic expansion, graph traversal, prompt construction, and generation.
Provider queries receive an authorized candidate scope or security partition;
providers do not decide access policy. Deny is the default when policy context is
missing or cannot be evaluated.

Authorization decisions use stable resource/security-domain identifiers and are
recorded in audit traces without exposing restricted content.

## Consequences

Some retrieval optimizations become harder because access constraints must be
carried into indexes and graph partitions. This cost is accepted because a
post-retrieval-only model cannot meet the platform's confidentiality goals.

## Verification

- Unauthorized resources cannot be inferred from hit counts, metadata results,
  graph traversal, reranker input, prompts, or citations.
- Security tests cover direct retrieval and indirect semantic/graph expansion.
- A provider failure cannot broaden the caller's authorized scope.
