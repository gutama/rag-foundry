# ADR-0015: Hybrid retrieval and rank-fusion policy

- **Status:** Accepted
- **Date:** 2026-08-07

## Context

Dense retrieval captures semantic similarity while lexical retrieval is strong
for exact terminology, identifiers, and rare phrases. Their raw scores are not
directly comparable, and graph retrieval has different semantics again.

## Decision

Make authorized lexical plus dense retrieval the default baseline, fuse candidate
ranks with a deterministic rank-fusion policy (reciprocal-rank fusion by default),
then apply an approved cross-encoder reranker to the bounded candidate set.

Candidate budgets, RRF parameters, reranker profile, filters, and tie-breaking are
versioned retrieval-profile settings. Graph/semantic expansion contributes
additional evidence candidates through explicit providers; it does not replace
the lexical+dense baseline by default.

Authorization from ADR-0005 constrains candidates before retrieval/fusion and is
never delegated to the reranker.

## Consequences

The baseline is robust across query types without calibrating heterogeneous raw
scores. Additional stages add latency, so evaluation must justify candidate
budgets and reranking cost.

## Verification

- Golden evaluation reports lexical, dense, fused, and reranked metrics
  separately.
- Ranking is reproducible for a pinned retrieval profile.
- Disabling graph expansion leaves a complete supported retrieval path.
