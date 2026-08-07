# ADR-0002: Canonical document, evidence, and semantic models

- **Status:** Accepted
- **Date:** 2026-08-07

## Context

Multiple parsers and retrieval providers otherwise create incompatible chunk,
citation, and entity representations. Re-parsing per index also breaks citation
stability and makes provenance difficult to audit.

## Decision

RAG Foundry owns a canonical, provider-neutral model and follows a parse-once,
distribute-many rule.

The minimum model includes immutable document revisions, canonical document
elements, chunks, evidence spans, metadata, semantic assertions, entities, and
citation references. Evidence references must resolve to a document revision and
the narrowest available source location (page/element plus coordinates or text
offsets when the parser can provide them).

Chunking, lexical indexing, vector indexing, graph extraction, reranking, and
answer generation consume this canonical representation. Provider-native output
is converted at the adapter boundary and is never the system-of-record schema.

## Consequences

Every downstream index can be rebuilt from the same parsed artifacts and
citations remain comparable across retrieval strategies. Adapters have extra
conversion work, but provider replacement no longer implies a data-model rewrite.

## Verification

- A canonical evidence reference round-trips from source document to answer
  citation without provider-specific identifiers.
- Re-indexing does not require re-parsing when the document revision and parser
  profile are unchanged.
- Semantic assertions always retain resolvable evidence provenance.
