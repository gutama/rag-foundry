# ADR-0013: Curated versus extracted knowledge

- **Status:** Proposed
- **Date:** 2026-08-07

## Context

LLM/algorithmic extraction can discover useful entities and relations, but it is
probabilistic. Mixing those outputs with steward-maintained metadata, taxonomies,
and ontology facts would allow model output to silently become institutional
truth.

## Decision

Keep curated knowledge and extracted knowledge explicitly distinct in storage,
provenance, lifecycle, and query semantics.

Curated knowledge is created or approved through governed registries. Extracted
knowledge begins as a candidate assertion linked to source evidence and the
extraction profile. A candidate may inform retrieval and review only according to
the active semantic policy. It cannot overwrite a curated assertion or be
presented as authoritative merely because it was extracted repeatedly.

Promotion to curated/approved status requires the validation and approval process
in ADR-0014/ADR-0022.

## Consequences

Graph coverage can grow rapidly without weakening governance, at the cost of
maintaining status-aware query paths and review queues.

## Verification

- Every assertion exposes its origin and authority/status class.
- Re-extraction cannot replace a curated assertion automatically.
- Retrieval/evaluation can measure curated-only and candidate-assisted behavior
  separately.
