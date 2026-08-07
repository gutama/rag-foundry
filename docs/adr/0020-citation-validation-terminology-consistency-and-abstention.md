# ADR-0020: Citation validation, terminology consistency, and abstention

- **Status:** Accepted
- **Date:** 2026-08-07

## Context

A plausible answer is not sufficient for institutional document intelligence.
Claims must be grounded in authorized evidence, terminology should follow governed
vocabulary where relevant, and the system must decline unsupported conclusions.

## Decision

RAG Foundry owns a post-generation answer-validation stage.

Material factual claims must map to authorized evidence references. Citation
references are validated for existence, access, document revision, and source
span. Where an approved taxonomy/ontology defines the relevant terminology, the
answer validator detects material naming/identity inconsistencies and can correct,
flag, or reject the answer according to policy.

If evidence coverage, citation validity, contradiction checks, or configured
confidence/evaluation gates are insufficient, the response abstains or explicitly
states the unsupported portion instead of inventing support.

## Consequences

Answer latency and complexity increase, but evidence-linked outputs become
auditable and safer for institutional use.

## Verification

- Synthetic unsupported claims fail citation validation.
- Citations cannot reference unauthorized or superseded evidence.
- Golden tests include expected abstentions, not only answer-match cases.
