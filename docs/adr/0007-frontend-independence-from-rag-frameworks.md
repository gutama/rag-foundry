# ADR-0007: Frontend independence from RAG frameworks

- **Status:** Accepted
- **Date:** 2026-08-07

## Context

Kotaemon and other RAG frameworks provide useful UX ideas, but coupling the
product UI to a framework's internal models or routes would make the framework a
de facto platform boundary and obstruct provider replacement.

## Decision

The React/TypeScript frontend talks only to RAG Foundry-owned API contracts.

Conversation, retrieval trace, citation, document, governance, approval, and
evaluation types are defined by RAG Foundry. Framework adapters may translate
their native types on the server side but no provider-specific object, endpoint,
or identifier is exposed as a required client contract.

Streaming responses use a RAG Foundry event contract that can carry answer
deltas, evidence/citation updates, warnings, and abstention without assuming a
particular generation framework.

## Consequences

The project must implement and maintain its own stable client API, but it can
adopt useful UI patterns without inheriting a framework's architecture.

## Verification

- The frontend builds and its contract tests pass with graph providers disabled.
- Removing or replacing a RAG framework does not require client model changes.
- Provider-native IDs do not appear in public frontend types.
