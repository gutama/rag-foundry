# ADR-0001: Modular monolith and worker topology

- **Status:** Proposed
- **Date:** 2026-08-07

## Context

RAG Foundry needs strong transactional boundaries for governance while parsing,
embedding, graph extraction, indexing, and evaluation have different resource
and scaling characteristics. Splitting every capability into a service now would
add operational cost and distributed consistency problems before those seams
are proven.

## Decision

Build the application as a framework-independent modular monolith with explicit
domain modules and independently scalable asynchronous workers.

- The API and domain core share one Python codebase and canonical contracts.
- Long-running or compute-heavy work runs through durable jobs in workers.
- Module boundaries are enforced at the domain/service interface, not by network
  calls.
- External retrieval, model, storage, and graph systems are reached only through
  provider adapters.
- A module may become an independent service later only when scaling, isolation,
  ownership, or reliability evidence justifies the added distributed-systems
  cost.

## Consequences

The compact deployment stays simple and transactional while workers can scale
independently. The trade-off is that module discipline must be enforced in code;
otherwise the monolith can become tightly coupled.

## Verification

- Domain modules can be tested without running LightRAG, model servers, or scale
  storage backends.
- Worker jobs are idempotent and can be retried without corrupting publication
  state.
- No RAG framework type appears in canonical domain interfaces.
