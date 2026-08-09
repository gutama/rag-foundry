# Specification: Source Ingestion, Parser Router, and Canonical Document Processing

## Track Overview
- **Track ID:** `ingestion_parsing`
- **Type:** Feature
- **Goal:** Build the source ingestion pipeline, object storage interface, parser provider interface, multi-format parser adapters (PDF, DOCX, XLSX, PPTX), intelligent parser router with OCR fallback (ADR-0008), and canonical document element extractor (`DocumentElement`, ADR-0002) for RAG Foundry.

## Functional Requirements
1. **Ingestion Connectors & Storage:**
   - Implement File Upload API (`/api/v1/sources/upload`) and Local Filesystem Connector (`connector-filesystem`).
   - Implement Object Storage interface (`ObjectStorageProvider`) supporting MinIO / S3 and local storage backends for raw document artifacts.
   - Preserve source file metadata, SHA-256 checksums, MIME types, and ACL policy references during ingestion.

2. **Parser Interface & Multi-Format Adapters (PDF & Office Docs):**
   - Build framework-independent `ParserProvider` interface (`parse(stream_or_path, options) -> CanonicalDocument`).
   - Implement **Native PDF Parser Adapter** (fast text extraction for native digital PDFs).
   - Implement **Docling Layout Parser Adapter** (structural parsing for complex PDF layouts, tables, headers, reading order, and Office formats: DOCX, XLSX, PPTX).
   - Implement **PaddleOCR Provider Adapter** (OCR text extraction for scanned or low-quality document images).

3. **Intelligent Parser Router & OCR Fallback (ADR-0008):**
   - Implement `ParserRouter` service to automatically select optimal parser.
   - Perform automated quality scoring on primary parse output (e.g., text density < 50 chars/page, missing font encodings).
   - Trigger PaddleOCR fallback router when primary text parse score falls below threshold.

4. **Canonical Document Elements & Diagnostics (ADR-0002):**
   - Extract structured `DocumentElement` list for every parsed document version:
     - `element_type` (heading, paragraph, table, list_item, figure)
     - `sequence_number` (int)
     - `text` (clean plain text)
     - `markdown` (formatted markdown)
     - `page_number` (1-based int)
     - `bounding_box` (normalized coordinates tuple `[x0, y0, x1, y1]`)
     - `metadata` (custom key-value dictionary)
   - Record `ParsingDiagnostics` metadata on document versions (parser name, parser version, parse duration, quality score, fallback triggered boolean).

5. **Asynchronous Execution & Job Tracking (ADR-0001):**
   - Implement async ingestion & parsing background job handler.
   - Maintain database job status state (`pending`, `processing`, `parsed`, `failed`) and persist detailed error tracebacks on failure.

## Non-Functional Requirements
- Support non-blocking async execution using `asyncio` and `asyncpg`.
- Maintain test coverage ≥80% across ingestion, storage, parsing, and routing services.
- Domain models must remain strictly framework-independent (no direct imports of third-party framework types in canonical domain core per ADR-0007/ADR-0025).

## Acceptance Criteria
- File upload API and filesystem connector store raw artifacts cleanly in object storage.
- Native PDF parser successfully extracts text and bounding boxes for digital PDFs.
- Docling parser parses multi-column layouts, tables, and Office formats (DOCX, XLSX, PPTX) into structured markdown.
- Scanned PDF fixtures with low text density automatically trigger PaddleOCR fallback.
- `DocumentElement` list correctly captures page numbers and bounding box coordinates for source citation alignment.
- Unit and integration test suite passes with ≥80% coverage.

## Out of Scope
- Vector embedding and structural chunking (handled in Phase 5 / retrieval track).
- SKOS classification and entity resolution (handled in taxonomy/ontology tracks).
