# ADR-0008: Parser routing and OCR fallback

- **Status:** Accepted
- **Date:** 2026-08-07

## Context

No single parser is best for born-digital PDFs, scans, office documents, tables,
figures, and equations. Silent OCR on every file is expensive and can degrade
text that was already extractable.

## Decision

Use a capability-based parser router that normalizes every parser result into the
canonical document model from ADR-0002.

Routing considers media type, document characteristics, configured parser
profile, and quality signals. OCR is a fallback for pages or regions that lack
usable text, not an unconditional second parse. The canonical representation
retains page/element ordering, coordinates when available, tables/figures as
structured elements, and parser/OCR provenance.

Parsing and OCR versions are recorded so canonical artifacts can be reproduced.
Low-confidence extraction is flagged rather than silently treated as clean text.

## Consequences

Document quality improves without tying ingestion to one parser. Routing and
quality scoring add test surface and require representative corpus fixtures.

## Verification

- Born-digital pages do not invoke OCR when extraction quality meets policy.
- OCR fallback preserves source-page provenance.
- Equivalent parser outputs satisfy the same canonical model conformance tests.
