# ADR-0006: Model gateway and approved profiles

- **Status:** Accepted
- **Date:** 2026-08-07

## Context

Embedding, reranking, extraction, and generation models affect reproducibility,
privacy, cost, and output quality. Direct model calls scattered across domain
code would make model changes ungoverned and air-gapped enforcement fragile.

## Decision

All model use goes through a RAG Foundry model gateway and an approved,
versioned model profile.

Profiles identify the task, provider, model/revision, relevant tokenizer and
inference settings, data-handling class, and deployment policy. Local Ollama,
vLLM, sentence-transformers, and approved local rerankers are supported through
adapters. Remote providers, if ever enabled, require an explicit deployment
policy and must not be a hidden fallback.

Indexes record the embedding profile used to build them; extraction and answer
traces record their model profiles.

## Consequences

Model replacement becomes auditable and local-only deployments can enforce a
hard network boundary. Teams must manage a profile registry and compatibility
rules instead of changing model strings ad hoc.

## Verification

- Domain services cannot instantiate provider clients directly.
- An unapproved model profile fails closed.
- Reproducibility records identify the profile for every model-mediated stage.
