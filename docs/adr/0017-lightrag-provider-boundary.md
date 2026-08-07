# ADR-0017: LightRAG provider boundary

- **Status:** Accepted
- **Date:** 2026-08-07

## Context

LightRAG can provide graph-enhanced retrieval, but allowing it to own canonical
knowledge, authorization, answer generation, or citations would duplicate RAG
Foundry governance and make the platform dependent on one graph implementation.
nano-GraphRAG is useful for experimentation and conformance, not as the standard
production graph path.

## Decision

Integrate LightRAG only through a graph-retrieval provider boundary.

RAG Foundry supplies authorized, provenance-bearing canonical/semantic inputs and
receives context/evidence candidates. RAG Foundry owns generation, authorization,
citation construction/validation, observability policy, and evaluation. LightRAG
output is context, never authoritative knowledge, and evidence without resolvable
RAG Foundry provenance is discarded.

nano-GraphRAG may implement the same provider contract for experiments,
conformance tests, and small research fixtures; it is not the production default.

## Consequences

The project gets graph-enhanced retrieval without surrendering its governance
boundary. Some native LightRAG end-to-end conveniences are intentionally not used.

## Verification

- The system operates correctly with the graph provider disabled.
- No LightRAG identifier is accepted as citation provenance without canonical
  resolution.
- Provider conformance tests can run against LightRAG and nano-GraphRAG adapters.
